#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Bar charts of a git repo in the terminal: commits and lines of code per day, week or month.

Two charts share one time axis, so their columns line up:

  1. commits per bucket: non-merge commits reachable from HEAD, by author date
  2. lines of code at the end of each bucket: the running sum of added minus
     deleted lines along the first-parent chain of HEAD, by committer date.
     Merges count with their diff against the first parent, so a merged
     branch's lines land on the day of the merge and the final total equals
     the text lines at HEAD. Binary files and lockfiles are left out.
     The bars stack three kinds of lines, src at the bottom, then tests, then docs,
     each in its own color (without color: █ ▓ ░ shading); -k picks which to chart.

Every file is one kind: that of the first rule it matches among -x (left out),
then --src, --tests and --docs in the order given, then the built-in docs rules
(Markdown and kb/, docs/), then the built-in tests rules (test directories and
test file names); anything else is src. A GLOB matches the path from the repo
root or the file name; `name/` matches the files under any directory of that
name, `a/b/` the files under that path.

The y axis is linear with round ticks and a dotted gridline near each labelled
row's top edge, where its value lies; the chart top is rounded up to the next tick.
--log switches both charts to a 1-2-5 ladder, one step per row, which spreads
out many small values sitting under a few spikes (bar heights then stop being
proportional). With --values each bar gets its exact number underneath: the
commit count, and for lines of code the change in that bucket (+120, -35)
rather than the total, which the bar and the title already show.

    repocharts.py                   # this repo, by day, as much history as fits
    repocharts.py -n 30 -v          # the last 30 days, numbers under the bars
    repocharts.py -b week -H 4      # by week, 4 rows high
    repocharts.py -b week --log     # by week, small weeks readable next to spikes
    repocharts.py ~/Code/x -b month # another repo, by month
    repocharts.py -x vendor/        # leave more files out of the line count
    repocharts.py -k src            # only src in the line chart, no tests or docs
    repocharts.py --tests 'it/' --src 'docs/*.py'  # fix which kind some files are
"""

import argparse
import itertools
import math
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from fnmatch import fnmatchcase
from fractions import Fraction
from pathlib import Path
from typing import NamedTuple

GRANULARITIES = ('day', 'week', 'month')
# Generated dependency pins, not code; matched against file names.
LOCKFILES = (
    '*.lock',
    'package-lock.json',
    'npm-shrinkwrap.json',
    'pnpm-lock.yaml',
    'go.sum',
    'Package.resolved',
)
# Kinds of lines of code, in stacking order from the bottom.
KINDS = ('src', 'tests', 'docs')
# Built-in kind rules, tried after -x and --src/--tests/--docs; files they miss are src. Docs go first,
# so Markdown is docs even in a test directory and kb/test-plan.md stays docs.
DOC_RULES = ('kb/', 'docs/', 'doc/', '*.md', '*.mdx', '*.markdown', '*.rst', '*.adoc')
TEST_RULES = (
    *('test/', 'tests/', '*Tests/', '__tests__/', '__mocks__/', 'spec/', 'e2e/', 'cypress/', 'testdata/'),
    *('test_*', 'test-*', '*_test.*', '*.test.*', '*.spec.*', '*_spec.*', 'conftest.py'),
)
DEFAULT_RULES = (*(('docs', p) for p in DOC_RULES), *(('tests', p) for p in TEST_RULES))
BLOCKS = ' ▁▂▃▄▅▆▇█'
SHADES = '█▓░'  # without color, a full cell shows its layer by shading, bottom layer first
GUTTER = 4  # width of the y-axis labels; compact() never needs more
MAX_COL = 3  # widest column per bucket without --values: a 2-cell bar plus a 1-cell gap
MAX_BAR = MAX_COL - 1
EXACT_BELOW = 10_000  # --values prints smaller numbers in full, larger ones like compact()
UNITS = {'k': 10**3, 'M': 10**6, 'G': 10**9}
BOLD, DIM, RED, GREEN, YELLOW, MAGENTA, CYAN = '1', '2', '31', '32', '33', '35', '36'
KIND_COLORS = {'src': CYAN, 'tests': YELLOW, 'docs': MAGENTA}
# Y axis
NICE = tuple(Fraction(c) for c in ('1', '1.5', '2', '2.5', '3', '4', '5', '6', '8'))  # tick intervals x 10^e
MAX_TICKS = 6  # labels per chart before they thin out to every 2nd, 4th, ... row
MIN_FILL = Fraction(3, 5)  # fewer labels are fine when more would leave the tallest bar below this
LADDERS = ((1, 2, 5), (1, 3), (1,))  # --log steps per decade, densest first
GRID = '˙'  # a tick's value lies on its row's top edge; this dot sits about 1/5 row below it in
# common monospace fonts, where a centred '·' would read half a row low. Even labelled rows only,
# so labels on every row get a line on every other one, and a 1-row chart gets none


class RepoError(Exception):
    pass


@dataclass
class Series:
    starts: list[date]
    commits: list[int]
    loc: dict[str, list[int]]  # kind -> lines of code at the end of each bucket, bottom layer first
    loc_before: dict[str, int]  # kind -> lines of code just before the first bucket

    @property
    def loc_stacks(self) -> list[tuple[int, ...]]:
        """Each bucket's lines of code, one number per kind."""
        return list(zip(*self.loc.values()))

    @property
    def loc_total(self) -> list[int]:
        return [sum(stack) for stack in self.loc_stacks]

    @property
    def loc_deltas(self) -> list[int]:
        totals = self.loc_total
        return [after - before for before, after in zip([sum(self.loc_before.values()), *totals], totals)]


@dataclass
class Scale:
    """How values map onto chart rows; rows count from the bottom, 1 being the lowest."""

    height: int
    ticks: dict[int, int]  # row -> the value at its top edge, labelled on the y axis
    grid: set[int]  # rows whose top edge gets a gridline
    to_rows: Callable[[int], float]  # value -> bar height in rows


class Cell(NamedTuple):
    """One character of a bar: a block in the color of one layer, over the background of another."""

    char: str
    lower: int | None = None  # layer drawn by the block
    upper: int | None = None  # layer filling the rest of the cell, behind the block


BLANK = Cell(' ')


class Paint:
    def __init__(self, enabled):
        self.enabled = enabled

    def __call__(self, text, code):
        return f'\033[{code}m{text}\033[0m' if self.enabled and text else text


# Buckets ---------------------------------------------------------------------


def bucket_start(day: date, by: str) -> date:
    if by == 'week':
        return day - timedelta(days=day.weekday())
    if by == 'month':
        return day.replace(day=1)
    return day


def shift(start: date, by: str, k: int) -> date:
    """Move a bucket start by k buckets (k may be negative)."""
    if by == 'day':
        return start + timedelta(days=k)
    if by == 'week':
        return start + timedelta(weeks=k)
    months = start.year * 12 + start.month - 1 + k
    return date(months // 12, months % 12 + 1, 1)


def count_periods(first: date, last: date, by: str) -> int:
    """Number of buckets from first to last bucket start, both included."""
    if by == 'day':
        return (last - first).days + 1
    if by == 'week':
        return (last - first).days // 7 + 1
    return (last.year - first.year) * 12 + last.month - first.month + 1


# Git -------------------------------------------------------------------------


def git(repo: Path, *args: str, env=None) -> str:
    result = subprocess.run(
        ['git', '-C', str(repo), *args],
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
    )
    return result.stdout


def has_commits(repo: Path) -> bool:
    result = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', '-q', 'HEAD'], capture_output=True)
    return result.returncode == 0


def is_partial_clone(repo: Path) -> bool:
    result = subprocess.run(
        ['git', '-C', str(repo), 'config', '--get-regexp', r'^remote\..*\.promisor$'], capture_output=True, text=True
    )
    return any(line.split()[-1] == 'true' for line in result.stdout.splitlines())


def local_day(timestamp: str) -> date:
    return datetime.fromtimestamp(int(timestamp)).date()


def read_commit_days(repo: Path) -> list[date]:
    """Author day of every non-merge commit reachable from HEAD."""
    out = git(repo, 'log', '--no-merges', '--format=%at', 'HEAD')
    return [local_day(ts) for ts in out.split()]


def matches(path: str, pattern: str) -> bool:
    """Whether a glob matches the path or the file name.

    `name/` matches the files under any directory of that name, `a/b/` the files under that path.
    """
    parts = path.split('/')
    if not pattern.endswith('/'):
        return fnmatchcase(path, pattern) or fnmatchcase(parts[-1], pattern)
    pattern = pattern[:-1]
    dirs = ['/'.join(parts[:i]) for i in range(1, len(parts))] if '/' in pattern else parts[:-1]
    return any(fnmatchcase(d, pattern) for d in dirs)


def kind_rules(excludes, overrides=()) -> list[tuple[str | None, str]]:
    """(kind, glob) in the order they are tried: excludes (kind None), then overrides, then the built-in rules."""
    return [*((None, pattern) for pattern in excludes), *overrides, *DEFAULT_RULES]


def classify(path: str, rules) -> str | None:
    """The kind of the first rule matching the path, src when none does; None leaves the file out."""
    return next((kind for kind, pattern in rules if matches(path, pattern)), 'src')


def read_loc_changes(repo: Path, rules) -> list[tuple[date, dict[str, int]]]:
    """(committer day, added - deleted lines per kind) for each first-parent commit of HEAD, newest first.

    Renames count as a deletion plus an addition, so a file moved to another kind takes its lines along.
    Lazy fetching is off: in a partial clone git would otherwise download missing
    blobs one commit at a time, so a missing blob fails the call instead.
    """
    out = git(
        repo,
        '-c',
        'core.quotePath=false',
        'log',
        '--first-parent',
        '--diff-merges=first-parent',
        '--root',
        '--no-renames',
        '--no-relative',
        '--no-color',
        '--numstat',
        '--format=@%ct',
        'HEAD',
        env={'GIT_NO_LAZY_FETCH': '1'},
    )
    kinds = {}  # path -> kind; most paths come up in many commits
    changes = []
    for line in out.splitlines():
        if line.startswith('@'):
            changes.append((local_day(line[1:]), dict.fromkeys(KINDS, 0)))
            continue
        if '\t' not in line:
            continue
        added, deleted, path = line.split('\t', 2)
        if added == '-':  # a binary file
            continue
        path = path.strip('"')
        if path not in kinds:
            kinds[path] = classify(path, rules)
        if kind := kinds[path]:
            changes[-1][1][kind] += int(added) - int(deleted)
    return changes


# Series ----------------------------------------------------------------------


def build_series(commit_days, loc_changes, by: str, end: date, n: int, kinds=KINDS) -> Series:
    """The n buckets ending with the one that starts at `end`, with lines of code of the given kinds."""
    starts = [shift(end, by, i - n + 1) for i in range(n)]
    commits = Counter(bucket_start(day, by) for day in commit_days)
    deltas = defaultdict(Counter)  # bucket start -> kind -> change
    for day, change in loc_changes:
        deltas[bucket_start(day, by)].update(change)
    loc_before = {kind: sum(d[kind] for start, d in deltas.items() if start < starts[0]) for kind in kinds}
    loc = {
        kind: list(itertools.accumulate((deltas[start][kind] for start in starts), initial=loc_before[kind]))[1:]
        for kind in kinds
    }
    return Series(starts, [commits[start] for start in starts], loc, loc_before)


# Scales ----------------------------------------------------------------------


def compact(n: int) -> str:
    value, unit = float(n), ''
    for next_unit in UNITS:
        if round(value) < 1000:
            break
        value, unit = value / 1000, next_unit
    if not unit:
        return str(n)
    return f'{value:.1f}'.removesuffix('.0') + unit if value < 9.95 else f'{value:.0f}{unit}'


def prints_exactly(value: Fraction) -> bool:
    """Whether compact() shows this value without rounding, within the y-axis gutter."""
    if value.denominator != 1:
        return False
    label = compact(int(value))
    unit = UNITS.get(label[-1])
    shown = Fraction(label[:-1]) * unit if unit else Fraction(label)
    return shown == value and len(label) <= GUTTER


def nice_interval(minimum: Fraction, count: int) -> Fraction:
    """The smallest NICE x 10^e >= minimum whose first `count` multiples all print exactly."""
    exp = math.floor(math.log10(minimum))
    for e in (exp, exp + 1, exp + 2):
        for c in NICE:
            interval = c * Fraction(10) ** e
            if interval >= minimum and all(prints_exactly(interval * k) for k in range(1, count + 1)):
                return interval
    raise ValueError(f'no tick interval fits {minimum} in {GUTTER} characters')


def label_spacings(height: int) -> list[int]:
    """Rows between labels to try, most labels first: powers of 2 from MAX_TICKS labels, then the full height."""
    every = 1
    while height / every > MAX_TICKS:
        every *= 2
    spacings = []
    while every < height:
        spacings.append(every)
        every *= 2
    return [*spacings, height]


def linear_scale(values, height: int) -> Scale:
    """A round tick every few rows, the chart top rounded up so the tallest bar fits.

    Takes the most labels that still let the tallest bar reach MIN_FILL of the chart,
    else the spacing that lets it reach highest.
    """
    top = max(values, default=0)
    if top <= 0:
        return Scale(height, {}, set(), lambda v: 0.0)
    best = None
    for every in label_spacings(height):
        interval = nice_interval(Fraction(top * every, height), height // every)
        step = interval / every  # value per row
        fill = top / (step * height)
        if best is None or fill > best[0]:
            best = (fill, step, every)
        if fill >= MIN_FILL:
            break
    _, step, every = best
    ticks = {row: int(step * row) for row in range(every, height + 1, every)}
    return Scale(height, ticks, {row for row in ticks if row % 2 == 0}, lambda v: float(v / step))


def ladder(mults, low: int, top: int) -> list[int]:
    """Ladder values (mults x 10^e) from the largest one <= low up to the first one >= top."""
    steps = []
    for exp in itertools.count(len(str(low)) - 1):
        for m in mults:
            value = m * 10**exp
            steps = [value] if value <= low else [*steps, value]
            if value >= top:
                return steps


def log_scale(values, height: int) -> Scale:
    """A ladder step per row (or per few rows), starting just below the smallest value.

    Uses the densest ladder whose steps fit the chart. When even decades do not fit,
    the lowest ones are dropped and their values share the bottom row.
    """
    positive = [v for v in values if v > 0]
    if not positive:
        return Scale(height, {}, set(), lambda v: 0.0)
    low, top = min(positive), max(positive)
    for mults in LADDERS:
        steps = ladder(mults, low, top)
        if len(steps) <= height:
            break
    else:
        steps = steps[-height:]
    per_step = height // len(steps)
    bounds = [0, *steps]

    def to_rows(v):
        if v <= 0:
            return 0.0
        for i, (lo, hi) in enumerate(zip(bounds, bounds[1:])):
            if v <= hi:
                part = v / hi if lo == 0 else math.log(v / lo) / math.log(hi / lo)
                return (i + part) * per_step
        return float(len(steps) * per_step)

    ticks = {(i + 1) * per_step: step for i, step in enumerate(steps)}
    grid = {row for row, step in ticks.items() if str(step).rstrip('0') == '1' and height > 1}  # decades
    return Scale(height, ticks, grid, to_rows)


# Rendering -------------------------------------------------------------------


def stack_bounds(stack, scale: Scale) -> list[int]:
    """Where each layer of a bar ends, in eighths of a row from the bottom.

    The top sits where a bar of the total would, so a nonzero total gets at least an eighth;
    the bounds in between are the running sums rounded to an eighth.
    """
    sums = list(itertools.accumulate(max(0, v) for v in stack))
    if not sums[-1]:
        return [0] * len(sums)
    top = min(scale.height * 8, max(1, round(scale.to_rows(sums[-1]) * 8)))
    return [*(min(top, round(scale.to_rows(s) * 8)) for s in sums[:-1]), top]


def stack_cell(bounds: list[int], row: int) -> Cell:
    """The cell `row` rows up a bar (0 = bottom) whose layers end at `bounds`.

    A cell shows at most two layers, a block over a background, and only one in the bar's top
    cell, where the background must stay empty; the smallest parts merge into a neighbour
    until the rest fits, so the larger layer wins.
    """
    floor = row * 8
    runs, below = [], 0  # [layer, eighths] of the layers in this cell, bottom up
    for layer, top in enumerate(bounds):
        eighths = min(top, floor + 8) - max(below, floor)
        if eighths > 0:
            runs.append([layer, eighths])
        below = top
    filled = sum(eighths for _, eighths in runs)
    while len(runs) > (2 if filled == 8 else 1):
        i = min(range(len(runs)), key=lambda i: runs[i][1])
        _, eighths = runs.pop(i)
        runs[max(i - 1, 0)][1] += eighths
    if not runs:
        return BLANK
    if len(runs) == 2:
        (lower, eighths), (upper, _) = runs
        return Cell(BLOCKS[eighths], lower, upper)
    return Cell(BLOCKS[filled], runs[0][0])


def bar_rows(stacks, scale: Scale, col: int) -> list[list[Cell]]:
    """Rows top to bottom; each bucket takes `col` cells, the last one a gap when col > 1.

    A stack is a bucket's values, one per layer, drawn bottom up.
    """
    bar = min(col - 1, MAX_BAR) if col > 1 else 1
    gap = col - bar
    bounds = [stack_bounds(stack, scale) for stack in stacks]
    return [
        [cell for b in bounds for cell in [stack_cell(b, r)] * bar + [BLANK] * gap]
        for r in reversed(range(scale.height))
    ]


def value_label(n: int, signed: bool = False) -> str:
    """The number printed under a bar: empty for 0, exact below EXACT_BELOW."""
    if n == 0:
        return ''
    sign = '-' if n < 0 else '+' if signed else ''
    return sign + (str(abs(n)) if abs(n) < EXACT_BELOW else compact(abs(n)))


def value_labels(series: Series) -> tuple[list[str], list[str]]:
    """Labels for --values: commit counts, and signed changes in lines of code."""
    return [value_label(c) for c in series.commits], [value_label(d, signed=True) for d in series.loc_deltas]


def shade(cell: Cell) -> str:
    """The cell without color: full cells shaded by the layer filling most of them, a bar's top cell as is."""
    if cell.upper is not None:
        return SHADES[cell.lower if BLOCKS.index(cell.char) > 4 else cell.upper]
    return SHADES[cell.lower] if cell.char == BLOCKS[8] else cell.char


def paint_row(cells: list[Cell], grid: bool, colors, paint: Paint) -> str:
    """Bars in their layers' colors (`colors` by layer), shaded without color.

    Blank cells are a dim gridline in grid rows; elsewhere the trailing ones are dropped.
    """
    end = len(cells) if grid else max((i + 1 for i, cell in enumerate(cells) if cell != BLANK), default=0)
    out = []
    for (lower, upper), run in itertools.groupby(cells[:end], key=lambda cell: (cell.lower, cell.upper)):
        run = list(run)
        if lower is None:
            out.append(paint(GRID * len(run), DIM) if grid else ' ' * len(run))
        elif not paint.enabled:
            out.append(''.join(map(shade, run)))
        else:
            code = colors[lower] if upper is None else f'{colors[lower]};{int(colors[upper]) + 10}'  # 3x -> 4x: bg
            out.append(paint(''.join(cell.char for cell in run), code))
    return ''.join(out)


def value_row(labels: list[str], col: int, color: str, paint: Paint) -> str:
    cells = (paint(label, RED if label.startswith('-') else color) + ' ' * (col - len(label)) for label in labels)
    return ''.join(cells).rstrip()


def x_axis(starts: list[date], by: str, col: int) -> tuple[str, str]:
    """The axis line with a tick under each label, and the label line.

    Labels are placed left to right wherever they fit two cells after the previous one.
    Day and week labels are MM-DD, with the year on the first one and wherever it changes.
    """
    width = len(starts) * col
    ticks = ['─'] * width
    labels = ''
    year = None
    for i, start in enumerate(starts):
        offset = i * col
        if labels and offset < len(labels) + 2:
            continue
        if by == 'month':
            text = start.strftime('%Y-%m')
        else:
            text = start.strftime('%m-%d' if start.year == year else '%Y-%m-%d')
        if labels and offset + len(text) > width:
            break
        labels = labels.ljust(offset) + text
        ticks[offset] = '┬'
        year = start.year
    return ''.join(ticks), labels


def render_chart(
    head: list[str], stacks, scale: Scale, starts, by: str, col: int, colors, paint: Paint, labels=None
) -> list[str]:
    """Title lines, bar rows, the --values row when labels are given, the axis and its dates."""
    lines = list(head)
    for i, row in enumerate(bar_rows(stacks, scale, col)):
        row_number = scale.height - i
        tick = scale.ticks.get(row_number)
        label, edge = ('', '│') if tick is None else (compact(tick), '┤')
        lines.append(paint(f'{label:>{GUTTER}} {edge}', DIM) + paint_row(row, row_number in scale.grid, colors, paint))
    if labels is not None:
        lines.append(paint(f'{"":>{GUTTER}} │', DIM) + value_row(labels, col, colors[0], paint))
    ticks, dates = x_axis(starts, by, col)
    lines.append(paint(f'{"0":>{GUTTER}} └{ticks}', DIM))
    lines.append(paint(f'{"":>{GUTTER}}  {dates}', DIM))
    return lines


def plural(n: int, unit: str) -> str:
    return f'{n} {unit}' if n == 1 else f'{n} {unit}s'


def commits_title(series: Series, by: str, paint: Paint) -> str:
    return (
        paint(f'Commits per {by}', BOLD)
        + f' · {sum(series.commits):,} in {plural(len(series.starts), by)} · peak {max(series.commits):,}'
    )


def loc_title(series: Series, excluded: list[str], paint: Paint) -> str:
    before, after = sum(series.loc_before.values()), series.loc_total[-1]
    title = paint('Lines of code', BOLD) + f' · {before:,} → {after:,} ({after - before:+,})'
    if excluded:
        title += paint(f' · excluding {", ".join(excluded)}', DIM)
    return title


def legend(series: Series, colors, paint: Paint) -> str:
    """Each kind's swatch, its lines at the end and its change over the window."""
    items = []
    for layer, (kind, lines) in enumerate(series.loc.items()):
        swatch = paint(BLOCKS[8], colors[layer]) if paint.enabled else SHADES[layer]
        items.append(f'{swatch} {kind} {lines[-1]:,} ({lines[-1] - series.loc_before[kind]:+,})')
    return f'{"":>{GUTTER}}  ' + '  '.join(items)


# Main ------------------------------------------------------------------------


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f'must be at least 1: {text}')
    return value


def kind_list(text: str) -> tuple[str, ...]:
    picked = {kind.strip() for kind in text.split(',')} - {''}
    if not picked or not picked <= set(KINDS):
        raise argparse.ArgumentTypeError(f'pick from {",".join(KINDS)}: {text}')
    return tuple(kind for kind in KINDS if kind in picked)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='repocharts',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('path', nargs='?', default='.', help='any directory inside the repo (default: .)')
    parser.add_argument('-b', '--by', choices=GRANULARITIES, default='day', help='bucket size (default: day)')
    parser.add_argument(
        '-n',
        '--last',
        type=positive_int,
        metavar='N',
        help='show the last N buckets (default: the whole history, or as much as fits the terminal)',
    )
    parser.add_argument(
        '-H', '--height', type=positive_int, default=8, help='rows per chart (default: 8; 1 is a sparkline)'
    )
    parser.add_argument(
        '--log',
        action='store_true',
        help='logarithmic y axis, one 1-2-5 step per row: spreads out small values under a few spikes',
    )
    parser.add_argument(
        '-v',
        '--values',
        action='store_true',
        help='print the exact number under each bar: commits, and the change in lines of code; '
        'columns widen to fit them, so fewer buckets fit the terminal',
    )
    parser.add_argument(
        '-k',
        '--kinds',
        type=kind_list,
        default=KINDS,
        metavar='LIST',
        help='which lines of code to chart, stacked bottom up: src, tests, docs, comma-separated (default: all)',
    )
    parser.add_argument(
        '-x',
        '--exclude',
        action='append',
        default=[],
        metavar='GLOB',
        help='leave matching files out of the line count; matched against the path and the file name, '
        '`dir/` against directories; repeatable',
    )
    built_in = {
        'src': 'files no rule matches are src',
        'tests': f'built in: {" ".join(TEST_RULES)}',
        'docs': f'built in, tried before the tests ones: {" ".join(DOC_RULES)}',
    }
    for kind in KINDS:
        parser.add_argument(
            f'--{kind}',
            dest='rules',
            action='append',
            default=[],
            type=lambda glob, kind=kind: (kind, glob),
            metavar='GLOB',
            help=f'count matching files as {kind}, ahead of the built-in rules; repeatable, the first match wins '
            f'({built_in[kind]})',
        )
    parser.add_argument(
        '--with-lockfiles',
        action='store_true',
        help=f'count lockfiles as code ({", ".join(LOCKFILES)})',
    )
    parser.add_argument('--no-color', action='store_true', help='plain output (also when NO_COLOR is set)')
    return parser.parse_args(argv)


def run(args) -> None:
    repo = Path(args.path).expanduser()
    top = Path(git(repo, 'rev-parse', '--show-toplevel').strip())
    if not has_commits(repo):
        raise RepoError(f'{top}: no commits yet')
    by = args.by
    excludes = [*([] if args.with_lockfiles else LOCKFILES), *args.exclude]
    commit_days = read_commit_days(repo)
    try:
        loc_changes = read_loc_changes(repo, kind_rules(excludes, args.rules))
    except subprocess.CalledProcessError:
        if not is_partial_clone(repo):
            raise
        loc_changes = None

    days = [*commit_days, *(day for day, _ in loc_changes or [])]
    last_day = max(date.today(), *days)
    end = bucket_start(last_day, by)
    avail = max(10, shutil.get_terminal_size().columns - GUTTER - 3)
    wanted = args.last or count_periods(bucket_start(min(days), by), end, by)
    n = min(wanted, avail)
    series = build_series(commit_days, loc_changes or [], by, end, n, args.kinds)
    # With --values every bucket needs room for its widest number plus a gap.
    need = max(map(len, sum(value_labels(series), [])), default=0) + 1 if args.values else 1
    if n * need > avail:
        n = avail // need
        series = build_series(commit_days, loc_changes or [], by, end, n, args.kinds)
    if args.last and n < args.last:
        print(f'repocharts: the terminal fits {plural(n, by)}; showing the last {n}', file=sys.stderr)
    col = max(need, min(MAX_COL, avail // n))

    paint = Paint(not args.no_color and not os.environ.get('NO_COLOR') and sys.stdout.isatty())
    counts, changes = value_labels(series) if args.values else (None, None)
    scale_for = log_scale if args.log else linear_scale
    excluded = [*([] if args.with_lockfiles else ['lockfiles']), *args.exclude]
    if loc_changes is None:
        loc_block = [
            paint('Lines of code', BOLD) + ' · skipped: this is a partial clone, past file versions are not local',
            paint(f'{"":>{GUTTER}}  `git -C {top} backfill` downloads them in batches (can be large); then rerun', DIM),
        ]
    else:
        colors = tuple(KIND_COLORS[kind] for kind in args.kinds)
        head = [loc_title(series, excluded, paint), legend(series, colors, paint)]
        loc_scale = scale_for(series.loc_total, args.height)
        loc_block = render_chart(head, series.loc_stacks, loc_scale, series.starts, by, col, colors, paint, changes)
    commit_scale = scale_for(series.commits, args.height)
    commit_stacks = [(count,) for count in series.commits]
    log_note = ' · log scale' if args.log else ''
    blocks = [
        [paint(top.name, BOLD) + f' · by {by}{log_note} · {series.starts[0]} → {last_day}'],
        render_chart(
            [commits_title(series, by, paint)],
            commit_stacks,
            commit_scale,
            series.starts,
            by,
            col,
            (GREEN,),
            paint,
            counts,
        ),
        loc_block,
    ]
    print('\n\n'.join('\n'.join(block) for block in blocks))


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        run(args)
    except subprocess.CalledProcessError as e:
        print(e.stderr.strip() or str(e), file=sys.stderr)
        return 1
    except RepoError as e:
        print(f'repocharts: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

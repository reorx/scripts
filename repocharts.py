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

The y axis is linear with round ticks and a gridline along each labelled row's
top edge, where its value lies; the chart top is rounded up to the next tick.
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
    repocharts.py -x 'vendor/*'     # leave more files out of the line count
"""

import argparse
import itertools
import math
import os
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from fnmatch import fnmatchcase
from fractions import Fraction
from pathlib import Path

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
BLOCKS = ' ▁▂▃▄▅▆▇█'
GUTTER = 4  # width of the y-axis labels; compact() never needs more
MAX_COL = 3  # widest column per bucket without --values: a 2-cell bar plus a 1-cell gap
MAX_BAR = MAX_COL - 1
EXACT_BELOW = 10_000  # --values prints smaller numbers in full, larger ones like compact()
UNITS = {'k': 10**3, 'M': 10**6, 'G': 10**9}
BOLD, DIM, RED, GREEN, CYAN = '1', '2', '31', '32', '36'
# Y axis
NICE = tuple(Fraction(c) for c in ('1', '1.5', '2', '2.5', '3', '4', '5', '6', '8'))  # tick intervals x 10^e
MAX_TICKS = 6  # labels per chart before they thin out to every 2nd, 4th, ... row
MIN_FILL = Fraction(3, 5)  # fewer labels are fine when more would leave the tallest bar below this
LADDERS = ((1, 2, 5), (1, 3), (1,))  # --log steps per decade, densest first
GRID = '▔'  # drawn along the top edge of a labelled row, where its tick value lies; even rows only,
# so labels on every row get a line on every other one, and a 1-row chart gets none


class RepoError(Exception):
    pass


@dataclass
class Series:
    starts: list[date]
    commits: list[int]
    loc: list[int]
    loc_before: int  # lines of code just before the first bucket

    @property
    def loc_deltas(self) -> list[int]:
        return [after - before for before, after in zip([self.loc_before, *self.loc], self.loc)]


@dataclass
class Scale:
    """How values map onto chart rows; rows count from the bottom, 1 being the lowest."""

    height: int
    ticks: dict[int, int]  # row -> the value at its top edge, labelled on the y axis
    grid: set[int]  # rows whose top edge gets a gridline
    to_rows: Callable[[int], float]  # value -> bar height in rows


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


def is_excluded(path: str, patterns) -> bool:
    name = path.rsplit('/', 1)[-1]
    return any(fnmatchcase(path, p) or fnmatchcase(name, p) for p in patterns)


def read_loc_changes(repo: Path, excludes) -> list[tuple[date, int]]:
    """(committer day, added - deleted lines) for each first-parent commit of HEAD, newest first.

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
    changes = []
    for line in out.splitlines():
        if line.startswith('@'):
            changes.append([local_day(line[1:]), 0])
            continue
        if '\t' not in line:
            continue
        added, deleted, path = line.split('\t', 2)
        if added == '-' or is_excluded(path.strip('"'), excludes):  # '-' marks a binary file
            continue
        changes[-1][1] += int(added) - int(deleted)
    return [(day, delta) for day, delta in changes]


# Series ----------------------------------------------------------------------


def build_series(commit_days, loc_changes, by: str, end: date, n: int) -> Series:
    """The n buckets ending with the one that starts at `end`."""
    starts = [shift(end, by, i - n + 1) for i in range(n)]
    commits = Counter(bucket_start(day, by) for day in commit_days)
    deltas = Counter()
    for day, delta in loc_changes:
        deltas[bucket_start(day, by)] += delta
    loc_before = sum(delta for start, delta in deltas.items() if start < starts[0])
    loc, total = [], loc_before
    for start in starts:
        total += deltas[start]
        loc.append(total)
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


def bar_rows(values, scale: Scale, col: int) -> list[str]:
    """Rows top to bottom; each bucket takes `col` cells, the last one a gap when col > 1."""
    bar = min(col - 1, MAX_BAR) if col > 1 else 1
    gap = col - bar
    height = scale.height
    # Bar heights in eighths of a row; any nonzero value gets at least one.
    levels = [min(height * 8, max(1, round(scale.to_rows(v) * 8))) if v > 0 else 0 for v in values]
    rows = []
    for r in reversed(range(height)):
        cells = (BLOCKS[min(8, max(0, level - r * 8))] * bar + ' ' * gap for level in levels)
        rows.append(''.join(cells).rstrip())
    return rows


def value_label(n: int, signed: bool = False) -> str:
    """The number printed under a bar: empty for 0, exact below EXACT_BELOW."""
    if n == 0:
        return ''
    sign = '-' if n < 0 else '+' if signed else ''
    return sign + (str(abs(n)) if abs(n) < EXACT_BELOW else compact(abs(n)))


def value_labels(series: Series) -> tuple[list[str], list[str]]:
    """Labels for --values: commit counts, and signed changes in lines of code."""
    return [value_label(c) for c in series.commits], [value_label(d, signed=True) for d in series.loc_deltas]


def paint_row(row: str, grid_width: int, color: str, paint: Paint) -> str:
    """Bars in color; with a grid width, the blank cells up to it become a dim gridline."""
    if not grid_width:
        return paint(row, color)
    out = []
    for blank, run in itertools.groupby(row.ljust(grid_width), key=lambda ch: ch == ' '):
        text = ''.join(run)
        out.append(paint(GRID * len(text), DIM) if blank else paint(text, color))
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
    title: str, values, scale: Scale, starts, by: str, col: int, color: str, paint: Paint, labels=None
) -> list[str]:
    """Title, bar rows, the --values row when labels are given, the axis and its dates."""
    width = len(starts) * col
    lines = [title]
    for i, row in enumerate(bar_rows(values, scale, col)):
        row_number = scale.height - i
        tick = scale.ticks.get(row_number)
        label, edge = ('', '│') if tick is None else (compact(tick), '┤')
        grid_width = width if row_number in scale.grid else 0
        lines.append(paint(f'{label:>{GUTTER}} {edge}', DIM) + paint_row(row, grid_width, color, paint))
    if labels is not None:
        lines.append(paint(f'{"":>{GUTTER}} │', DIM) + value_row(labels, col, color, paint))
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
    after = series.loc[-1]
    title = paint('Lines of code', BOLD) + f' · {series.loc_before:,} → {after:,} ({after - series.loc_before:+,})'
    if excluded:
        title += paint(f' · excluding {", ".join(excluded)}', DIM)
    return title


# Main ------------------------------------------------------------------------


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f'must be at least 1: {text}')
    return value


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
        '-x',
        '--exclude',
        action='append',
        default=[],
        metavar='GLOB',
        help='leave matching files out of the line count; matched against the path and the file name; repeatable',
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
        loc_changes = read_loc_changes(repo, excludes)
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
    series = build_series(commit_days, loc_changes or [], by, end, n)
    # With --values every bucket needs room for its widest number plus a gap.
    need = max(map(len, sum(value_labels(series), [])), default=0) + 1 if args.values else 1
    if n * need > avail:
        n = avail // need
        series = build_series(commit_days, loc_changes or [], by, end, n)
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
        loc_title_text = loc_title(series, excluded, paint)
        loc_scale = scale_for(series.loc, args.height)
        loc_block = render_chart(loc_title_text, series.loc, loc_scale, series.starts, by, col, CYAN, paint, changes)
    commit_scale = scale_for(series.commits, args.height)
    log_note = ' · log scale' if args.log else ''
    blocks = [
        [paint(top.name, BOLD) + f' · by {by}{log_note} · {series.starts[0]} → {last_day}'],
        render_chart(
            commits_title(series, by, paint), series.commits, commit_scale, series.starts, by, col, GREEN, paint, counts
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

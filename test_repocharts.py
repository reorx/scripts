#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Behavior tests: uv run test_repocharts.py."""

import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('repocharts', Path(__file__).with_name('repocharts.py'))
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)

# Repos are built without the user's git config (signing, hooks, templates).
GIT_ENV = {
    **os.environ,
    'GIT_CONFIG_GLOBAL': '/dev/null',
    'GIT_CONFIG_NOSYSTEM': '1',
    'GIT_AUTHOR_NAME': 'T',
    'GIT_AUTHOR_EMAIL': 't@example.invalid',
    'GIT_COMMITTER_NAME': 'T',
    'GIT_COMMITTER_EMAIL': 't@example.invalid',
}


class Repo:
    """A throwaway git repo whose commits land at noon local time on the given days."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(exist_ok=True)
        self.git('init', '-q', '-b', 'main')

    def git(self, *args, day=None):
        env = dict(GIT_ENV)
        if day:
            stamp = f'{day.isoformat()}T12:00:00'
            env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        subprocess.run(['git', '-C', str(self.root), *args], env=env, check=True, capture_output=True)

    def write(self, name, lines):
        path = self.root / name
        if isinstance(lines, bytes):
            path.write_bytes(lines)
        else:
            path.write_text(''.join(f'{line}\n' for line in lines))

    def commit(self, day, **files):
        for name, lines in files.items():
            self.write(name.replace('__', '.'), lines)
        self.git('add', '-A')
        self.git('commit', '-q', '-m', f'on {day}', day=day)


def build_history(root):
    """main: d1 +10, d2 -3 (plus a lockfile and a binary), d4 +1, d5 merges a branch that added 4 on d3."""
    d1, d2, d3, d4, d5 = (date(2026, 1, n) for n in (5, 7, 13, 14, 20))
    repo = Repo(root)
    repo.commit(d1, a__py=[f'line {i}' for i in range(10)])
    repo.commit(
        d2,
        a__py=['x', 'y', 'line 5', 'line 6', 'line 7', 'line 8', 'line 9'],
        uv__lock=[f'pkg {i}' for i in range(100)],
        img__bin=b'\x00\x01\x02' * 50,
    )
    repo.git('checkout', '-q', '-b', 'feature')
    repo.commit(d3, b__py=['b'] * 4)
    repo.git('checkout', '-q', 'main')
    repo.commit(d4, c__py=['c'])
    repo.git('merge', '-q', '--no-ff', '-m', 'merge feature', 'feature', day=d5)
    return repo, (d1, d2, d3, d4, d5)


def run_main(*argv, columns=100):
    out, err = io.StringIO(), io.StringIO()
    with (
        patch.dict(os.environ, {'COLUMNS': str(columns), 'NO_COLOR': '1'}),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        code = app.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def parse_label(label):
    units = {'k': 1_000, 'M': 1_000_000, 'G': 1_000_000_000}
    return Fraction(label[:-1]) * units[label[-1]] if label[-1] in units else Fraction(label)


def bar_cells(row):
    """(offset, run) of each bar in a chart row; the y axis and gridlines are left out."""
    return [(m.start(), m.group()) for m in re.finditer(f'[{app.BLOCKS[1:]}{app.SHADES}]+', row[app.GUTTER + 2 :])]


def text(rows):
    """Bar rows as plain strings, trailing blanks dropped."""
    return [''.join(cell.char for cell in row).rstrip() for row in rows]


def bars(values, height, col):
    return text(app.bar_rows([(v,) for v in values], app.linear_scale(values, height), col))


def eighths(height):
    """A scale where every unit is an eighth of a row."""
    return app.Scale(height, {}, set(), lambda v: v / 8)


def chart_blocks(output):
    """Split the output into charts: each is the list of lines from its title to its label line."""
    blocks = output.strip('\n').split('\n\n')
    return [block.split('\n') for block in blocks[1:]]


def chart_body(block):
    """The bar rows of a chart drawn without --values, top to bottom: the lines whose y axis is '│' or '┤'."""
    return [line for line in block if line[app.GUTTER + 1 : app.GUTTER + 2] in ('│', '┤')]


class Buckets(unittest.TestCase):
    def test_a_week_starts_on_monday(self):
        self.assertEqual(app.bucket_start(date(2026, 11, 15), 'week'), date(2026, 11, 9))
        self.assertEqual(app.bucket_start(date(2026, 11, 9), 'week'), date(2026, 11, 9))

    def test_a_month_starts_on_its_first_day(self):
        self.assertEqual(app.bucket_start(date(2026, 2, 28), 'month'), date(2026, 2, 1))

    def test_a_day_is_its_own_bucket(self):
        self.assertEqual(app.bucket_start(date(2026, 2, 28), 'day'), date(2026, 2, 28))

    def test_shift_moves_whole_periods_across_years(self):
        self.assertEqual(app.shift(date(2026, 1, 1), 'month', -1), date(2025, 12, 1))
        self.assertEqual(app.shift(date(2025, 11, 1), 'month', 14), date(2027, 1, 1))
        self.assertEqual(app.shift(date(2026, 1, 5), 'week', -2), date(2025, 12, 22))
        self.assertEqual(app.shift(date(2026, 3, 1), 'day', -1), date(2026, 2, 28))

    def test_count_periods_is_inclusive(self):
        self.assertEqual(app.count_periods(date(2025, 11, 1), date(2026, 2, 1), 'month'), 4)
        self.assertEqual(app.count_periods(date(2026, 1, 5), date(2026, 1, 19), 'week'), 3)
        self.assertEqual(app.count_periods(date(2026, 1, 5), date(2026, 1, 5), 'day'), 1)


class Kinds(unittest.TestCase):
    """Every file counts as src, tests or docs; the first matching rule decides."""

    def kind(self, path, *overrides, excludes=()):
        return app.classify(path, app.kind_rules(excludes, overrides))

    def assertKind(self, kind, paths):
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.kind(path), kind)

    def test_markdown_and_files_under_kb_or_docs_are_docs(self):
        self.assertKind(
            'docs',
            (
                'README.md',
                'src/guide.mdx',
                'a/doc/api.adoc',
                'docs/index.rst',
                'docs/conf.py',
                'kb/plans/2026-11-11-x.md',
                'kb/data.json',
            ),
        )

    def test_test_directories_and_test_file_names_are_tests(self):
        self.assertKind(
            'tests',
            (
                'tests/helpers.py',
                'test/fixtures/a.json',
                'pkg/tests/x.py',
                'src/__tests__/App.tsx',
                'src/__mocks__/fs.js',
                'src/App.test.tsx',
                'src/api.spec.ts',
                'test_repocharts.py',
                'conftest.py',
                'pkg/util_test.go',
                'test-tsfwd.sh',
                'spec/models/user_spec.rb',
                'e2e/login.ts',
                'cypress/support/commands.js',
                'MyAppTests/FooTests.swift',
                'testdata/a.txt',
            ),
        )

    def test_everything_else_is_src(self):
        self.assertKind(
            'src',
            (
                'repocharts.py',
                'src/App.tsx',
                'latest.py',
                'protests.py',
                'contest/rank.py',
                'src/testing.ts',
                'Makefile',
            ),
        )

    def test_docs_rules_win_over_tests_rules(self):
        self.assertKind('docs', ('tests/README.md', 'kb/test-plan.md', 'docs/test_example.py'))

    def test_rules_from_the_command_line_come_first_in_their_order(self):
        self.assertEqual(self.kind('tests/fixtures/a.md', ('tests', 'tests/')), 'tests')
        self.assertEqual(self.kind('notes.txt', ('docs', '*.txt')), 'docs')
        self.assertEqual(self.kind('docs/conf.py', ('src', 'docs/conf.py')), 'src')
        self.assertEqual(self.kind('test_a.py', ('src', '*.py'), ('tests', 'test_*')), 'src')

    def test_excluded_files_are_left_out_whatever_their_kind(self):
        self.assertIsNone(self.kind('uv.lock', excludes=app.LOCKFILES))
        self.assertIsNone(self.kind('vendor/lib/README.md', ('docs', '*.md'), excludes=['vendor/']))

    def test_a_directory_rule_matches_a_bare_name_at_any_depth_and_a_path_from_the_root(self):
        self.assertTrue(app.matches('a/b/vendor/x.js', 'vendor/'))
        self.assertFalse(app.matches('vendor.js', 'vendor/'))
        self.assertFalse(app.matches('a/vendor', 'vendor/'))
        self.assertTrue(app.matches('site/content/a.html', 'site/content/'))
        self.assertFalse(app.matches('x/site/content/a.html', 'site/content/'))
        self.assertTrue(app.matches('x/site/content/a.html', '*/content/'))


def per_commit(changes):
    """(day, change over all kinds) of each commit, oldest first."""
    return sorted((day, sum(by_kind.values())) for day, by_kind in changes)


class GitHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo, self.days = build_history(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_commit_days_leave_out_merges(self):
        d1, d2, d3, d4, _ = self.days
        self.assertEqual(sorted(app.read_commit_days(self.repo.root)), [d1, d2, d3, d4])

    def test_loc_changes_follow_the_first_parent_so_a_merged_branch_counts_once(self):
        d1, d2, _, d4, d5 = self.days
        changes = app.read_loc_changes(self.repo.root, app.kind_rules(app.LOCKFILES))
        self.assertEqual(per_commit(changes), [(d1, 10), (d2, -3), (d4, 1), (d5, 4)])

    def test_loc_changes_sum_to_the_text_lines_at_head(self):
        changes = app.read_loc_changes(self.repo.root, app.kind_rules(app.LOCKFILES))
        self.assertEqual(sum(delta for _, delta in per_commit(changes)), 7 + 4 + 1)

    def test_lockfiles_count_when_not_excluded(self):
        changes = app.read_loc_changes(self.repo.root, app.kind_rules([]))
        self.assertEqual(sum(delta for _, delta in per_commit(changes)), 12 + 100)

    def test_exclude_patterns_match_paths_and_basenames(self):
        changes = app.read_loc_changes(self.repo.root, app.kind_rules([*app.LOCKFILES, 'b.py', 'c*']))
        self.assertEqual(sum(delta for _, delta in per_commit(changes)), 7)

    def test_lines_are_split_by_kind_and_a_moved_file_takes_its_lines_along(self):
        d1, d2 = date(2026, 2, 2), date(2026, 2, 3)
        repo = Repo(Path(self.tmp.name) / 'kinds')
        repo.commit(d1, app__py=['a'] * 5, helpers__py=['h'] * 4, test_app__py=['t'] * 3, README__md=['r'] * 2)
        (repo.root / 'tests').mkdir()
        repo.git('mv', 'helpers.py', 'tests/helpers.py')
        repo.commit(d2, README__md=['r'])
        changes = sorted(app.read_loc_changes(repo.root, app.kind_rules([])), key=lambda change: change[0])
        self.assertEqual(
            changes,
            [(d1, {'src': 9, 'tests': 3, 'docs': 2}), (d2, {'src': -4, 'tests': 4, 'docs': -1})],
        )


class PartialClone(unittest.TestCase):
    """A blob:none clone has no old file versions; diffing them would fetch blobs commit by commit."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        src, _ = build_history(Path(self.tmp.name) / 'src')
        src.git('config', 'uploadpack.allowFilter', 'true')
        self.clone = Path(self.tmp.name) / 'clone'
        subprocess.run(
            ['git', 'clone', '-q', '--filter=blob:none', f'file://{src.root}', str(self.clone)],
            env=GIT_ENV,
            check=True,
            capture_output=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def missing_objects(self):
        out = subprocess.run(
            ['git', '-C', str(self.clone), 'rev-list', '--objects', '--missing=print', 'HEAD'],
            env=GIT_ENV,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return [line for line in out.splitlines() if line.startswith('?')]

    def test_the_loc_chart_is_skipped_with_a_hint_and_nothing_is_fetched(self):
        missing = self.missing_objects()
        self.assertTrue(missing)
        code, out, _ = run_main(str(self.clone), '--by', 'week')
        self.assertEqual(code, 0)
        commits, loc = chart_blocks(out)
        self.assertTrue(commits[0].startswith('Commits per week · 4 in'), commits[0])
        self.assertIn('partial clone', loc[0])
        self.assertRegex('\n'.join(loc), r'`git -C \S+ backfill`')
        self.assertEqual(self.missing_objects(), missing)

    def test_after_git_backfill_the_loc_chart_is_drawn(self):
        subprocess.run(['git', '-C', str(self.clone), 'backfill'], env=GIT_ENV, check=True, capture_output=True)
        code, out, _ = run_main(str(self.clone), '--by', 'week')
        self.assertEqual(code, 0)
        _, loc = chart_blocks(out)
        self.assertTrue(loc[0].startswith('Lines of code · 0 → 12 (+12)'), loc[0])


class Series(unittest.TestCase):
    def test_buckets_cover_the_window_including_empty_periods(self):
        commit_days = [date(2026, 1, 5), date(2026, 1, 7), date(2026, 1, 20)]
        series = app.build_series(commit_days, [], 'week', end=date(2026, 1, 26), n=4)
        self.assertEqual(series.starts, [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19), date(2026, 1, 26)])
        self.assertEqual(series.commits, [2, 0, 1, 0])

    CHANGES = [
        (date(2025, 12, 30), {'src': 50, 'docs': 5}),
        (date(2026, 1, 5), {'src': 10, 'tests': 4}),
        (date(2026, 1, 20), {'src': -3}),
    ]

    def test_loc_is_the_running_total_per_kind_at_the_end_of_each_bucket(self):
        series = app.build_series([], self.CHANGES, 'week', end=date(2026, 1, 26), n=4)
        self.assertEqual(series.loc_before, {'src': 50, 'tests': 0, 'docs': 5})
        self.assertEqual(series.loc, {'src': [60, 60, 57, 57], 'tests': [4, 4, 4, 4], 'docs': [5, 5, 5, 5]})
        self.assertEqual(series.loc_total, [69, 69, 66, 66])
        self.assertEqual(series.loc_deltas, [14, 0, -3, 0])

    def test_only_the_chosen_kinds_are_kept_bottom_layer_first(self):
        series = app.build_series([], self.CHANGES, 'week', end=date(2026, 1, 26), n=4, kinds=('src', 'docs'))
        self.assertEqual(list(series.loc), ['src', 'docs'])
        self.assertEqual(series.loc_stacks, [(60, 5), (60, 5), (57, 5), (57, 5)])
        self.assertEqual(series.loc_total, [65, 65, 62, 62])
        self.assertEqual(series.loc_deltas, [10, 0, -3, 0])

    def test_window_reaches_back_before_the_first_commit(self):
        series = app.build_series([date(2026, 3, 2)], [], 'month', end=date(2026, 3, 1), n=3)
        self.assertEqual(series.starts, [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)])
        self.assertEqual(series.commits, [0, 0, 1])


class Bars(unittest.TestCase):
    def test_the_tallest_bar_fills_every_row(self):
        rows = bars([4, 2], height=2, col=1)
        self.assertEqual(rows, ['█', '██'])

    def test_a_small_nonzero_value_stays_visible(self):
        rows = bars([1000, 1], height=3, col=1)
        self.assertEqual(rows[-1][1], '▁')

    def test_zero_draws_nothing(self):
        rows = bars([0, 5, 0], height=1, col=1)
        self.assertEqual(rows, [' █'])

    def test_wide_columns_leave_a_gap_after_each_bar(self):
        rows = bars([1, 1], height=1, col=3)
        self.assertEqual(rows, ['██ ██'])

    def test_all_zero_draws_an_empty_chart(self):
        self.assertEqual(bars([0, 0], height=2, col=1), ['', ''])

    def test_bars_stay_two_cells_wide_in_wider_columns(self):
        self.assertEqual(bars([1, 1], height=1, col=5), ['██   ██'])

    def test_log_bars_grow_one_row_per_step(self):
        values = [1, 10, 100]
        rows = app.bar_rows([(v,) for v in values], app.log_scale(values, 3), col=1)
        self.assertEqual(text(rows), ['  █', ' ██', '███'])


def filled(cell):
    """Eighths of the cell a bar covers: a split cell is full, the upper layer drawn as its background."""
    return 8 if cell.upper is not None else app.BLOCKS.index(cell.char)


class StackedBars(unittest.TestCase):
    """Layers stack bottom up; a cell is a block in one layer's color over another layer's background."""

    def cells(self, stack, height):
        """One bar's cells, top to bottom, on a scale of one eighth of a row per unit."""
        return [row[0] for row in app.bar_rows([stack], eighths(height), col=1)]

    def test_layers_stack_bottom_up(self):
        self.assertEqual(self.cells((8, 8), 2), [app.Cell('█', 1), app.Cell('█', 0)])

    def test_a_boundary_inside_a_row_splits_the_cell_between_two_layers(self):
        self.assertEqual(self.cells((3, 13), 2), [app.Cell('█', 1), app.Cell('▃', 0, 1)])

    def test_the_top_cell_of_a_bar_takes_its_larger_layer(self):
        self.assertEqual(self.cells((11, 1), 2)[0], app.Cell('▄', 0))
        self.assertEqual(self.cells((9, 3), 2)[0], app.Cell('▄', 1))

    def test_three_layers_in_one_row_lose_the_smallest(self):
        self.assertEqual(self.cells((2, 1, 5), 1), [app.Cell('▃', 0, 2)])

    def test_an_empty_layer_takes_no_room(self):
        self.assertEqual(self.cells((8, 0, 8), 2), [app.Cell('█', 2), app.Cell('█', 0)])

    def test_a_stack_is_exactly_as_tall_as_a_bar_of_its_total(self):
        scale = app.linear_scale([169], 8)
        for stack in [(100, 50, 19), (1, 1, 1), (0, 0, 7), (160, 0, 9), (3, 97, 0)]:
            with self.subTest(stack=stack):
                stacked = app.bar_rows([stack], scale, 1)
                single = app.bar_rows([(sum(stack),)], scale, 1)
                self.assertEqual(
                    [filled(row[0]) for row in stacked],
                    [filled(row[0]) for row in single],
                )


class Painting(unittest.TestCase):
    COLORS = ('36', '33', '35')

    def paint(self, cells, grid=False, color=True):
        return app.paint_row(cells, grid, self.COLORS, app.Paint(color))

    def test_in_color_each_layer_has_its_own_color(self):
        self.assertEqual(self.paint([app.Cell('█', 0), app.Cell('▅', 2)]), '\033[36m█\033[0m\033[35m▅\033[0m')

    def test_in_color_a_split_cell_shows_the_lower_layer_over_the_upper_layers_background(self):
        self.assertEqual(self.paint([app.Cell('▃', 0, 1)]), '\033[36;43m▃\033[0m')

    def test_without_color_full_cells_are_shaded_by_their_larger_layer(self):
        cells = [
            app.Cell('█', 0),
            app.Cell('█', 1),
            app.Cell('█', 2),
            app.Cell('▃', 0, 1),
            app.Cell('▆', 1, 2),
            app.Cell('▃', 1),
        ]
        self.assertEqual(self.paint(cells, color=False), '█▓░▓▓▃')

    def test_blank_cells_become_a_dim_gridline_in_grid_rows_and_are_trimmed_elsewhere(self):
        cells = [app.Cell('█', 0), app.BLANK, app.BLANK]
        self.assertEqual(self.paint(cells, grid=True, color=False), '█' + app.GRID * 2)
        self.assertEqual(self.paint(cells, color=False), '█')


class LinearScale(unittest.TestCase):
    def test_ticks_are_round_and_the_top_is_rounded_up(self):
        scale = app.linear_scale([169, 20], 8)
        self.assertEqual(scale.ticks, {2: 50, 4: 100, 6: 150, 8: 200})
        self.assertEqual(scale.grid, {2, 4, 6, 8})
        self.assertEqual(scale.to_rows(100), 4)

    def test_small_counts_get_one_commit_per_row(self):
        self.assertEqual(app.linear_scale([6], 8).ticks, {2: 2, 4: 4, 6: 6, 8: 8})

    def test_rows_may_be_half_a_commit_when_that_fills_the_chart_better(self):
        self.assertEqual(app.linear_scale([3], 8).ticks, {2: 1, 4: 2, 6: 3, 8: 4})

    def test_fewer_ticks_rather_than_a_mostly_empty_chart(self):
        self.assertEqual(app.linear_scale([1], 8).ticks, {8: 1})
        self.assertEqual(app.linear_scale([2], 8).ticks, {4: 1, 8: 2})

    def test_short_charts_label_every_row_but_draw_gridlines_on_every_other(self):
        scale = app.linear_scale([40], 4)
        self.assertEqual(scale.ticks, {1: 10, 2: 20, 3: 30, 4: 40})
        self.assertEqual(scale.grid, {2, 4})

    def test_a_one_row_chart_has_no_gridline(self):
        self.assertEqual(app.linear_scale([6], 1).grid, set())
        self.assertEqual(app.log_scale([1, 10], 1).grid, set())

    def test_ticks_print_exactly_and_the_chart_stays_at_least_half_full(self):
        for top in (1, 2, 3, 7, 13, 101, 169, 999, 1001, 12_345, 30_366, 196_850, 2_000_001):
            for height in range(1, 13):
                with self.subTest(top=top, height=height):
                    scale = app.linear_scale([top], height)
                    self.assertTrue(scale.ticks)
                    for value in scale.ticks.values():
                        label = app.compact(value)
                        self.assertLessEqual(len(label), app.GUTTER)
                        self.assertEqual(parse_label(label), value)
                    self.assertLessEqual(scale.to_rows(top), height)
                    self.assertGreaterEqual(scale.to_rows(top), height / 2)

    def test_an_all_zero_window_has_no_ticks(self):
        scale = app.linear_scale([0, 0], 8)
        self.assertEqual(scale.ticks, {})
        self.assertEqual(scale.to_rows(0), 0)


class LogScale(unittest.TestCase):
    def test_one_1_2_5_step_per_row_with_gridlines_on_decades(self):
        scale = app.log_scale([1, 169], 8)
        self.assertEqual(scale.ticks, {1: 1, 2: 2, 3: 5, 4: 10, 5: 20, 6: 50, 7: 100, 8: 200})
        self.assertEqual(scale.grid, {1, 4, 7})
        self.assertEqual(scale.to_rows(10), 4)
        self.assertEqual(scale.to_rows(0), 0)

    def test_a_small_range_spreads_each_step_over_several_rows(self):
        self.assertEqual(app.log_scale([1, 6], 8).ticks, {2: 1, 4: 2, 6: 5, 8: 10})

    def test_short_charts_use_coarser_steps(self):
        self.assertEqual(app.log_scale([1, 169], 6).ticks, {1: 1, 2: 3, 3: 10, 4: 30, 5: 100, 6: 300})
        self.assertEqual(app.log_scale([1, 169], 4).ticks, {1: 1, 2: 10, 3: 100, 4: 1000})

    def test_the_ladder_starts_just_below_the_smallest_value(self):
        scale = app.log_scale([40_000, 196_850], 8)
        self.assertEqual(scale.ticks, {2: 20_000, 4: 50_000, 6: 100_000, 8: 200_000})

    def test_a_range_too_wide_for_the_chart_squeezes_the_smallest_values_into_the_bottom_row(self):
        scale = app.log_scale([1, 10**6], 3)
        self.assertEqual(scale.ticks, {1: 10_000, 2: 100_000, 3: 1_000_000})
        self.assertGreater(scale.to_rows(1), 0)


class ValueLabels(unittest.TestCase):
    def test_zero_has_no_label(self):
        self.assertEqual(app.value_label(0), '')
        self.assertEqual(app.value_label(0, signed=True), '')

    def test_counts_are_exact_below_ten_thousand(self):
        self.assertEqual(app.value_label(7), '7')
        self.assertEqual(app.value_label(9999), '9999')

    def test_changes_carry_their_sign(self):
        self.assertEqual(app.value_label(30, signed=True), '+30')
        self.assertEqual(app.value_label(-20, signed=True), '-20')

    def test_ten_thousand_and_up_are_abbreviated(self):
        self.assertEqual(app.value_label(12345, signed=True), '+12k')
        self.assertEqual(app.value_label(-1_500_000, signed=True), '-1.5M')


class Axis(unittest.TestCase):
    def test_labels_carry_the_year_first_and_when_it_changes(self):
        starts = [app.shift(date(2025, 11, 3), 'week', i) for i in range(16)]
        _, labels = app.x_axis(starts, 'week', col=3)
        words = labels.split()
        self.assertEqual(words[0], '2025-11-03')
        self.assertTrue(any(w.startswith('2026-') for w in words[1:]), words)
        self.assertTrue(all(len(w) == 5 for w in words[1:] if not w.startswith('20')), words)

    def test_ticks_mark_where_labels_start_and_labels_never_touch(self):
        starts = [app.shift(date(2026, 1, 1), 'day', i) for i in range(60)]
        ticks, labels = app.x_axis(starts, 'day', col=1)
        self.assertEqual(len(ticks), 60)
        label_starts = [m.start() for m in re.finditer(r'\S+', labels)]
        self.assertGreater(len(label_starts), 3)
        self.assertEqual([i for i, ch in enumerate(ticks) if ch == '┬'], label_starts)
        self.assertNotRegex(labels, r'\S \S')
        self.assertLessEqual(len(labels), 60)

    def test_month_labels_are_year_month(self):
        starts = [app.shift(date(2025, 1, 1), 'month', i) for i in range(12)]
        _, labels = app.x_axis(starts, 'month', col=3)
        self.assertTrue(labels.startswith('2025-01'))


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.today = date.today()

    def tearDown(self):
        self.tmp.cleanup()

    def recent_repo(self):
        repo = Repo(self.root / 'proj')
        repo.commit(self.today - timedelta(days=20), a__py=['a'] * 30)
        repo.commit(self.today - timedelta(days=10), a__py=['a'] * 40)
        repo.commit(self.today - timedelta(days=10), b__py=['b'] * 5)
        repo.commit(self.today, a__py=['a'] * 20)
        return repo

    def test_prints_the_commit_chart_above_the_loc_chart(self):
        repo = self.recent_repo()
        code, out, _ = run_main(str(repo.root), '--by', 'day', '--last', '21', '--height', '3')
        self.assertEqual(code, 0)
        commits, loc = chart_blocks(out)
        self.assertTrue(commits[0].startswith('Commits per day · 4 in 21 days · peak 2'), commits[0])
        self.assertTrue(loc[0].startswith('Lines of code · 0 → 25 (+25)'), loc[0])
        self.assertEqual(len(commits), 1 + 3 + 2)
        self.assertEqual(len(loc), 1 + 1 + 3 + 2)  # title, legend, rows, axis, dates

    def test_both_charts_share_the_same_columns(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root), '--by', 'day', '--last', '21', '--height', '3')
        commits, loc = chart_blocks(out)

        # Both bottom rows start drawing on the day of the first commit, 20 days ago.
        self.assertEqual(bar_cells(chart_body(commits)[-1])[0][0], bar_cells(chart_body(loc)[-1])[0][0])
        self.assertEqual(commits[-2:], loc[-2:])

    def test_default_window_spans_the_history_when_it_fits(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root), '--by', 'day')
        self.assertIn('in 21 days', out)

    def test_window_is_clamped_to_the_terminal_width(self):
        repo = self.recent_repo()
        code, out, err = run_main(str(repo.root), '--by', 'day', '--last', '300', columns=60)
        self.assertEqual(code, 0)
        bars = chart_blocks(out)[0][1]
        self.assertLessEqual(len(bars), 60)
        self.assertIn('terminal', err)

    def test_the_default_bucket_is_a_day(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root))
        self.assertTrue(out.startswith('proj · by day'), out)
        self.assertIn('Commits per day · 4 in 21 days', out)

    def test_H_is_short_for_height(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root), '-H', '3')
        commits, loc = chart_blocks(out)
        self.assertEqual(len(commits), 1 + 3 + 2)

    def test_values_put_the_count_under_each_bar_and_the_change_under_each_loc_bar(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root), '--last', '21', '-H', '3', '--values')
        commits, loc = chart_blocks(out)
        self.assertEqual(len(commits), 1 + 3 + 1 + 2)
        self.assertEqual(len(loc), 1 + 1 + 3 + 1 + 2)

        def tokens(row):
            self.assertTrue(row.startswith(' ' * app.GUTTER + ' │'), row)
            return [(m.start(), m.group()) for m in re.finditer(r'\S+', row[app.GUTTER + 2 :])]

        count_row, change_row, bottom_bars = tokens(commits[4]), tokens(loc[5]), bar_cells(commits[3])
        self.assertEqual([text for _, text in count_row], ['1', '2', '1'])
        self.assertEqual([text for _, text in change_row], ['+30', '+15', '-20'])
        # Each number starts where its bar starts, in both charts.
        self.assertEqual([pos for pos, _ in count_row], [pos for pos, _ in bottom_bars])
        self.assertEqual([pos for pos, _ in change_row], [pos for pos, _ in bottom_bars])

    def test_values_widen_the_columns_and_shrink_the_window_to_fit(self):
        repo = self.recent_repo()
        code, out, err = run_main(str(repo.root), '--last', '21', '--values', columns=40)
        self.assertEqual(code, 0)
        self.assertIn('Commits per day · 1 in 8 days', out)
        self.assertIn('terminal', err)
        chart_rows = [line for line in out.splitlines() if any(ch in line for ch in '│┤└')]
        self.assertTrue(all(len(line) <= 40 for line in chart_rows), chart_rows)

    def y_labels(self, block):
        return [line[: app.GUTTER].strip() for line in chart_body(block)]

    def test_the_y_axis_has_round_ticks_with_gridlines(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root), '--last', '21')
        commits, loc = chart_blocks(out)
        self.assertEqual(self.y_labels(commits), ['2', '', '', '', '1', '', '', ''])
        self.assertEqual(self.y_labels(loc), ['60', '', '45', '', '30', '', '15', ''])
        for block in (commits, loc):
            labelled = [bool(label) for label in self.y_labels(block)]
            self.assertEqual([app.GRID in line for line in chart_body(block)], labelled)

    def test_log_puts_the_y_axis_on_a_1_2_5_ladder(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root), '--last', '21', '--log')
        self.assertIn('log scale', out.splitlines()[0])
        _, loc = chart_blocks(out)
        self.assertEqual(self.y_labels(loc), ['50', '', '', '', '20', '', '', ''])

    def kinds_repo(self):
        """30 lines of src and 5 of docs three days ago, 10 lines of tests today."""
        repo = Repo(self.root / 'proj')
        repo.commit(self.today - timedelta(days=3), app__py=['a'] * 30, README__md=['r'] * 5)
        repo.commit(self.today, test_app__py=['t'] * 10)
        return repo

    def test_the_loc_chart_stacks_src_tests_and_docs_under_a_legend(self):
        repo = self.kinds_repo()
        _, out, _ = run_main(str(repo.root), '--last', '4')
        _, loc = chart_blocks(out)
        self.assertTrue(loc[0].startswith('Lines of code · 0 → 45 (+45)'), loc[0])
        self.assertEqual(
            loc[1].split(), ['█', 'src', '30', '(+30)', '▓', 'tests', '10', '(+10)', '░', 'docs', '5', '(+5)']
        )
        # Without color the layers are told apart by shading.
        body = ''.join(chart_body(loc))
        self.assertIn('▓', body)
        self.assertIn('░', body)

    def test_kinds_pick_which_lines_to_chart(self):
        repo = self.kinds_repo()
        _, out, _ = run_main(str(repo.root), '--last', '4', '-k', 'docs,tests')
        _, loc = chart_blocks(out)
        self.assertTrue(loc[0].startswith('Lines of code · 0 → 15 (+15)'), loc[0])
        self.assertEqual(loc[1].split(), ['█', 'tests', '10', '(+10)', '▓', 'docs', '5', '(+5)'])

    def test_an_unknown_kind_is_a_usage_error(self):
        repo = self.kinds_repo()
        with self.assertRaises(SystemExit) as raised:
            run_main(str(repo.root), '-k', 'src,code')
        self.assertEqual(raised.exception.code, 2)

    def test_rules_on_the_command_line_override_the_built_in_ones(self):
        repo = self.kinds_repo()
        _, out, _ = run_main(str(repo.root), '--last', '4', '--src', 'test_*', '--tests', '*.md')
        _, loc = chart_blocks(out)
        self.assertEqual(
            loc[1].split(), ['█', 'src', '40', '(+40)', '▓', 'tests', '5', '(+5)', '░', 'docs', '0', '(+0)']
        )

    def test_runs_from_a_subdirectory(self):
        repo = self.recent_repo()
        sub = repo.root / 'deep'
        sub.mkdir()
        code, out, _ = run_main(str(sub), '--by', 'week')
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('proj · by week'), out)

    def test_outside_a_repo_it_fails_with_gits_message(self):
        code, out, err = run_main(str(self.root))
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('not a git repository', err)

    def test_a_repo_without_commits_fails(self):
        Repo(self.root / 'empty')
        code, _, err = run_main(str(self.root / 'empty'))
        self.assertEqual(code, 1)
        self.assertIn('no commits', err)

    def test_runs_through_its_shebang(self):
        repo = self.recent_repo()
        script = Path(__file__).with_name('repocharts.py')
        result = subprocess.run(
            [str(script), str(repo.root), '--by', 'month', '--no-color'], capture_output=True, text=True, check=True
        )
        self.assertIn('Commits per month', result.stdout)
        self.assertNotIn('\033[', result.stdout)


if __name__ == '__main__':
    unittest.main()

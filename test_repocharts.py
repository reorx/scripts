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
    return [(m.start(), m.group()) for m in re.finditer(f'[{app.BLOCKS[1:]}]+', row[app.GUTTER + 2:])]


def bars(values, height, col):
    return app.bar_rows(values, app.linear_scale(values, height), col)


def chart_blocks(output):
    """Split the output into charts: each is the list of lines from its title to its label line."""
    blocks = output.strip('\n').split('\n\n')
    return [block.split('\n') for block in blocks[1:]]


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
        changes = sorted(app.read_loc_changes(self.repo.root, app.LOCKFILES))
        self.assertEqual(changes, [(d1, 10), (d2, -3), (d4, 1), (d5, 4)])

    def test_loc_changes_sum_to_the_text_lines_at_head(self):
        changes = app.read_loc_changes(self.repo.root, app.LOCKFILES)
        self.assertEqual(sum(delta for _, delta in changes), 7 + 4 + 1)

    def test_lockfiles_count_when_not_excluded(self):
        changes = app.read_loc_changes(self.repo.root, [])
        self.assertEqual(sum(delta for _, delta in changes), 12 + 100)

    def test_exclude_patterns_match_paths_and_basenames(self):
        changes = app.read_loc_changes(self.repo.root, [*app.LOCKFILES, 'b.py', 'c*'])
        self.assertEqual(sum(delta for _, delta in changes), 7)


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

    def test_loc_is_the_running_total_at_the_end_of_each_bucket(self):
        changes = [(date(2025, 12, 30), 50), (date(2026, 1, 5), 10), (date(2026, 1, 20), -3)]
        series = app.build_series([], changes, 'week', end=date(2026, 1, 26), n=4)
        self.assertEqual(series.loc_before, 50)
        self.assertEqual(series.loc, [60, 60, 57, 57])
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
        self.assertEqual(app.bar_rows(values, app.log_scale(values, 3), col=1), ['  █', ' ██', '███'])


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
        self.assertEqual(len(loc), 1 + 3 + 2)

    def test_both_charts_share_the_same_columns(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root), '--by', 'day', '--last', '21', '--height', '3')
        commits, loc = chart_blocks(out)

        # Both bottom rows start drawing on the day of the first commit, 20 days ago.
        self.assertEqual(bar_cells(commits[3])[0][0], bar_cells(loc[3])[0][0])
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
        self.assertEqual(len(loc), 1 + 3 + 1 + 2)

        def tokens(row):
            self.assertTrue(row.startswith(' ' * app.GUTTER + ' │'), row)
            return [(m.start(), m.group()) for m in re.finditer(r'\S+', row[app.GUTTER + 2:])]

        count_row, change_row, bottom_bars = tokens(commits[4]), tokens(loc[4]), bar_cells(commits[3])
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

    def y_labels(self, block, height=8):
        return [line[: app.GUTTER].strip() for line in block[1 : 1 + height]]

    def test_the_y_axis_has_round_ticks_with_gridlines(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root), '--last', '21')
        commits, loc = chart_blocks(out)
        self.assertEqual(self.y_labels(commits), ['2', '', '', '', '1', '', '', ''])
        self.assertEqual(self.y_labels(loc), ['60', '', '45', '', '30', '', '15', ''])
        for block in (commits, loc):
            labelled = [bool(label) for label in self.y_labels(block)]
            self.assertEqual([app.GRID in line for line in block[1:9]], labelled)

    def test_log_puts_the_y_axis_on_a_1_2_5_ladder(self):
        repo = self.recent_repo()
        _, out, _ = run_main(str(repo.root), '--last', '21', '--log')
        self.assertIn('log scale', out.splitlines()[0])
        _, loc = chart_blocks(out)
        self.assertEqual(self.y_labels(loc), ['50', '', '', '', '20', '', '', ''])

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

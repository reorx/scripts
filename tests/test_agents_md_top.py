#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["tiktoken>=0.8"]
# ///
"""Behavior tests: uv run tests/test_agents_md_top.py."""

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / 'agents-md-top.py'
SPEC = importlib.util.spec_from_file_location('agents_md_top', SCRIPT)
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)

ANSI = re.compile(r'\x1b\[[0-9;]*m')
YELLOW = '\x1b[33m'
# Trees are scanned without the user's git config and ripgrep config.
CLEAN_ENV = {
    **{k: v for k, v in os.environ.items() if k not in ('RIPGREP_CONFIG_PATH', app.THRESHOLD_ENV, 'NO_COLOR')},
    'GIT_CONFIG_GLOBAL': '/dev/null',
    'GIT_CONFIG_NOSYSTEM': '1',
}


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def git_init(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-q', str(path)], check=True, env=CLEAN_ENV)


def entry(root: Path, rel: str, tokens: int, size: int = 100, project: str = 'p') -> 'app.Entry':
    return app.Entry(path=root / rel, tokens=tokens, size=size, mtime=datetime(2026, 11, 15, 9, 30), project=project)


class TreeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / 'Code'
        self.root.mkdir()
        self._env = dict(os.environ)
        os.environ.clear()
        os.environ.update(CLEAN_ENV)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def found(self) -> list[str]:
        return sorted(str(p.relative_to(self.root)) for p in app.find_agents_files(self.root))


class FindFilesBehavior(TreeTestCase):
    def test_given_projects_when_scanned_then_list_every_agents_md_at_any_depth(self):
        write(self.root / 'alpha/AGENTS.md', 'a')
        write(self.root / 'beta/packages/core/AGENTS.md', 'b')
        write(self.root / 'beta/README.md', 'not this')
        write(self.root / 'beta/agents.md', 'lowercase is a different file')
        self.assertEqual(self.found(), ['alpha/AGENTS.md', 'beta/packages/core/AGENTS.md'])

    def test_given_gitignored_dir_inside_repo_when_scanned_then_skip_it_like_rg(self):
        git_init(self.root / 'alpha')
        write(self.root / 'alpha/.gitignore', 'node_modules/\nvendor\n')
        write(self.root / 'alpha/AGENTS.md', 'a')
        write(self.root / 'alpha/node_modules/pkg/AGENTS.md', 'dep')
        write(self.root / 'alpha/vendor/lib/AGENTS.md', 'vendored')
        self.assertEqual(self.found(), ['alpha/AGENTS.md'])

    def test_given_gitignored_agents_md_file_when_scanned_then_skip_it_although_rg_globs_would_not(self):
        git_init(self.root / 'alpha')
        write(self.root / 'alpha/.gitignore', 'scratch/AGENTS.md\n')
        write(self.root / 'alpha/AGENTS.md', 'a')
        write(self.root / 'alpha/scratch/AGENTS.md', 'local only')
        self.assertEqual(self.found(), ['alpha/AGENTS.md'])

    def test_given_hidden_dirs_and_ignore_files_when_scanned_then_skip_them_like_rg(self):
        write(self.root / 'alpha/AGENTS.md', 'a')
        write(self.root / 'alpha/.claude/worktrees/x/AGENTS.md', 'worktree copy')
        write(self.root / 'beta/.ignore', 'generated/\n')
        write(self.root / 'beta/generated/AGENTS.md', 'generated')
        write(self.root / 'beta/AGENTS.md', 'b')
        self.assertEqual(self.found(), ['alpha/AGENTS.md', 'beta/AGENTS.md'])

    def test_given_agents_md_symlinked_to_claude_md_when_scanned_then_include_it(self):
        write(self.root / 'alpha/CLAUDE.md', 'shared instructions')
        (self.root / 'alpha/AGENTS.md').symlink_to('CLAUDE.md')
        self.assertEqual(self.found(), ['alpha/AGENTS.md'])

    def test_given_project_dir_symlinked_from_elsewhere_when_scanned_then_follow_it(self):
        outside = Path(self._tmp.name) / 'Documents/monitoring'
        write(outside / 'AGENTS.md', 'm')
        (self.root / 'monitoring').symlink_to(outside)
        self.assertEqual(self.found(), ['monitoring/AGENTS.md'])

    def test_given_two_paths_to_one_file_when_scanned_then_keep_the_direct_path_once(self):
        write(self.root / 'zeta/AGENTS.md', 'z')
        (self.root / 'alias').symlink_to(self.root / 'zeta')
        self.assertEqual(self.found(), ['zeta/AGENTS.md'])

    def test_given_no_agents_md_when_scanned_then_return_empty(self):
        write(self.root / 'alpha/README.md', 'r')
        self.assertEqual(self.found(), [])


class CollectBehavior(TreeTestCase):
    def test_given_files_when_collected_then_project_is_first_dir_under_root(self):
        write(self.root / 'alpha/AGENTS.md', 'a')
        write(self.root / 'beta/packages/core/AGENTS.md', 'b')
        write(self.root / 'AGENTS.md', 'root level')
        projects = {str(e.path.relative_to(self.root)): e.project for e in app.collect(self.root)}
        self.assertEqual(
            projects, {'alpha/AGENTS.md': 'alpha', 'beta/packages/core/AGENTS.md': 'beta', 'AGENTS.md': '-'}
        )

    def test_given_files_when_collected_then_sorted_by_tokens_largest_first(self):
        write(self.root / 'small/AGENTS.md', 'hello world')
        write(self.root / 'big/AGENTS.md', 'hello world ' * 200)
        write(self.root / 'mid/AGENTS.md', 'hello world ' * 20)
        self.assertEqual([e.project for e in app.collect(self.root)], ['big', 'mid', 'small'])

    def test_given_symlinked_file_when_collected_then_measure_the_target(self):
        target = write(self.root / 'alpha/CLAUDE.md', 'hello world')
        (self.root / 'alpha/AGENTS.md').symlink_to('CLAUDE.md')
        [e] = app.collect(self.root)
        self.assertEqual((e.tokens, e.size), (2, target.stat().st_size))
        self.assertEqual(e.mtime, datetime.fromtimestamp(target.stat().st_mtime))


class TokenBehavior(unittest.TestCase):
    def test_given_english_text_when_counted_then_use_o200k_base(self):
        self.assertEqual(app.count_tokens('hello world'), 2)

    def test_given_special_token_text_when_counted_then_treat_it_as_plain_text(self):
        self.assertGreater(app.count_tokens('Never emit <|endoftext|> in output.'), 3)

    def test_given_empty_file_when_counted_then_zero(self):
        self.assertEqual(app.count_tokens(''), 0)


class ThresholdBehavior(unittest.TestCase):
    def test_given_env_unset_when_read_then_use_builtin_default(self):
        self.assertEqual(app.read_threshold({}), app.DEFAULT_MAX_TOKENS)

    def test_given_env_number_when_read_then_use_it(self):
        self.assertEqual(app.read_threshold({app.THRESHOLD_ENV: '1500'}), 1500)
        self.assertEqual(app.read_threshold({app.THRESHOLD_ENV: '12_000'}), 12000)

    def test_given_env_not_a_positive_integer_when_read_then_fail_naming_the_variable(self):
        for bad in ('big', '-5', '0', '2.5'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, app.THRESHOLD_ENV):
                app.read_threshold({app.THRESHOLD_ENV: bad})


class RenderBehavior(unittest.TestCase):
    root = Path('/x/Code')

    def render(self, entries, threshold=1000, limit=20, color=False):
        return app.render(entries, root=self.root, threshold=threshold, limit=limit, color=color, home=Path('/x'))

    def test_given_entries_when_rendered_then_columns_are_path_tokens_size_mtime_project(self):
        out = self.render([entry(self.root, 'alpha/AGENTS.md', 12345, size=52000, project='alpha')])
        header, row = out.splitlines()[:2]
        self.assertEqual(header.split(), ['PATH', 'TOKENS', 'SIZE', 'MTIME', 'PROJECT'])
        self.assertEqual(row.split(), ['~/Code/alpha/AGENTS.md', '12,345', '50.8K', '2026-11-15', '09:30', 'alpha'])

    def test_given_more_entries_than_limit_when_rendered_then_show_only_the_first_n(self):
        entries = [entry(self.root, f'p{i}/AGENTS.md', 100 - i, project=f'p{i}') for i in range(30)]
        rows = [line for line in self.render(entries, limit=20).splitlines() if line.startswith('~/')]
        self.assertEqual(len(rows), 20)
        self.assertIn('p19', rows[-1])

    def test_given_rows_over_threshold_when_colored_then_only_those_rows_are_yellow(self):
        entries = [
            entry(self.root, 'big/AGENTS.md', 1001, project='big'),
            entry(self.root, 'edge/AGENTS.md', 1000, project='edge'),
        ]
        lines = self.render(entries, threshold=1000, color=True).splitlines()
        big = next(line for line in lines if 'big/AGENTS.md' in line)
        edge = next(line for line in lines if 'edge/AGENTS.md' in line)
        self.assertTrue(big.startswith(YELLOW))
        self.assertNotIn(YELLOW, edge)

    def test_given_color_off_when_rendered_then_no_escape_codes(self):
        out = self.render([entry(self.root, 'big/AGENTS.md', 5000)], color=False)
        self.assertIsNone(ANSI.search(out))

    def test_given_colored_output_when_rendered_then_columns_still_align(self):
        entries = [
            entry(self.root, 'a/AGENTS.md', 5000, project='a'),
            entry(self.root, 'longer-name/AGENTS.md', 10, project='longer-name'),
        ]
        plain = self.render(entries, color=False)
        colored = ANSI.sub('', self.render(entries, color=True))
        self.assertEqual(plain, colored)

    def test_given_entries_when_rendered_then_footer_counts_all_files_and_those_over_threshold(self):
        entries = [entry(self.root, f'p{i}/AGENTS.md', 2000 if i < 3 else 10) for i in range(25)]
        footer = self.render(entries, threshold=1000, limit=20).splitlines()[-1]
        self.assertIn('25 AGENTS.md', footer)
        self.assertIn('3 over 1,000 tokens', footer)
        self.assertIn(app.THRESHOLD_ENV, footer)
        self.assertIn('o200k_base', footer)

    def test_given_no_entries_when_rendered_then_say_so(self):
        self.assertIn('No AGENTS.md', self.render([]))


class FormatBehavior(unittest.TestCase):
    def test_sizes_read_like_ls_h(self):
        self.assertEqual(
            [app.human_size(n) for n in (0, 512, 1024, 52000, 3 * 1024 * 1024)], ['0B', '512B', '1.0K', '50.8K', '3.0M']
        )

    def test_paths_under_home_start_with_tilde(self):
        self.assertEqual(app.display_path(Path('/x/Code/a/AGENTS.md'), Path('/x')), '~/Code/a/AGENTS.md')
        self.assertEqual(app.display_path(Path('/y/a/AGENTS.md'), Path('/x')), '/y/a/AGENTS.md')


class CliBehavior(TreeTestCase):
    def run_cli(self, *args, **env):
        return subprocess.run(
            ['uv', 'run', '-q', str(SCRIPT), *args], capture_output=True, text=True, env={**os.environ, **env}
        )

    def test_given_env_threshold_when_run_then_footer_reports_it_and_pipe_gets_no_color(self):
        write(self.root / 'big/AGENTS.md', 'hello world ' * 100)
        write(self.root / 'small/AGENTS.md', 'hello world')
        result = self.run_cli(str(self.root), **{app.THRESHOLD_ENV: '50'})
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [
            line.split()[-1]
            for line in result.stdout.splitlines()
            if 'AGENTS.md' in line and line.startswith(str(self.root)[:2])
        ]
        self.assertEqual(rows, ['big', 'small'])
        self.assertIn('1 over 50 tokens', result.stdout)
        self.assertIsNone(ANSI.search(result.stdout))

    def test_given_limit_flag_when_run_then_show_that_many_rows(self):
        for name in 'abc':
            write(self.root / f'{name}/AGENTS.md', 'x')
        result = self.run_cli(str(self.root), '-n', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum('AGENTS.md' in line for line in result.stdout.splitlines()[1:-1]), 2)

    def test_given_bad_env_threshold_when_run_then_exit_1_with_message(self):
        result = self.run_cli(str(self.root), **{app.THRESHOLD_ENV: 'lots'})
        self.assertEqual(result.returncode, 1)
        self.assertIn(app.THRESHOLD_ENV, result.stderr)

    def test_given_missing_root_when_run_then_exit_1_with_message(self):
        result = self.run_cli(str(self.root / 'nope'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('not a directory', result.stderr)


if __name__ == '__main__':
    unittest.main()

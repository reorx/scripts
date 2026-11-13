#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Behaviour tests for dev-space: rule matching, safety guards, delete / archive / restore,
sqlite backups, tiers, config validation, clone-aware sizing, and the watch side.

Everything runs in temp dirs with real git repos; lsof snapshots, free space and `codex` are
injected or faked, so nothing outside the temp dirs is touched.
"""

import gzip
import importlib.machinery
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('dev-space')
LOADER = importlib.machinery.SourceFileLoader('dev_space', str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
ds = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(ds)

DAY = 86400
NOW = time.time()
GIB = 1024**3


def write(path: Path, data: bytes | str = b'x', age_days: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    age(path, age_days)
    return path


def age(path: Path, days: float) -> None:
    """Set mtime (and atime) of path, and of everything under it, to `days` ago."""
    t = NOW - days * DAY
    targets = [path]
    if path.is_dir() and not path.is_symlink():
        targets += [Path(dp, n) for dp, ds_, fs in os.walk(path) for n in ds_ + fs]
    for p in sorted(targets, key=lambda p: -len(p.parts)):
        os.utime(p, (t, t), follow_symlinks=False)


def git(cwd: Path, *args: str, days_ago: float = 0) -> None:
    stamp = f'@{int(NOW - days_ago * DAY)} +0000'
    env = {**os.environ, 'GIT_AUTHOR_DATE': stamp, 'GIT_COMMITTER_DATE': stamp}
    subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, env=env)


def make_repo(
    path: Path, ignore: str = 'tmp/\nnode_modules/\n.venv/\n.build/\n*.sqlite*\n', commit_days_ago: float = 0
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, 'init', '-q')
    git(path, 'config', 'user.email', 't@example.com')
    git(path, 'config', 'user.name', 't')
    write(path / '.gitignore', ignore)
    write(path / 'README.md', 'hi')
    git(path, 'add', '-A')
    git(path, 'commit', '-qm', 'init', days_ago=commit_days_ago)
    age(path / '.gitignore', commit_days_ago)
    age(path / 'README.md', commit_days_ago)
    return path


class Sandbox(unittest.TestCase):
    """A temp home with a code root, a fake archive volume and a state dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(os.path.realpath(self._tmp.name))
        self.code = self.home / 'Code'
        self.code.mkdir()
        self.archive = self.home / 'LaCie' / 'DevArchive'
        self.archive.mkdir(parents=True)
        self.state = self.home / 'state'

    def tearDown(self):
        for dp, dirs, _files in os.walk(self.home):
            for d in dirs:
                os.chmod(os.path.join(dp, d), 0o755)
        self._tmp.cleanup()

    def config(self, body: str, settings: str = '', watch: str = '') -> 'ds.Config':
        text = f"""
[settings]
code_root = "{self.code}"
archive_root = "{self.archive}"
state_dir = "{self.state}"
pressure_free = "15GiB"
{settings}
{watch}
{body}
"""
        path = self.home / 'dev-space.toml'
        path.write_text(text)
        return ds.load_config(path, home=self.home)

    def run_clean(self, cfg, tier='daily', dry_run=False, open_paths=(), **kw):
        out = io.StringIO()
        runner = ds.Runner(
            cfg, tier=tier, dry_run=dry_run, now=NOW, open_paths=dict.fromkeys(open_paths, 'proc'), out=out
        )
        result = runner.clean(**kw)
        return result, out.getvalue()

    def done_paths(self, result):
        return sorted(str(o.path) for o in result.done)

    def skipped(self, result):
        return {str(s.path): s.reason for s in result.skipped}


class TestGlob(Sandbox):
    def test_double_star_matches_nested_and_skips_dot_git(self):
        base = self.home / 'p'
        write(base / 'tmp/a.sqlite')
        write(base / 'tmp/x/y/b.sqlite')
        write(base / '.git/tmp/c.sqlite')
        write(base / 'src/d.sqlite')
        got = sorted(str(p.relative_to(base)) for p in ds.match_units(base, ['tmp/**/*.sqlite']))
        self.assertEqual(got, ['tmp/a.sqlite', 'tmp/x/y/b.sqlite'])

    def test_single_star_is_one_level(self):
        base = self.home / 'p'
        (base / 'tmp/t1/DerivedData').mkdir(parents=True)
        (base / 'tmp/t1/deep/DerivedData').mkdir(parents=True)
        got = [str(p.relative_to(base)) for p in ds.match_units(base, ['tmp/*/DerivedData'])]
        self.assertEqual(got, ['tmp/t1/DerivedData'])

    def test_outermost_match_wins(self):
        base = self.home / 'p'
        write(base / 'tmp/node_modules/a/node_modules/b/index.js')
        got = [str(p.relative_to(base)) for p in ds.match_units(base, ['tmp/**/node_modules'])]
        self.assertEqual(got, ['tmp/node_modules'])

    def test_heavy_generated_dirs_are_matched_but_never_searched(self):
        base = self.home / 'p'
        write(base / 'web/.next/cache/x')
        write(base / 'node_modules/pkg/.next/cache/x')
        write(base / '.build/DerivedData/a/.build/index-build/x')
        (base / 'node_modules/.bin').mkdir(parents=True)
        got = sorted(
            str(p.relative_to(base)) for p in ds.match_units(base, ['**/.next/cache', '**/.build/index-build'])
        )
        self.assertEqual(got, ['web/.next/cache'])
        self.assertEqual([p.name for p in ds.match_units(base, ['node_modules'])], ['node_modules'])

    def test_read_only_dirs_are_matched_but_never_searched(self):
        # a Go module cache in a test HOME: read-only trees whose testdata holds *.db files
        base = self.home / 'p'
        mod = base / 'tmp/cleanhome/go/pkg/mod/modernc.org/sqlite@v1.61.1'
        write(mod / 'testdata/fuzz.db')
        write(base / 'tmp/run/data/app.db')
        for d in (mod / 'testdata', mod):
            d.chmod(0o555)
        got = sorted(str(p.relative_to(base)) for p in ds.match_units(base, ['tmp/*/**/*.db']))
        self.assertEqual(got, ['tmp/run/data/app.db'])
        self.assertEqual([p.name for p in ds.match_units(base, ['tmp/*/go/pkg/mod/*/*'])], ['sqlite@v1.61.1'])

    def test_absolute_pattern_splits_literal_base(self):
        write(self.home / 'live/backups/20261101T000000Z-abc/vibench.sqlite')
        write(self.home / 'live/backups/identity-x/key')
        base, rel = ds.split_pattern(str(self.home / 'live/backups/20*'))
        self.assertEqual((base, rel), (self.home / 'live/backups', '20*'))
        self.assertEqual([p.name for p in ds.match_units(base, [rel])], ['20261101T000000Z-abc'])


class TestSelection(Sandbox):
    def project(self, rules: str, name='p', commit_days_ago=60, extra=''):
        root = make_repo(self.code / name, commit_days_ago=commit_days_ago)
        cfg = self.config(f'[projects.{name}]\nroot = "{root}"\n{extra}\n{rules}')
        return root, cfg

    def test_age_uses_newest_mtime_inside(self):
        root, cfg = self.project("""
[[projects.p.rules]]
id = "dd"
why = "t"
action = "delete"
when = "daily"
paths = ["tmp/*/DerivedData"]
age_days = 7
""")
        write(root / 'tmp/old/DerivedData/a.o', age_days=10)
        write(root / 'tmp/mixed/DerivedData/a.o', age_days=10)
        write(root / 'tmp/mixed/DerivedData/sub/b.o', age_days=1)
        result, _ = self.run_clean(cfg)
        self.assertEqual(self.done_paths(result), [str(root / 'tmp/old/DerivedData')])
        self.assertFalse((root / 'tmp/old/DerivedData').exists())
        self.assertTrue((root / 'tmp/mixed/DerivedData').exists())

    def test_keep_newest_protects_n_newest(self):
        root, cfg = self.project("""
[[projects.p.rules]]
id = "bak"
why = "t"
action = "delete"
when = "daily"
paths = ["data/dev.sqlite.bak-*"]
age_days = 7
keep_newest = 2
""")
        for i, d in enumerate([30, 20, 10, 9]):
            write(root / f'data/dev.sqlite.bak-{i}', age_days=d)
        result, _ = self.run_clean(cfg)
        self.assertEqual([Path(p).name for p in self.done_paths(result)], ['dev.sqlite.bak-0', 'dev.sqlite.bak-1'])

    def test_idle_days_needs_old_commit_and_no_recent_changes(self):
        rules = """
[[projects.{n}.rules]]
id = "nm"
why = "t"
action = "delete"
when = "daily"
paths = ["node_modules"]
idle_days = 14
"""
        idle = make_repo(self.code / 'idle', commit_days_ago=30)
        busy = make_repo(self.code / 'busy', commit_days_ago=1)
        dirty = make_repo(self.code / 'dirty', commit_days_ago=30)
        write(dirty / 'README.md', 'edited', age_days=2)
        for r in (idle, busy, dirty):
            write(r / 'node_modules/x/index.js', age_days=40)
        body = ''.join(
            f'[projects.{n}]\nroot = "{self.code / n}"\n' + rules.format(n=n) for n in ('idle', 'busy', 'dirty')
        )
        cfg = self.config(body)
        result, _ = self.run_clean(cfg)
        self.assertEqual(self.done_paths(result), [str(idle / 'node_modules')])

    def test_guards(self):
        root, cfg = self.project(
            """
[[projects.p.rules]]
id = "all"
why = "t"
action = "delete"
when = "daily"
paths = ["tmp/*", "src/*", "notes/*"]
exclude = ["tmp/keep-me", "tmp/*/secret.env"]
""",
            extra='protect = ["tmp/protected-*"]',
        )
        write(root / 'tmp/ok/a', age_days=10)
        write(root / 'tmp/keep-me/a', age_days=10)
        write(root / 'tmp/has-secret/secret.env', age_days=10)
        write(root / 'tmp/protected-db/a', age_days=10)
        write(root / 'tmp/busy/a', age_days=10)
        os.symlink(self.home, root / 'tmp/link')
        write(root / 'src/tracked.txt', age_days=10)
        git(root, 'add', 'src/tracked.txt')
        git(root, 'commit', '-qm', 'track', days_ago=60)
        write(root / 'notes/draft.md', age_days=10)  # untracked, not ignored: work in progress
        result, _ = self.run_clean(cfg, open_paths=[str(root / 'tmp/busy/a')])
        self.assertEqual(self.done_paths(result), [str(root / 'tmp/ok')])
        reasons = self.skipped(result)
        self.assertIn('exclude', reasons[str(root / 'tmp/keep-me')])
        self.assertIn('exclude', reasons[str(root / 'tmp/has-secret')])
        self.assertIn('protect', reasons[str(root / 'tmp/protected-db')])
        self.assertIn('in use', reasons[str(root / 'tmp/busy')])
        self.assertIn('symlink', reasons[str(root / 'tmp/link')])
        self.assertIn('tracked', reasons[str(root / 'src/tracked.txt')])
        self.assertIn('not ignored', reasons[str(root / 'notes/draft.md')])
        self.assertTrue(self.home.exists())

    def test_symlink_escaping_project_is_never_followed(self):
        outside = write(self.home / 'outside/tmp/x/DerivedData/a.o', age_days=30).parent
        root, cfg = self.project("""
[[projects.p.rules]]
id = "dd"
why = "t"
action = "delete"
when = "daily"
paths = ["tmp/**/DerivedData"]
""")
        (root / 'tmp').mkdir()
        os.symlink(self.home / 'outside/tmp/x', root / 'tmp/x')
        result, _ = self.run_clean(cfg)
        self.assertEqual(result.done, [])
        self.assertTrue(outside.exists())

    def test_companions_follow_their_unit(self):
        root, cfg = self.project("""
[[projects.p.rules]]
id = "dist"
why = "t"
action = "delete"
when = "daily"
paths = ["tmp/dist/*.tar.gz"]
keep_newest = 1
companions = [".sha256"]
""")
        write(root / 'tmp/dist/a.tar.gz', age_days=20)
        write(root / 'tmp/dist/a.tar.gz.sha256', age_days=20)
        write(root / 'tmp/dist/b.tar.gz', age_days=1)
        write(root / 'tmp/dist/b.tar.gz.sha256', age_days=1)
        self.run_clean(cfg)
        self.assertEqual(sorted(p.name for p in (root / 'tmp/dist').iterdir()), ['b.tar.gz', 'b.tar.gz.sha256'])

    def test_dry_run_changes_nothing_and_audit_log_matches(self):
        root, cfg = self.project("""
[[projects.p.rules]]
id = "tmpx"
why = "t"
action = "delete"
when = "daily"
paths = ["tmp/*"]
age_days = 7
""")
        write(root / 'tmp/a/f', b'x' * 10000, age_days=10)
        result, out = self.run_clean(cfg, dry_run=True)
        self.assertEqual(len(result.done), 1)
        self.assertTrue((root / 'tmp/a/f').exists())
        self.assertFalse((self.state / 'actions.jsonl').exists())
        self.assertIn('tmpx', out)
        result, _ = self.run_clean(cfg)
        self.assertFalse((root / 'tmp/a').exists())
        log = [json.loads(line) for line in (self.state / 'actions.jsonl').read_text().splitlines()]
        self.assertEqual([(e['rule'], e['action'], e['path']) for e in log], [('tmpx', 'delete', str(root / 'tmp/a'))])
        self.assertGreater(log[0]['du_bytes'], 0)

    def test_tiers(self):
        root, cfg = self.project("""
[[projects.p.rules]]
id = "daily"
why = "t"
action = "delete"
when = "daily"
paths = ["tmp/d*"]
age_days = 7
pressure_age_days = 2
[[projects.p.rules]]
id = "pressure"
why = "t"
action = "delete"
when = "pressure"
paths = ["tmp/p*"]
[[projects.p.rules]]
id = "manual"
why = "t"
action = "delete"
when = "manual"
paths = ["tmp/m*"]
""")
        for name in ('d-old', 'd-mid', 'p', 'm'):
            write(root / f'tmp/{name}/f', age_days=10 if name == 'd-old' else 3)
        result, _ = self.run_clean(cfg, tier='daily', dry_run=True)
        self.assertEqual([Path(p).name for p in self.done_paths(result)], ['d-old'])
        result, _ = self.run_clean(cfg, tier='pressure', dry_run=True)
        self.assertEqual([Path(p).name for p in self.done_paths(result)], ['d-mid', 'd-old', 'p'])
        result, _ = self.run_clean(cfg, tier='manual', dry_run=True)
        self.assertEqual([Path(p).name for p in self.done_paths(result)], ['d-old', 'm', 'p'])
        self.assertEqual(ds.scheduled_tier(free=10 * GIB, pressure_free=15 * GIB), 'pressure')
        self.assertEqual(ds.scheduled_tier(free=20 * GIB, pressure_free=15 * GIB), 'daily')


class TestDefaults(Sandbox):
    RULES = """
[[defaults.rules]]
id = "tmp-build"
why = "t"
action = "delete"
when = "daily"
paths = ["tmp/**/DerivedData"]
age_days = 7
"""

    def test_defaults_apply_to_git_projects_with_exclusions(self):
        anon = make_repo(self.code / 'anon')
        conf = make_repo(self.code / 'conf')
        skipper = make_repo(self.code / 'skipper')
        excluded = make_repo(self.code / 'excluded')
        plain = self.code / 'plain'  # not a git repo
        for d in (anon, conf, skipper, excluded, plain):
            write(d / 'tmp/t/DerivedData/a.o', age_days=10)
        cfg = self.config(
            self.RULES
            + f'[projects.conf]\nroot = "{conf}"\n'
            + f'[projects.skipper]\nroot = "{skipper}"\nskip_defaults = ["tmp-build"]\n',
            settings=f'defaults_exclude = ["{excluded}"]',
        )
        result, _ = self.run_clean(cfg)
        self.assertEqual(self.done_paths(result), [str(anon / 'tmp/t/DerivedData'), str(conf / 'tmp/t/DerivedData')])

    def test_rules_listing_shows_effective_rules(self):
        make_repo(self.code / 'anon')
        cfg = self.config(self.RULES)
        out = io.StringIO()
        ds.print_rules(cfg, 'anon', out=out)
        self.assertIn('tmp-build', out.getvalue())


class TestArchive(Sandbox):
    def setup_project(self, when='daily'):
        root = make_repo(self.code / 'p')
        cfg = self.config(f"""
[projects.p]
root = "{root}"
[[projects.p.rules]]
id = "evidence"
why = "t"
action = "archive"
when = "{when}"
paths = ["tmp/20??-??-??-*"]
age_days = 14
""")
        return root, cfg

    def test_archive_moves_verifies_links_and_restores(self):
        root, cfg = self.setup_project()
        unit = root / 'tmp/2026-10-01-task'
        write(unit / 'shot.png', b'png' * 1000, age_days=20)
        write(unit / 'sub/report.md', 'ok', age_days=20)
        result, _ = self.run_clean(cfg)
        dest = self.archive / 'p' / unit.relative_to(self.home)
        self.assertEqual(self.done_paths(result), [str(unit)])
        self.assertTrue(unit.is_symlink())
        self.assertEqual(Path(os.readlink(unit)), dest)
        self.assertEqual((dest / 'sub/report.md').read_text(), 'ok')
        self.assertAlmostEqual((dest / 'shot.png').stat().st_mtime, NOW - 20 * DAY, delta=2)
        manifest = (self.archive / 'MANIFEST.jsonl').read_text()
        self.assertIn(str(unit), manifest)
        # a second run leaves the symlink alone
        result, _ = self.run_clean(cfg)
        self.assertEqual(result.done, [])
        ds.restore(cfg, unit, dry_run=False, out=io.StringIO())
        self.assertFalse(unit.is_symlink())
        self.assertEqual((unit / 'sub/report.md').read_text(), 'ok')
        self.assertTrue(dest.exists())  # the LaCie copy stays

    def test_appledouble_files_from_exfat_are_not_copied_back(self):
        src = self.home / 'src'
        write(src / 'a.md', 'a')
        write(src / '._a.md', 'xattrs')  # exFAT stores a.md's xattrs here
        write(src / '._lonely', 'real file')  # no a sibling: a real file that happens to start with ._
        ds.copy_verified(src, self.home / 'dst')
        self.assertEqual(sorted(p.name for p in (self.home / 'dst').iterdir()), ['._lonely', 'a.md'])

    def test_rearchive_after_restore_gets_a_new_name(self):
        root, cfg = self.setup_project()
        unit = root / 'tmp/2026-10-01-task'
        write(unit / 'a.png', '1', age_days=20)
        self.run_clean(cfg)
        ds.restore(cfg, unit, dry_run=False, out=io.StringIO())
        write(unit / 'a.png', '2', age_days=20)
        result, _ = self.run_clean(cfg)
        self.assertEqual(len(result.done), 1)
        self.assertTrue(unit.is_symlink())
        self.assertEqual((unit / 'a.png').read_text(), '2')
        self.assertEqual(len(list((self.archive / 'p' / unit.parent.relative_to(self.home)).iterdir())), 2)

    def test_archive_refuses_content_exfat_cannot_hold(self):
        root, cfg = self.setup_project()
        write(root / 'tmp/2026-10-01-git/repo/.git/HEAD', 'ref', age_days=20)
        write(root / 'tmp/2026-10-02-link/a', age_days=20)
        os.symlink('a', root / 'tmp/2026-10-02-link/b')
        age(root / 'tmp/2026-10-02-link', 20)
        write(root / 'tmp/2026-10-03-app/Foo.app/Contents/MacOS/Foo', age_days=20)
        write(root / 'tmp/2026-10-04-env/.env', 'TOKEN=1', age_days=20)
        write(root / 'tmp/2026-10-05-colon/a:b', age_days=20)
        result, _ = self.run_clean(cfg)
        self.assertEqual(result.done, [])
        reasons = self.skipped(result)
        self.assertEqual(len(reasons), 5)
        self.assertTrue(all('exFAT' in r or 'secret' in r for r in reasons.values()), reasons)

    def test_archive_skipped_when_volume_missing(self):
        root, cfg = self.setup_project()
        write(root / 'tmp/2026-10-01-task/a', age_days=20)
        self.archive.rmdir()
        self.archive.parent.rmdir()
        result, out = self.run_clean(cfg)
        self.assertEqual(result.done, [])
        self.assertIn('not mounted', out)
        self.assertTrue((root / 'tmp/2026-10-01-task/a').exists())

    def test_volumes_path_requires_a_mount_point(self):
        self.assertFalse(ds.archive_available(Path('/Volumes/definitely-not-mounted-xyz/DevArchive')))
        self.assertTrue(ds.archive_available(self.archive))


class TestSqliteBackup(Sandbox):
    def test_backup_of_live_wal_db_and_same_day_skip(self):
        root = make_repo(self.code / 'p')
        db = root / 'data/live.sqlite'
        db.parent.mkdir(parents=True)
        conn = sqlite3.connect(db)
        conn.execute('pragma journal_mode=wal')
        conn.execute('create table t(x)')
        conn.executemany('insert into t values (?)', [(i,) for i in range(500)])
        conn.commit()  # connection stays open, like the running server
        cfg = self.config(f"""
[projects.p]
root = "{root}"
[[projects.p.rules]]
id = "offsite"
why = "t"
action = "sqlite-backup"
when = "daily"
source = "data/live.sqlite"
keep_daily = 7
keep_weekly = 8
""")
        result, _ = self.run_clean(cfg)
        backups = sorted((self.archive / 'p/sqlite-backups/offsite').glob('live-*.sqlite.gz'))
        self.assertEqual(len(backups), 1)
        restored = self.home / 'restored.sqlite'
        restored.write_bytes(gzip.decompress(backups[0].read_bytes()))
        check = sqlite3.connect(restored)
        self.assertEqual(check.execute('pragma integrity_check').fetchone()[0], 'ok')
        self.assertEqual(check.execute('select count(*) from t').fetchone()[0], 500)
        result, out = self.run_clean(cfg)
        self.assertEqual(len(list((self.archive / 'p/sqlite-backups/offsite').glob('*.gz'))), 1)
        self.assertIn('already backed up today', out)
        conn.close()

    def test_retention_keeps_dailies_and_weeklies(self):
        day = 86400
        start = 1_700_000_000  # a Tuesday
        stamps = [start - i * day for i in range(60)] + [start - 3600]  # 60 days, plus a second one on day 0
        keep = ds.backups_to_keep(stamps, keep_daily=7, keep_weekly=4)
        days_kept = {int((start - s) // day) for s in keep}
        self.assertTrue(set(range(7)) <= days_kept)
        self.assertNotIn(start - 3600, keep)  # only the newest of a day is kept
        older = sorted(s for s in keep if start - s >= 7 * day)
        self.assertLessEqual(len(older), 4)
        self.assertNotIn(59, days_kept)


class TestConfig(Sandbox):
    def test_typos_and_bad_values_are_errors(self):
        root = make_repo(self.code / 'p')
        cases = {
            'age_day = 7': 'age_day',
            'action = "remove"': 'remove',
            'when = "weekly"': 'weekly',
        }
        for line, needle in cases.items():
            body = (
                f'[projects.p]\nroot = "{root}"\n[[projects.p.rules]]\nid = "r"\nwhy = "t"\npaths = ["tmp"]\n{line}\n'
            )
            if 'action' not in line:
                body += 'action = "delete"\n'
            with self.assertRaises(ds.ConfigError) as ctx:
                self.config(body)
            self.assertIn(needle, str(ctx.exception))
            self.assertIn('p', str(ctx.exception))
        dup = (
            f'[projects.p]\nroot = "{root}"\n'
            + '[[projects.p.rules]]\nid = "r"\nwhy = "t"\naction = "delete"\npaths = ["tmp"]\n' * 2
        )
        with self.assertRaises(ds.ConfigError):
            self.config(dup)

    def test_parse_size(self):
        self.assertEqual(ds.parse_size('15GiB'), 15 * GIB)
        self.assertEqual(ds.parse_size('512MiB'), 512 * 1024**2)


class TestMeasure(Sandbox):
    def test_clones_and_hardlinks_count_once_and_only_when_all_go(self):
        a = write(self.home / 'm/a', os.urandom(256 * 1024))
        subprocess.run(['cp', '-c', str(a), str(self.home / 'm/b')], check=True)
        os.link(self.home / 'm/b', self.home / 'm/c')
        du_a, real_a = ds.measure([a])
        self.assertGreater(du_a, 0)
        self.assertEqual(real_a, 0)  # its clone b still holds the data
        _, real_ab = ds.measure([a, self.home / 'm/b'])
        self.assertEqual(real_ab, 0)  # c is a hard link of b, still holding it
        _, real_all = ds.measure([self.home / 'm'])
        self.assertGreaterEqual(real_all, 256 * 1024)
        self.assertLess(real_all, 2 * 256 * 1024 + 64 * 1024)


class TestWatch(Sandbox):
    WATCH = """
[watch]
free_warn = "40GiB"
free_critical = "15GiB"
default_alert_size = "3GiB"
growth_alert = "3GiB"
realert_days = 3
backup_stale_days = 3
agent_cooldown_days = 14
agent_max_per_run = 1
agent_timeout_minutes = 1
[watch.caches]
uv = { path = "CACHE", budget = "1GiB" }
"""

    def cfg(self, body=''):
        return self.config(body, watch=self.WATCH.replace('CACHE', str(self.home / 'uvcache')))

    def test_measure_groups_related_dirs_into_their_project(self):
        root = make_repo(self.code / 'vb')
        write(self.code / 'vb-live/data', b'x' * 8192)
        write(self.code / 'loose/f', b'x' * 4096)
        write(self.home / 'uvcache/w', b'x' * 4096)
        cfg = self.cfg(f'[projects.vb]\nroot = "{root}"\nrelated = ["{self.code / "vb-live"}"]\nalert_size = "1GiB"\n')
        snap = ds.measure_all(cfg)
        self.assertIn('project:vb', snap.items)
        self.assertIn('project:loose', snap.items)
        self.assertNotIn('project:vb-live', snap.items)
        self.assertGreaterEqual(snap.items['project:vb'], 8192)
        self.assertIn('cache:uv', snap.items)

    def test_history_delta_uses_the_record_at_least_7_days_old(self):
        hist = [
            {'ts': NOW - 9 * DAY, 'items': {'project:a': 1 * GIB}},
            {'ts': NOW - 8 * DAY, 'items': {'project:a': 2 * GIB}},
            {'ts': NOW - 1 * DAY, 'items': {'project:a': 5 * GIB}},
        ]
        self.assertEqual(ds.history_delta(hist, 'project:a', 6 * GIB, NOW), 4 * GIB)
        self.assertIsNone(ds.history_delta(hist[2:], 'project:a', 6 * GIB, NOW))

    def test_evaluate_thresholds(self):
        root = make_repo(self.code / 'known')
        cfg = self.cfg(f'[projects.known]\nroot = "{root}"\nalert_size = "10GiB"\n')
        snap = ds.Snapshot(
            ts=NOW,
            free=10 * GIB,
            items={
                'project:known': 9 * GIB,
                'project:anon': 4 * GIB,
                'project:small': 1 * GIB,
                'cache:uv': 2 * GIB,
            },
        )
        hist = [{'ts': NOW - 8 * DAY, 'items': {'project:known': 2 * GIB}}]
        alerts = {a.key: a for a in ds.evaluate(snap, hist, cfg, NOW, last_backups={})}
        self.assertEqual(alerts['free'].level, 'critical')
        self.assertIn('project:anon:size', alerts)
        self.assertTrue(alerts['project:anon:size'].needs_agent)
        self.assertNotIn('project:known:size', alerts)
        self.assertIn('project:known:growth', alerts)
        self.assertIn('cache:uv:size', alerts)
        self.assertNotIn('project:small:size', alerts)

    def test_stale_offsite_backup_alerts(self):
        root = make_repo(self.code / 'p')
        cfg = self.cfg(f"""
[projects.p]
root = "{root}"
[[projects.p.rules]]
id = "offsite"
why = "t"
action = "sqlite-backup"
when = "daily"
source = "db.sqlite"
""")
        snap = ds.Snapshot(ts=NOW, free=100 * GIB, items={})
        alerts = ds.evaluate(snap, [], cfg, NOW, last_backups={'p/offsite': NOW - 5 * DAY})
        self.assertEqual([a.key for a in alerts], ['backup:p/offsite'])
        self.assertEqual(ds.evaluate(snap, [], cfg, NOW, last_backups={'p/offsite': NOW - DAY}), [])

    def test_dedupe(self):
        warn = ds.Alert(key='free', level='warn', message='m')
        crit = ds.Alert(key='free', level='critical', message='m')
        state = {}
        self.assertEqual(ds.dedupe([warn], state, NOW, realert_days=3), [warn])
        self.assertEqual(ds.dedupe([warn], state, NOW + DAY, realert_days=3), [])
        self.assertEqual(ds.dedupe([crit], state, NOW + DAY, realert_days=3), [crit])
        self.assertEqual(ds.dedupe([crit], state, NOW + 5 * DAY, realert_days=3), [crit])

    def test_dispatch_runs_read_only_codex_with_cooldown_and_cap(self):
        fake = self.home / 'bin/codex'
        argv_log = self.home / 'codex-argv.txt'
        write(
            fake,
            f"""#!/bin/sh
echo "$@" >> "{argv_log}"
while [ $# -gt 0 ]; do [ "$1" = "-o" ] && echo "# proposal" > "$2"; shift; done
""",
        )
        fake.chmod(0o755)
        a = make_repo(self.code / 'a')
        make_repo(self.code / 'b')
        cfg = self.cfg()
        alerts = [
            ds.Alert(key=f'project:{n}:size', level='warn', message='m', project=n, needs_agent=True)
            for n in ('a', 'b')
        ]
        out = io.StringIO()
        made = ds.dispatch_proposals(alerts, cfg, NOW, codex=str(fake), out=out, notify=lambda *a: None)
        self.assertEqual(len(made), 1)  # agent_max_per_run = 1
        argv = argv_log.read_text()
        self.assertIn('-s read-only', argv)
        self.assertIn(f'-C {a}', argv)
        self.assertTrue(made[0].exists())
        again = ds.dispatch_proposals(alerts[:1], cfg, NOW + DAY, codex=str(fake), out=out, notify=lambda *a: None)
        self.assertEqual(again, [])  # cooldown


if __name__ == '__main__':
    unittest.main(verbosity=1)

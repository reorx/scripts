#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = ["textual>=8.0"]
# ///
"""
Behavior tests for brewer.py

Run: uv run test_brewer.py
"""

import html
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('brewer', HERE / 'brewer.py')
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)


# A stand-in for brew: serves info/outdated JSON from FAKE_BREW_DIR and logs every call.
# `upgrade` drops the formula (plus whatever effects.json says it drags along) from outdated.json;
# `uninstall` refuses while another keg depends on the formula, else drops it from both files.
FAKE_BREW = """\
#!{python}
import json, os, signal, sys
from pathlib import Path

d = Path(os.environ['FAKE_BREW_DIR'])
args = sys.argv[1:]
line = ' '.join(args)
if args[:1] == ['upgrade']:
    wl = Path(os.environ['FAKE_WHITELIST'])
    entries = [l.strip() for l in wl.read_text().splitlines() if l.strip() and not l.startswith('#')] if wl.exists() else []
    line += ' | wl=' + ','.join(entries) + ' | auto_update=' + os.environ.get('HOMEBREW_NO_AUTO_UPDATE', '')
with open(d / 'calls.log', 'a') as f:
    f.write(line + '\\n')

if args[:1] == ['update']:
    sys.exit(int(os.environ.get('FAKE_UPDATE_EXIT', '0')))
if args[:2] == ['info', '--json=v2']:
    print((d / 'info.json').read_text())
    sys.exit(0)
if args[:2] == ['outdated', '--json=v2']:
    print((d / 'outdated.json').read_text())
    sys.exit(0)
if args[:1] in (['upgrade'], ['uninstall']) and args[1:2] == ['--formula']:
    name = args[2]
    # brew 7 asks before upgrading unless told not to; nobody answers here, like an unattended run
    if args[0] == 'upgrade' and not os.environ.get('HOMEBREW_NO_ASK') and not {{'-y', '--yes', '--no-ask'}} & set(args):
        print('==> Do you want to proceed with the upgrade? [y/n]')
        sys.exit(1)
    if name == os.environ.get('FAKE_INTERRUPT'):
        os.kill(os.getppid(), signal.SIGINT)
        sys.exit(130)
    if name in os.environ.get('FAKE_FAIL', '').split(','):
        sys.exit(1)
if args[:2] == ['uninstall', '--formula']:
    info = json.loads((d / 'info.json').read_text())
    users = [
        f['full_name'] for f in info['formulae']
        if any(name in [r['full_name'] for r in k['runtime_dependencies']] for k in f['installed'])
    ]
    if users:
        print(f'Error: Refusing to uninstall {{name}} because it is required by {{", ".join(users)}}')
        sys.exit(1)
    info['formulae'] = [f for f in info['formulae'] if f['full_name'] != name]
    (d / 'info.json').write_text(json.dumps(info))
    data = json.loads((d / 'outdated.json').read_text())
    data['formulae'] = [f for f in data['formulae'] if f['name'] != name]
    (d / 'outdated.json').write_text(json.dumps(data))
    sys.exit(0)
if args[:2] == ['upgrade', '--formula']:
    if name in os.environ.get('FAKE_NOOP', '').split(','):
        sys.exit(0)
    effects_file = d / 'effects.json'
    effects = json.loads(effects_file.read_text()) if effects_file.exists() else {{}}
    gone = {{name, *effects.get(name, [])}}
    data = json.loads((d / 'outdated.json').read_text())
    data['formulae'] = [f for f in data['formulae'] if f['name'] not in gone]
    (d / 'outdated.json').write_text(json.dumps(data))
    sys.exit(0)
sys.exit('fake brew: unexpected ' + line)
"""


def spec_(name, installed, latest, on_request=True, pinned=False, desc='', homepage='', deps=()):
    """One installed formula as both brew JSON views see it; `deps` are its runtime dependencies."""
    versions = [installed] if isinstance(installed, str) else list(installed)
    return {
        'name': name,
        'versions': versions,
        'latest': latest,
        'on_request': on_request,
        'pinned': pinned,
        'desc': desc or f'{name} desc',
        'homepage': homepage or f'https://example.com/{name.split("/")[-1]}',
        'deps': list(deps),
    }


def info_json(specs):
    return {
        'formulae': [
            {
                'name': s['name'].split('/')[-1],
                'full_name': s['name'],
                'desc': s['desc'],
                'homepage': s['homepage'],
                'pinned': s['pinned'],
                'installed': [
                    {
                        'version': v,
                        'installed_on_request': s['on_request'],
                        'runtime_dependencies': [{'full_name': d, 'version': '1.0'} for d in s['deps']],
                    }
                    for v in s['versions']
                ],
            }
            for s in specs
        ],
        'casks': [],
    }


def outdated_json(specs):
    return {
        'formulae': [
            {
                'name': s['name'],
                'installed_versions': s['versions'],
                'current_version': s['latest'],
                'pinned': s['pinned'],
                'pinned_version': s['versions'][-1] if s['pinned'] else None,
            }
            for s in specs
            if s['latest'] is not None
        ],
        'casks': [],
    }


def formula(name, installed, latest, level, pinned=False, desc='', required_by=()):
    return br.Formula(
        name,
        installed,
        latest,
        level,
        pinned,
        desc or f'{name} desc',
        f'https://example.com/{name}',
        list(required_by),
    )


class TestVersionLevel(unittest.TestCase):
    """The first differing position decides the level; examples come from the PRD table and real brew data."""

    def assert_level(self, level, cases):
        for old, new in cases:
            with self.subTest(old=old, new=new):
                self.assertEqual(br.version_level(old, new), level)

    def test_first_segment_is_major(self):
        self.assert_level(
            'major',
            [
                ('13.3.0', '14.5.0_1'),
                ('v2.2.0', 'v3.0.0'),
                ('303.141.1', '308'),
                ('3.0.0-beta3', '4.5.0'),
                ('0.2.3', '2.1.6'),
            ],
        )

    def test_second_segment_is_minor(self):
        self.assert_level(
            'minor',
            [
                ('1.25.7_1', '1.27.3'),
                ('3.5a', '3.8'),
                ('2026.8.19_1', '2026.10.21_1'),
                ('0.4.6', '0.7.0'),
                ('0.15.1b', '0.16.5'),
                ('7.95_1', '7.993'),
                ('RELEASE.2025-07-23T15-54-02Z_1', 'RELEASE.2025-09-06T17-38-46Z_1'),
            ],
        )

    def test_later_segments_and_revisions_are_patch(self):
        self.assert_level(
            'patch',
            [
                ('5.9', '5.9.2'),
                ('7.1.2-3_1', '7.1.2-34'),
                ('1.37.0', '1.37.0_3'),
                ('1.4.0_40', '1.4.0_43'),
                ('0.4.85', '0.4.123'),
                ('2.1.1788856981', '2.1.1792588164'),
            ],
        )

    def test_numbers_compare_by_value_not_text(self):
        self.assertEqual(br.version_level('2026.07.1', '2026.7.2'), 'patch')

    def test_unreadable_versions_count_as_major(self):
        self.assertEqual(br.version_level('latest', 'stable'), 'major')


class TestScan(unittest.TestCase):
    def scan(self, specs):
        return {f.name: f for f in br.parse_scan(info_json(specs), outdated_json(specs))}

    def test_dependency_only_formulae_are_left_out(self):
        got = self.scan([spec_('gh', '2.101.0', '2.103.3'), spec_('icu4c@78', '78.3', '78.4', on_request=False)])
        self.assertEqual(list(got), ['gh'])

    def test_one_keg_installed_on_request_is_enough(self):
        specs = [spec_('tree', ['2.1.3', '2.3.1'], '2.4.0')]
        info = info_json(specs)
        info['formulae'][0]['installed'][0]['installed_on_request'] = False
        got = br.parse_scan(info, outdated_json(specs))
        self.assertEqual([f.name for f in got], ['tree'])

    def test_compares_the_newest_installed_version(self):
        got = self.scan([spec_('flyctl', ['0.3.40', '0.3.110', '0.4.85'], '0.5.0')])
        self.assertEqual(got['flyctl'].installed, '0.4.85')
        self.assertEqual(got['flyctl'].level, 'minor')

    def test_tap_formulae_keep_their_full_name(self):
        got = self.scan([spec_('stripe/stripe-cli/stripe', '1.43.6', '1.55.2', desc='Stripe CLI utility')])
        self.assertEqual(got['stripe/stripe-cli/stripe'].desc, 'Stripe CLI utility')

    def test_carries_description_homepage_and_pin(self):
        got = self.scan(
            [spec_('redis', '7.2.6', '8.10.3', pinned=True, desc='Key-value store', homepage='https://redis.io')]
        )
        r = got['redis']
        self.assertEqual(
            (r.installed, r.latest, r.level, r.pinned, r.desc, r.homepage),
            ('7.2.6', '8.10.3', 'major', True, 'Key-value store', 'https://redis.io'),
        )

    def test_up_to_date_formulae_are_not_listed(self):
        got = self.scan([spec_('gh', '2.101.0', None), spec_('fd', '10.2.0', '10.5.0')])
        self.assertEqual(list(got), ['fd'])

    def test_required_by_lists_every_installed_formula_depending_on_it(self):
        got = self.scan(
            [
                spec_('xz', '5.8.1', '6.0.0'),
                spec_('zstd', '1.5.7', None, on_request=False, deps=['xz']),
                spec_('ansible', '12.1.0', None, deps=['tree', 'xz']),
                spec_('tree', '2.1.3', '2.4.0'),
            ]
        )
        self.assertEqual(got['xz'].required_by, ['ansible', 'zstd'])
        self.assertEqual(got['tree'].required_by, ['ansible'])

    def test_kegs_without_dependency_records_require_nothing(self):
        specs = [spec_('xz', '5.8.1', '6.0.0'), spec_('zstd', '1.5.7', None, on_request=False)]
        info = info_json(specs)
        info['formulae'][1]['installed'][0]['runtime_dependencies'] = None
        got = br.parse_scan(info, outdated_json(specs))
        self.assertEqual(got[0].required_by, [])


class TestWhitelist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name, 'brewer', 'whitelist')

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_is_empty(self):
        self.assertEqual(br.load_whitelist(self.path), [])

    def test_load_skips_comments_and_blanks(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('# header\n\n gh \n# yt-dlp\nfd\n')
        self.assertEqual(br.load_whitelist(self.path), ['gh', 'fd'])

    def test_short_and_full_names_match_each_other(self):
        self.assertTrue(br.in_whitelist('stripe/stripe-cli/stripe', ['stripe']))
        self.assertTrue(br.in_whitelist('stripe', ['stripe/stripe-cli/stripe']))
        self.assertFalse(br.in_whitelist('stripe-mock', ['stripe']))

    def test_add_creates_file_with_header_and_skips_duplicates(self):
        self.assertEqual(br.add_to_whitelist(self.path, ['gh', 'fd', 'gh']), ['gh', 'fd'])
        self.assertEqual(br.add_to_whitelist(self.path, ['fd', 'bat']), ['bat'])
        text = self.path.read_text()
        self.assertTrue(text.startswith('#'))
        self.assertEqual(br.load_whitelist(self.path), ['gh', 'fd', 'bat'])

    def test_add_keeps_hand_written_lines(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('# mine\ngh  \n# keep this')
        br.add_to_whitelist(self.path, ['fd'])
        self.assertEqual(self.path.read_text(), '# mine\ngh  \n# keep this\nfd\n')

    def test_add_treats_short_name_of_listed_tap_formula_as_duplicate(self):
        br.add_to_whitelist(self.path, ['stripe/stripe-cli/stripe'])
        self.assertEqual(br.add_to_whitelist(self.path, ['stripe']), [])

    def test_remove_drops_only_matching_lines(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('# mine\ngh\nstripe/stripe-cli/stripe\nfd\n')
        self.assertEqual(br.remove_from_whitelist(self.path, ['stripe', 'nope', 'fd']), ['stripe', 'fd'])
        self.assertEqual(self.path.read_text(), '# mine\ngh\n')


class TestMakePlan(unittest.TestCase):
    def test_splits_by_whitelist_level_and_pin(self):
        formulae = [
            formula('zsh', '5.9', '5.9.2', 'patch'),
            formula('gh', '2.101.0', '2.103.3', 'minor'),
            formula('watch', '4.0.5', '4.0.7', 'patch'),
            formula('tmux', '3.5a', '3.8', 'minor'),
            formula('ripgrep', '14.1.1', '15.2.0', 'major'),
            formula('bat', '0.25.0', '0.26.1', 'minor'),
            formula('redis', '7.2.6', '8.10.3', 'major', pinned=True),
            formula('node', '26.9.0', '26.12.1', 'minor', pinned=True),
        ]
        plan = br.make_plan(formulae, ['gh', 'watch', 'node'])
        self.assertEqual([f.name for f in plan.auto], ['gh', 'watch'])
        # Major first, then Minor, names sorted within each
        self.assertEqual([f.name for f in plan.review], ['ripgrep', 'bat', 'tmux'])
        self.assertEqual([f.name for f in plan.ignored], ['zsh'])
        self.assertEqual([f.name for f in plan.pinned], ['redis', 'node'])


class TestRemovalOrder(unittest.TestCase):
    def test_dependents_go_before_what_they_depend_on(self):
        # ansible needs libyaml and pyyaml, pyyaml needs libyaml (dependency lists are recursive)
        formulae = [
            formula('libyaml', '0.2.5', '1.0.0', 'major', required_by=['ansible', 'pyyaml']),
            formula('ansible', '12.1.0', '13.0.0', 'major'),
            formula('pyyaml', '6.0.2', '7.0.0', 'major', required_by=['ansible']),
            formula('bat', '0.25.0', '0.26.1', 'minor', required_by=['other']),
        ]
        self.assertEqual([f.name for f in br.removal_order(formulae)], ['ansible', 'bat', 'pyyaml', 'libyaml'])


LONG_DESC = 'Search tool like grep and The Silver Searcher, but faster and gitignore-aware'


def screen_text(app):
    """What the terminal shows, as plain text (the SVG export encodes spaces)."""
    return html.unescape(app.export_screenshot()).replace('\xa0', ' ')


class TestReviewApp(unittest.IsolatedAsyncioTestCase):
    def make_app(self):
        return br.ReviewApp(
            [
                formula('ripgrep', '14.1.1', '15.2.0', 'major', desc=LONG_DESC),
                formula('bat', '0.25.0', '0.26.1', 'minor', required_by=['delta', 'tmux', 'zellij']),
                formula('tmux', '3.5a', '3.8', 'minor'),
            ]
        )

    async def run_keys(self, *keys):
        app = self.make_app()
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.press(*keys)
        return app

    async def test_x_marks_for_uninstall_and_drops_the_other_marks(self):
        app = await self.run_keys('d', 'x', 'enter')
        self.assertEqual(app.return_value, br.Choice([], [], ['ripgrep']))

    async def test_x_again_drops_the_uninstall_mark(self):
        app = await self.run_keys('x', 'x', 'enter')
        self.assertEqual(app.return_value, br.Choice([], [], []))

    async def test_space_or_d_on_a_row_marked_for_uninstall_drops_that_mark(self):
        app = await self.run_keys('x', 'space', 'down', 'x', 'd', 'enter')
        self.assertEqual(app.return_value, br.Choice(['ripgrep', 'bat'], ['bat'], []))

    async def test_x_on_a_formula_others_need_warns_but_still_marks(self):
        with mock.patch.object(br.ReviewApp, 'notify') as notify:
            app = await self.run_keys('down', 'x', 'enter')
        self.assertEqual(app.return_value, br.Choice([], [], ['bat']))
        message = notify.call_args.args[0]
        self.assertIn('delta, tmux, zellij', message)
        self.assertEqual(notify.call_args.kwargs.get('severity'), 'warning')

    async def test_dependents_already_marked_for_uninstall_are_not_warned_about(self):
        with mock.patch.object(br.ReviewApp, 'notify') as notify:
            await self.run_keys('down', 'down', 'x', 'up', 'x', 'enter')
        message = notify.call_args.args[0]
        self.assertIn('delta, zellij', message)
        self.assertNotIn('tmux', message)

    async def test_x_on_a_formula_nothing_needs_does_not_warn(self):
        with mock.patch.object(br.ReviewApp, 'notify') as notify:
            await self.run_keys('x', 'enter')
        notify.assert_not_called()

    async def test_uninstall_marks_and_count_are_visible(self):
        app = self.make_app()
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.press('x', 'down', 'down', 'x')
            screen = app.export_screenshot()
            status = app.status_text()
            await pilot.press('q')
        self.assertEqual(screen.count('✗'), 2)
        self.assertIn('2 to uninstall', status)

    async def test_i_shows_full_description_homepage_and_dependents(self):
        app = self.make_app()
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.press('i')
            ripgrep = (isinstance(app.screen, br.InfoScreen), screen_text(app))
            await pilot.press('escape', 'down', 'i')
            bat = screen_text(app)
            await pilot.press('escape')
            closed = not isinstance(app.screen, br.InfoScreen)
            await pilot.press('q')
        self.assertTrue(ripgrep[0])
        self.assertIn(LONG_DESC, ripgrep[1])
        self.assertIn('https://example.com/ripgrep', ripgrep[1])
        self.assertIn('none', ripgrep[1])
        self.assertIn('delta, tmux, zellij', bat)
        self.assertTrue(closed)

    async def test_i_and_q_close_the_info_panel_too(self):
        for key in ('i', 'q'):
            with self.subTest(key=key):
                app = await self.run_keys('i', key, 'space', 'enter')
                self.assertEqual(app.return_value, br.Choice(['ripgrep'], []))

    async def test_o_in_the_info_panel_opens_that_homepage(self):
        with mock.patch.object(br.webbrowser, 'open') as opened:
            await self.run_keys('down', 'i', 'o', 'escape', 'q')
        opened.assert_called_once_with('https://example.com/bat')

    async def test_marking_keys_and_enter_do_nothing_in_the_info_panel(self):
        app = await self.run_keys('i', 'space', 'd', 'x', 'enter', 'escape', 'space', 'enter')
        self.assertEqual(app.return_value, br.Choice(['ripgrep'], []))

    async def test_nothing_is_selected_at_start(self):
        app = await self.run_keys('enter')
        self.assertEqual(app.return_value, br.Choice([], []))

    async def test_space_toggles_upgrade_for_the_row_under_the_cursor(self):
        app = await self.run_keys('space', 'down', 'down', 'space', 'up', 'space', 'space', 'enter')
        self.assertEqual(app.return_value, br.Choice(['ripgrep', 'tmux'], []))

    async def test_j_and_k_move_the_cursor(self):
        app = await self.run_keys('j', 'j', 'k', 'space', 'enter')
        self.assertEqual(app.return_value, br.Choice(['bat'], []))

    async def test_d_whitelists_and_selects_for_upgrade(self):
        app = await self.run_keys('down', 'd', 'enter')
        self.assertEqual(app.return_value, br.Choice(['bat'], ['bat']))

    async def test_d_again_drops_whitelist_but_keeps_upgrade(self):
        app = await self.run_keys('d', 'd', 'enter')
        self.assertEqual(app.return_value, br.Choice(['ripgrep'], []))

    async def test_unselecting_a_whitelisted_row_drops_both_marks(self):
        app = await self.run_keys('d', 'space', 'enter')
        self.assertEqual(app.return_value, br.Choice([], []))

    async def test_q_and_escape_cancel(self):
        for key in ('q', 'escape'):
            with self.subTest(key=key):
                app = await self.run_keys('space', 'd', key)
                self.assertIsNone(app.return_value)

    async def test_o_opens_the_homepage_of_the_current_row(self):
        with mock.patch.object(br.webbrowser, 'open') as opened:
            await self.run_keys('down', 'o', 'q')
        opened.assert_called_once_with('https://example.com/bat')

    async def test_marks_are_visible_on_the_rows(self):
        app = self.make_app()
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.press('space', 'down', 'd', 'down')
            screen = app.export_screenshot()
            await pilot.press('q')
        self.assertEqual(screen.count('✓'), 2)
        self.assertEqual(screen.count('★'), 1)

    async def test_status_counts_levels_and_marks(self):
        app = self.make_app()
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.press('space', 'down', 'd')
            status = app.status_text()
            await pilot.press('q')
        self.assertIn('1 major', status)
        self.assertIn('2 minor', status)
        self.assertIn('2 selected', status)
        self.assertIn('1 to whitelist', status)
        self.assertIn('0 to uninstall', status)


class FakeBrewCase(unittest.TestCase):
    """Runs main() in-process against a fake brew first in PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        fake = bin_dir / 'brew'
        fake.write_text(FAKE_BREW.format(python=sys.executable))
        fake.chmod(0o755)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.whitelist = self.root / 'config' / 'whitelist'
        self.env = {
            'PATH': f'{bin_dir}:{os.environ["PATH"]}',
            'FAKE_BREW_DIR': str(self.state),
            'FAKE_WHITELIST': str(self.whitelist),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def set_brew(self, specs, effects=None):
        (self.state / 'info.json').write_text(json.dumps(info_json(specs)))
        (self.state / 'outdated.json').write_text(json.dumps(outdated_json(specs)))
        if effects:
            (self.state / 'effects.json').write_text(json.dumps(effects))

    def set_whitelist(self, *names):
        self.whitelist.parent.mkdir(parents=True, exist_ok=True)
        self.whitelist.write_text(''.join(f'{n}\n' for n in names))

    def actions(self):
        """update/upgrade/uninstall calls in order, without the read-only JSON queries."""
        log = self.state / 'calls.log'
        lines = log.read_text().splitlines() if log.exists() else []
        return [line for line in lines if line.split()[0] in ('update', 'upgrade', 'uninstall')]

    def upgraded(self):
        return [line.split()[2] for line in self.actions() if line.startswith('upgrade')]

    def changes(self):
        """`upgrade name` / `uninstall name` in the order brew ran them."""
        return [' '.join(line.split()[:3:2]) for line in self.actions() if line.split()[0] != 'update']

    def run_main(self, argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, {**self.env, **(env or {})}),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = br.main([*argv, '--whitelist', str(self.whitelist)])
        return code, out.getvalue(), err.getvalue()


def section(out, title):
    """Indented lines under a `title:` line of the summary."""
    lines = out.splitlines()
    try:
        start = lines.index(f'{title}:')
    except ValueError:
        return []
    items = []
    for line in lines[start + 1 :]:
        if not line.startswith('  '):
            break
        items.append(line.strip())
    return items


class TestOutdatedCommand(FakeBrewCase):
    def setUp(self):
        super().setUp()
        self.set_brew(
            [
                spec_('ripgrep', '14.1.1', '15.2.0'),
                spec_('redis', '7.2.6', '8.10.3', pinned=True),
                spec_('gh', '2.101.0', '2.103.3'),
                spec_('zsh', '5.9', '5.9.2'),
                spec_('watch', '4.0.5', '4.0.7'),
                spec_('icu4c@78', '78.3', '79.1', on_request=False),
            ]
        )
        self.set_whitelist('gh', 'watch')

    def test_updates_then_lists_major_and_minor_groups(self):
        code, out, _ = self.run_main(['outdated'])
        self.assertEqual(code, 0)
        self.assertEqual(self.actions(), ['update'])
        self.assertRegex(
            out, r'Major \(2\)\n  redis\s+7\.2\.6\s+→ 8\.10\.3\s+pinned\n  ripgrep\s+14\.1\.1\s+→ 15\.2\.0\n'
        )
        self.assertRegex(out, r'Minor \(1\)\n  gh\s+2\.101\.0\s+→ 2\.103\.3\s+whitelist\n')

    def test_patch_only_and_dependencies_stay_out_of_the_lists(self):
        _, out, _ = self.run_main(['outdated'])
        self.assertNotIn('zsh', out)
        self.assertNotIn('icu4c', out)
        self.assertIn('1 patch-only ignored', out)
        self.assertIn('2 whitelisted to auto-upgrade', out)

    def test_no_update_skips_brew_update(self):
        self.run_main(['outdated', '--no-update'])
        self.assertEqual(self.actions(), [])

    def test_failed_update_warns_and_still_lists(self):
        code, out, err = self.run_main(['outdated'], {'FAKE_UPDATE_EXIT': '1'})
        self.assertEqual(code, 0)
        self.assertIn('brew update failed', err)
        self.assertIn('ripgrep', out)

    def test_nothing_outdated(self):
        self.set_brew([spec_('gh', '2.101.0', None)])
        _, out, _ = self.run_main(['outdated', '--no-update'])
        self.assertIn('All formulae are up to date.', out)


class TestUpgradeCommand(FakeBrewCase):
    def setUp(self):
        super().setUp()
        self.set_brew(
            [
                spec_('gh', '2.101.0', '2.103.3'),
                spec_('watch', '4.0.5', '4.0.7'),
                spec_('ripgrep', '14.1.1', '15.2.0'),
                spec_('bat', '0.25.0', '0.26.1'),
                spec_('tmux', '3.5a', '3.8'),
                spec_('fd', '10.2.0', '10.5.0'),
                spec_('zsh', '5.9', '5.9.2'),
                spec_('icu4c@78', '78.3', '79.1', on_request=False),
            ],
            # upgrading gh also upgrades fd as an outdated dependent
            effects={'gh': ['fd']},
        )
        self.set_whitelist('gh', 'watch')
        self.reviewed = None
        self.choice = br.Choice([], [])

    def run_upgrade(self, *args, env=None, interactive=True):
        test = self

        def fake_run(app):
            test.reviewed = [f.name for f in app.formulae]
            return test.choice

        with (
            mock.patch.object(br.ReviewApp, 'run', fake_run),
            mock.patch.object(br, 'is_interactive', return_value=interactive),
        ):
            return self.run_main(['upgrade', *args], env)

    def test_whitelisted_upgrade_first_then_review_what_is_still_outdated(self):
        code, out, _ = self.run_upgrade()
        self.assertEqual(code, 0)
        actions = self.actions()
        self.assertEqual(actions[0], 'update')
        self.assertEqual(self.upgraded(), ['gh', 'watch'])
        # fd went away with gh, zsh is patch-only, icu4c is a dependency
        self.assertEqual(self.reviewed, ['ripgrep', 'bat', 'tmux'])
        self.assertIn('[1/2] gh 2.101.0 → 2.103.3', out)

    def test_upgrades_skip_brew_auto_update(self):
        self.run_upgrade()
        self.assertTrue(all(line.endswith('auto_update=1') for line in self.actions() if line.startswith('upgrade')))

    def test_upgrades_never_ask_for_confirmation(self):
        # the review TUI is the confirmation, brew's own prompt must not stop the run again
        self.choice = br.Choice(['ripgrep'], [])
        code, out, _ = self.run_upgrade()
        self.assertEqual(code, 0)
        self.assertNotIn('Do you want to proceed', out)
        self.assertEqual(section(out, 'Upgraded (selected)'), ['ripgrep 14.1.1 → 15.2.0'])

    def test_selected_upgrade_after_whitelist_is_saved(self):
        self.choice = br.Choice(['ripgrep', 'tmux'], ['tmux'])
        code, out, _ = self.run_upgrade()
        self.assertEqual(code, 0)
        self.assertEqual(self.upgraded(), ['gh', 'watch', 'ripgrep', 'tmux'])
        ripgrep_call = next(line for line in self.actions() if line.startswith('upgrade --formula ripgrep'))
        self.assertIn('wl=gh,watch,tmux', ripgrep_call)
        self.assertEqual(br.load_whitelist(self.whitelist), ['gh', 'watch', 'tmux'])

    def test_summary_groups(self):
        self.choice = br.Choice(['ripgrep', 'tmux'], ['tmux'])
        _, out, _ = self.run_upgrade()
        self.assertEqual(section(out, 'Upgraded (whitelist)'), ['gh 2.101.0 → 2.103.3', 'watch 4.0.5 → 4.0.7'])
        self.assertEqual(section(out, 'Upgraded (selected)'), ['ripgrep 14.1.1 → 15.2.0', 'tmux 3.5a → 3.8'])
        self.assertEqual(section(out, 'Also upgraded by Homebrew'), ['fd 10.2.0 → 10.5.0'])
        self.assertEqual(section(out, 'Added to whitelist'), ['tmux'])
        self.assertEqual(section(out, 'Failed'), [])
        self.assertIn('1 not selected · 1 patch-only ignored', out)

    def test_no_review_when_nothing_needs_confirmation(self):
        self.set_whitelist('gh', 'watch', 'ripgrep', 'bat', 'tmux')
        code, _, _ = self.run_upgrade()
        self.assertEqual(code, 0)
        self.assertIsNone(self.reviewed)
        self.assertEqual(self.upgraded(), ['gh', 'watch', 'ripgrep', 'bat', 'tmux'])

    def test_cancel_upgrades_nothing_more_and_keeps_whitelist(self):
        self.choice = None
        code, out, _ = self.run_upgrade()
        self.assertEqual(code, 0)
        self.assertEqual(self.upgraded(), ['gh', 'watch'])
        self.assertEqual(br.load_whitelist(self.whitelist), ['gh', 'watch'])
        self.assertIn('Review cancelled', out)
        self.assertIn('3 not selected', out)

    def test_failure_keeps_going_and_exits_non_zero(self):
        self.choice = br.Choice(['ripgrep', 'tmux'], [])
        code, out, _ = self.run_upgrade(env={'FAKE_FAIL': 'watch,ripgrep'})
        self.assertEqual(code, 1)
        self.assertEqual(self.upgraded(), ['gh', 'watch', 'ripgrep', 'tmux'])
        self.assertEqual(section(out, 'Failed'), ['watch (exit 1)', 'ripgrep (exit 1)'])
        self.assertEqual(section(out, 'Upgraded (selected)'), ['tmux 3.5a → 3.8'])

    def test_success_that_leaves_formula_outdated_is_a_failure(self):
        code, out, _ = self.run_upgrade(env={'FAKE_NOOP': 'watch'})
        self.assertEqual(code, 1)
        self.assertEqual(section(out, 'Failed'), ['watch (still outdated)'])

    def test_dry_run_changes_nothing(self):
        self.choice = br.Choice(['ripgrep', 'tmux'], ['tmux'])
        code, out, _ = self.run_upgrade('--dry-run')
        self.assertEqual(code, 0)
        self.assertEqual(self.upgraded(), [])
        self.assertEqual(br.load_whitelist(self.whitelist), ['gh', 'watch'])
        self.assertIn('would run: brew upgrade --formula gh', out)
        self.assertIn('would run: brew upgrade --formula tmux', out)
        self.assertEqual(section(out, 'Would upgrade (whitelist)'), ['gh 2.101.0 → 2.103.3', 'watch 4.0.5 → 4.0.7'])
        self.assertEqual(section(out, 'Would upgrade (selected)'), ['ripgrep 14.1.1 → 15.2.0', 'tmux 3.5a → 3.8'])
        self.assertEqual(section(out, 'Would add to whitelist'), ['tmux'])

    def test_no_update_skips_brew_update(self):
        self.run_upgrade('--no-update')
        self.assertNotIn('update', self.actions())

    def test_not_a_terminal_lists_candidates_without_review(self):
        code, out, _ = self.run_upgrade(interactive=False)
        self.assertEqual(code, 0)
        self.assertIsNone(self.reviewed)
        self.assertEqual(self.upgraded(), ['gh', 'watch'])
        self.assertIn('skipped: not a terminal', out)
        self.assertRegex(out, r'ripgrep\s+14\.1\.1\s+→ 15\.2\.0')
        self.assertIn('3 left to review', out)

    def test_no_review_upgrades_the_whitelist_and_only_lists_the_rest(self):
        code, out, _ = self.run_upgrade('--no-review')
        self.assertEqual(code, 0)
        self.assertIsNone(self.reviewed)
        self.assertEqual(self.changes(), ['upgrade gh', 'upgrade watch'])
        self.assertIn('skipped: --no-review', out)
        self.assertRegex(out, r'tmux\s+3\.5a\s+→ 3\.8')
        self.assertEqual(section(out, 'Upgraded (whitelist)'), ['gh 2.101.0 → 2.103.3', 'watch 4.0.5 → 4.0.7'])
        self.assertIn('3 left to review · 1 patch-only ignored', out)

    def test_no_review_with_dry_run_changes_nothing(self):
        code, out, _ = self.run_upgrade('--no-review', '--dry-run')
        self.assertEqual(code, 0)
        self.assertIsNone(self.reviewed)
        self.assertEqual(self.changes(), [])
        self.assertEqual(section(out, 'Would upgrade (whitelist)'), ['gh 2.101.0 → 2.103.3', 'watch 4.0.5 → 4.0.7'])

    def test_uninstalls_before_upgrading_the_selected(self):
        self.choice = br.Choice(['ripgrep'], [], ['tmux'])
        code, out, _ = self.run_upgrade()
        self.assertEqual(code, 0)
        self.assertEqual(self.changes(), ['upgrade gh', 'upgrade watch', 'uninstall tmux', 'upgrade ripgrep'])
        self.assertIn('To uninstall: tmux', out)
        self.assertIn('Selected: ripgrep', out)

    def test_summary_lists_uninstalled_and_keeps_them_out_of_also_upgraded(self):
        self.choice = br.Choice(['ripgrep'], [], ['tmux'])
        _, out, _ = self.run_upgrade()
        self.assertEqual(section(out, 'Uninstalled'), ['tmux 3.5a'])
        self.assertEqual(section(out, 'Also upgraded by Homebrew'), ['fd 10.2.0 → 10.5.0'])
        self.assertEqual(section(out, 'Failed'), [])
        # bat was neither upgraded nor uninstalled
        self.assertIn('1 not selected · 1 patch-only ignored', out)

    def test_dependents_are_uninstalled_before_what_they_need(self):
        self.set_brew(
            [
                spec_('bat', '0.25.0', '0.26.1'),
                spec_('tmux', '3.5a', '3.8', deps=['bat']),
                spec_('ripgrep', '14.1.1', '15.2.0'),
            ]
        )
        self.choice = br.Choice([], [], ['bat', 'tmux'])
        code, out, _ = self.run_upgrade('--no-update')
        self.assertEqual(code, 0)
        self.assertEqual(self.changes(), ['uninstall tmux', 'uninstall bat'])
        self.assertEqual(section(out, 'Uninstalled'), ['tmux 3.5a', 'bat 0.25.0'])

    def test_refused_uninstall_keeps_going_and_exits_non_zero(self):
        # tmux needs bat, but only bat is marked: brew refuses
        self.set_brew(
            [
                spec_('bat', '0.25.0', '0.26.1'),
                spec_('tmux', '3.5a', '3.8', deps=['bat']),
                spec_('ripgrep', '14.1.1', '15.2.0'),
            ]
        )
        self.choice = br.Choice(['ripgrep'], [], ['bat'])
        code, out, _ = self.run_upgrade('--no-update')
        self.assertEqual(code, 1)
        self.assertEqual(self.changes(), ['uninstall bat', 'upgrade ripgrep'])
        self.assertEqual(section(out, 'Failed'), ['bat (uninstall exit 1)'])
        self.assertEqual(section(out, 'Upgraded (selected)'), ['ripgrep 14.1.1 → 15.2.0'])
        self.assertEqual(section(out, 'Uninstalled'), [])

    def test_ctrl_c_during_uninstall_stops_the_rest(self):
        self.choice = br.Choice(['ripgrep'], [], ['tmux'])
        code, out, _ = self.run_upgrade(env={'FAKE_INTERRUPT': 'tmux'})
        self.assertEqual(code, 130)
        self.assertEqual(self.changes(), ['upgrade gh', 'upgrade watch', 'uninstall tmux'])
        self.assertEqual(section(out, 'Failed'), ['tmux (uninstall interrupted)'])

    def test_dry_run_only_prints_the_uninstall(self):
        self.choice = br.Choice([], [], ['tmux'])
        code, out, _ = self.run_upgrade('--dry-run')
        self.assertEqual(code, 0)
        self.assertEqual(self.changes(), [])
        self.assertIn('would run: brew uninstall --formula tmux', out)
        self.assertEqual(section(out, 'Would uninstall'), ['tmux 3.5a'])

    def test_ctrl_c_stops_the_rest_but_keeps_whitelist_and_summary(self):
        self.choice = br.Choice(['ripgrep', 'bat', 'tmux'], ['bat'])
        code, out, _ = self.run_upgrade(env={'FAKE_INTERRUPT': 'bat'})
        self.assertEqual(code, 130)
        self.assertEqual(self.upgraded(), ['gh', 'watch', 'ripgrep', 'bat'])
        self.assertEqual(br.load_whitelist(self.whitelist), ['gh', 'watch', 'bat'])
        self.assertEqual(section(out, 'Failed'), ['bat (interrupted)'])
        self.assertEqual(section(out, 'Upgraded (selected)'), ['ripgrep 14.1.1 → 15.2.0'])
        self.assertEqual(section(out, 'Added to whitelist'), ['bat'])

    def test_already_up_to_date(self):
        self.set_brew([spec_('gh', '2.101.0', None)])
        code, out, _ = self.run_upgrade('--no-update')
        self.assertEqual(code, 0)
        self.assertIsNone(self.reviewed)
        self.assertIn('All formulae are up to date.', out)


class TestWhitelistCommand(FakeBrewCase):
    def setUp(self):
        super().setUp()
        self.set_brew([spec_('gh', '2.101.0', None), spec_('libpng', '1.6.58', None, on_request=False)])

    def test_lists_path_and_entries(self):
        self.set_whitelist('gh', 'fd')
        code, out, _ = self.run_main(['whitelist'])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [str(self.whitelist), 'gh', 'fd'])

    def test_empty(self):
        _, out, _ = self.run_main(['whitelist'])
        self.assertIn('(empty)', out)

    def test_add_warns_about_formulae_not_installed_on_request(self):
        code, out, err = self.run_main(['whitelist', 'add', 'gh', 'libpng'])
        self.assertEqual(code, 0)
        self.assertEqual(br.load_whitelist(self.whitelist), ['gh', 'libpng'])
        self.assertIn('libpng', err)
        self.assertNotIn('gh', err)
        self.assertIn('Added: gh, libpng', out)

    def test_add_existing_entry(self):
        self.set_whitelist('gh')
        _, out, _ = self.run_main(['whitelist', 'add', 'gh'])
        self.assertIn('Already in whitelist: gh', out)

    def test_rm_reports_missing_and_keeps_comments(self):
        self.whitelist.parent.mkdir(parents=True)
        self.whitelist.write_text('# mine\ngh\nfd\n')
        code, out, err = self.run_main(['whitelist', 'rm', 'gh', 'nope'])
        self.assertEqual(code, 0)
        self.assertEqual(self.whitelist.read_text(), '# mine\nfd\n')
        self.assertIn('Removed: gh', out)
        self.assertIn('Not in whitelist: nope', err)

    def test_add_without_names_is_an_error(self):
        with self.assertRaises(SystemExit):
            self.run_main(['whitelist', 'add'])


class TestMissingBrew(unittest.TestCase):
    def test_reports_and_exits_non_zero(self):
        err = io.StringIO()
        with (
            mock.patch.dict(os.environ, {'PATH': '/nonexistent'}),
            redirect_stderr(err),
            redirect_stdout(io.StringIO()),
        ):
            code = br.main(['outdated', '--no-update'])
        self.assertNotEqual(code, 0)
        self.assertIn('brew not found', err.getvalue())


@unittest.skipUnless(shutil.which('brew'), 'brew not installed')
class TestRealBrew(unittest.TestCase):
    """Read-only smoke test against this machine's Homebrew."""

    def test_scan_only_reports_formulae_installed_on_request(self):
        with mock.patch.dict(os.environ, {'HOMEBREW_NO_AUTO_UPDATE': '1'}):
            found = br.scan()
            info = br.brew_json('info', '--json=v2', '--installed')
        on_request = {
            f['full_name'] for f in info['formulae'] if any(k['installed_on_request'] for k in f['installed'])
        }
        for f in found:
            self.assertIn(f.name, on_request)
            self.assertIn(f.level, br.LEVELS)
            self.assertTrue(re.search(r'\d', f.latest), f.latest)


if __name__ == '__main__':
    unittest.main()

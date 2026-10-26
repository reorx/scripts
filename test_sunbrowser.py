#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Behavior tests: uv run test_sunbrowser.py."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('sunbrowser.py')
SPEC = importlib.util.spec_from_file_location('sunbrowser', SCRIPT)
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)

APP = '/Users/me/Library/Application Support/adspower_global/cwd_global/chrome_152/SunBrowser.app'
CACHE = '/Users/me/Library/Application Support/adspower_global/cwd_global/source/cache'


def main_line(pid, udd):
    return (
        f'{pid} {APP}/Contents/MacOS/SunBrowser --force-color-profile=srgb --no-first-run '
        f'--user-data-dir={udd} --no-default-browser-check --remote-debugging-port=0 --lang=en-US'
    )


def helper_line(pid, udd):
    return (
        f'{pid} {APP}/Contents/Frameworks/SunBrowser Framework.framework/Versions/152.0/Helpers/'
        f'SunBrowser Helper (Renderer).app/Contents/MacOS/SunBrowser Helper (Renderer) --type=renderer '
        f'--user-data-dir={udd} --lang=en-US'
    )


def make_profile(root, name, port=60468, path='/devtools/browser/abc-123'):
    udd = Path(root) / name
    udd.mkdir()
    (udd / 'DevToolsActivePort').write_text(f'{port}\n{path}')
    return str(udd)


def bash_event(command):
    return {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': command}}


class FindInstancesTest(unittest.TestCase):
    def test_keeps_main_process_and_skips_helpers(self):
        udd = f'{CACHE}/k1hy9lkt_i7i7fd'
        ps = '\n'.join([main_line(24480, udd), helper_line(26121, udd), '90420 /Applications/AdsPower Global.app'])
        self.assertEqual(app.find_instances(ps), [app.Instance(24480, udd)])

    def test_user_data_dir_with_spaces_is_kept_whole(self):
        udd = f'{CACHE}/k1hy9lkt_i7i7fd'
        [instance] = app.find_instances(main_line(1, udd))
        self.assertEqual(instance.user_data_dir, udd)
        self.assertEqual(instance.profile, 'k1hy9lkt')

    def test_user_data_dir_as_last_argument(self):
        line = f'7 {APP}/Contents/MacOS/SunBrowser --no-first-run --user-data-dir={CACHE}/abc_x'
        self.assertEqual(app.find_instances(line), [app.Instance(7, f'{CACHE}/abc_x')])

    def test_no_sunbrowser_running(self):
        ps = '1 /sbin/launchd\n2843 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        self.assertEqual(app.find_instances(ps), [])


class ResolveWsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_single_instance_gives_ws_url_from_devtools_active_port(self):
        udd = make_profile(self.tmp.name, 'k1hy9lkt_i7i7fd', 60468, '/devtools/browser/abc-123')
        ws = app.resolve_ws([app.Instance(1, udd)])
        self.assertEqual(ws, 'ws://127.0.0.1:60468/devtools/browser/abc-123')

    def test_not_running_tells_user_to_open_adspower(self):
        with self.assertRaisesRegex(app.SunBrowserError, 'not running.*AdsPower'):
            app.resolve_ws([])

    def test_several_instances_need_a_profile_choice(self):
        a = make_profile(self.tmp.name, 'k1hy9lkt_i7i7fd', 1001)
        b = make_profile(self.tmp.name, 'k1i7l6fc_i7i7fd', 1002)
        with self.assertRaisesRegex(app.SunBrowserError, r'SUNBROWSER_PROFILE.*k1hy9lkt.*k1i7l6fc'):
            app.resolve_ws([app.Instance(1, a), app.Instance(2, b)])

    def test_profile_choice_picks_the_matching_instance(self):
        a = make_profile(self.tmp.name, 'k1hy9lkt_i7i7fd', 1001)
        b = make_profile(self.tmp.name, 'k1i7l6fc_i7i7fd', 1002)
        ws = app.resolve_ws([app.Instance(1, a), app.Instance(2, b)], profile='k1i7l6fc')
        self.assertTrue(ws.startswith('ws://127.0.0.1:1002/'))

    def test_unknown_profile_choice(self):
        a = make_profile(self.tmp.name, 'k1hy9lkt_i7i7fd')
        with self.assertRaisesRegex(app.SunBrowserError, 'nope'):
            app.resolve_ws([app.Instance(1, a)], profile='nope')

    def test_missing_devtools_active_port(self):
        udd = Path(self.tmp.name) / 'k1hy9lkt_i7i7fd'
        udd.mkdir()
        with self.assertRaisesRegex(app.SunBrowserError, 'DevToolsActivePort'):
            app.resolve_ws([app.Instance(1, str(udd))])


class PlanCommandsTest(unittest.TestCase):
    WS = 'ws://127.0.0.1:60468/devtools/browser/abc'

    def test_attaches_with_pinned_tab_and_own_session(self):
        [argv] = app.plan_commands(['open', 'https://claude.ai/new'], self.WS, env={})
        self.assertEqual(
            argv,
            [
                'agent-browser',
                '--cdp',
                self.WS,
                '--pin-tab',
                '--session',
                'sunbrowser',
                'open',
                'https://claude.ai/new',
            ],
        )

    def test_explicit_session_is_kept(self):
        [argv] = app.plan_commands(['--session', 'task1', 'snapshot'], self.WS, env={})
        self.assertNotIn('sunbrowser', argv)
        self.assertEqual(argv[-3:], ['--session', 'task1', 'snapshot'])

    def test_session_from_env_is_kept(self):
        [argv] = app.plan_commands(['snapshot'], self.WS, env={'AGENT_BROWSER_SESSION': 'task2'})
        self.assertNotIn('--session', argv)

    def test_close_closes_the_session_tab_first(self):
        tab_close, close = app.plan_commands(['--session', 't', 'close'], self.WS, env={})
        self.assertEqual(tab_close[-2:], ['tab', 'close'])
        self.assertEqual(close[-1], 'close')

    def test_tab_close_is_not_doubled(self):
        commands = app.plan_commands(['tab', 'close'], self.WS, env={})
        self.assertEqual(len(commands), 1)

    def test_close_all_passes_through(self):
        commands = app.plan_commands(['close', '--all'], self.WS, env={})
        self.assertEqual(len(commands), 1)


class HookTest(unittest.TestCase):
    def test_denies_plain_agent_browser_on_claude_ai(self):
        reason = app.hook_reason(bash_event('agent-browser open https://claude.ai/new'))
        self.assertIn('sunbrowser.py', reason)

    def test_denies_npx_and_flags_before_the_url(self):
        reason = app.hook_reason(
            bash_event('npx agent-browser --session x open claude.ai/code && agent-browser snapshot')
        )
        self.assertIsNotNone(reason)

    def test_allows_sunbrowser(self):
        self.assertIsNone(app.hook_reason(bash_event('sunbrowser.py open https://claude.ai/artifact/abc')))

    def test_allows_agent_browser_attached_through_sunbrowser(self):
        command = 'agent-browser --cdp "$(sunbrowser.py --ws)" --pin-tab open https://claude.ai'
        self.assertIsNone(app.hook_reason(bash_event(command)))

    def test_allows_other_sites(self):
        self.assertIsNone(app.hook_reason(bash_event('agent-browser open http://localhost:3000')))

    def test_allows_non_browser_commands_mentioning_claude_ai(self):
        self.assertIsNone(app.hook_reason(bash_event('curl -sI https://claude.ai')))

    def test_ignores_other_tools(self):
        event = {'tool_name': 'WebFetch', 'tool_input': {'url': 'https://claude.ai'}}
        self.assertIsNone(app.hook_reason(event))


class HookCliTest(unittest.TestCase):
    def run_hook(self, stdin):
        return subprocess.run(
            [sys.executable, str(SCRIPT), '--hook'], input=stdin, capture_output=True, text=True, timeout=10
        )

    def test_deny_is_reported_as_pretooluse_json(self):
        result = self.run_hook(json.dumps(bash_event('agent-browser open https://claude.ai')))
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(output['hookEventName'], 'PreToolUse')
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertIn('sunbrowser.py', output['permissionDecisionReason'])

    def test_allow_prints_nothing(self):
        result = self.run_hook(json.dumps(bash_event('ls -la')))
        self.assertEqual((result.returncode, result.stdout), (0, ''))

    def test_malformed_input_never_blocks(self):
        result = self.run_hook('not json')
        self.assertEqual((result.returncode, result.stdout), (0, ''))


if __name__ == '__main__':
    unittest.main()

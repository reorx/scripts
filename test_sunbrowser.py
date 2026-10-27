#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Behavior tests: uv run test_sunbrowser.py."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

SPEC = importlib.util.spec_from_file_location('sunbrowser', Path(__file__).with_name('sunbrowser.py'))
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


def make_profile(root, name, port=60468):
    udd = Path(root) / name
    udd.mkdir()
    (udd / 'DevToolsActivePort').write_text(f'{port}\n/devtools/browser/abc-123')
    return str(udd)


class FakeDevTools(BaseHTTPRequestHandler):
    """Answers the two DevTools HTTP endpoints sunbrowser.py uses, recording each request."""

    requests = []

    def do_PUT(self):
        self.requests.append(('PUT', self.path))
        self.reply(200, json.dumps({'id': f'TARGET{len(self.requests)}', 'type': 'page'}))

    def do_GET(self):
        self.requests.append(('GET', self.path))
        self.reply(200, 'Target activated')

    def reply(self, status, body):
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


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


class PickInstanceTest(unittest.TestCase):
    A = app.Instance(1, f'{CACHE}/k1hy9lkt_i7i7fd')
    B = app.Instance(2, f'{CACHE}/k1i7l6fc_i7i7fd')

    def test_single_instance(self):
        self.assertEqual(app.pick_instance([self.A]), self.A)

    def test_not_running_tells_user_to_open_adspower(self):
        with self.assertRaisesRegex(app.SunBrowserError, 'not running.*AdsPower'):
            app.pick_instance([])

    def test_several_instances_need_a_profile_choice(self):
        with self.assertRaisesRegex(app.SunBrowserError, r'SUN_BROWSER_PROFILE.*k1hy9lkt.*k1i7l6fc'):
            app.pick_instance([self.A, self.B])

    def test_profile_choice_picks_the_matching_instance(self):
        self.assertEqual(app.pick_instance([self.A, self.B], profile='k1i7l6fc'), self.B)

    def test_unknown_profile_choice(self):
        with self.assertRaisesRegex(app.SunBrowserError, 'nope'):
            app.pick_instance([self.A], profile='nope')


class DevtoolsPortTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_port_comes_from_devtools_active_port(self):
        udd = make_profile(self.tmp.name, 'k1hy9lkt_i7i7fd', 60468)
        self.assertEqual(app.devtools_port(app.Instance(1, udd)), 60468)

    def test_missing_devtools_active_port(self):
        udd = Path(self.tmp.name) / 'k1hy9lkt_i7i7fd'
        udd.mkdir()
        with self.assertRaisesRegex(app.SunBrowserError, 'DevToolsActivePort'):
            app.devtools_port(app.Instance(1, str(udd)))


class DomainsTest(unittest.TestCase):
    def test_default_is_claude_ai_and_claude_com(self):
        self.assertEqual(app.parse_domains(None), ['claude.ai', 'claude.com'])

    def test_env_value_is_trimmed_and_lowercased(self):
        self.assertEqual(app.parse_domains(' Claude.AI, .example.org ,,'), ['claude.ai', 'example.org'])

    def test_domain_and_its_subdomains_match(self):
        domains = ['claude.ai', 'claude.com']
        for url in [
            'https://claude.ai/code/artifact/abc',
            'https://claude.com/cai/oauth/authorize?client_id=x&state=y',
            'https://platform.claude.com/oauth/authorize',
            'https://CLAUDE.AI:443/new',
        ]:
            with self.subTest(url=url):
                self.assertTrue(app.matches(url, domains))

    def test_lookalikes_and_other_urls_do_not_match(self):
        domains = ['claude.ai', 'claude.com']
        for url in [
            'https://evilclaude.ai/',
            'https://claude.ai.example.com/',
            'https://example.com/?next=https://claude.ai',
            'http://localhost:3000',
            'mailto:support@claude.com',
            'file:///tmp/claude.ai.html',
        ]:
            with self.subTest(url=url):
                self.assertFalse(app.matches(url, domains))


class OpenInSunBrowserTest(unittest.TestCase):
    def setUp(self):
        FakeDevTools.requests = []
        self.server = HTTPServer(('127.0.0.1', 0), FakeDevTools)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_opens_a_new_tab_and_selects_it(self):
        url = 'https://claude.com/cai/oauth/authorize?client_id=x&state=y#frag'
        app.open_in_sun_browser(self.server.server_port, url)
        (method, new_path), activate = FakeDevTools.requests
        self.assertEqual(method, 'PUT')
        split = urlsplit(new_path)
        self.assertEqual(split.path, '/json/new')
        self.assertEqual(unquote(split.query), url)
        self.assertEqual(activate, ('GET', '/json/activate/TARGET1'))

    def test_opens_every_url_then_brings_that_process_to_front(self):
        udd = make_profile(self.tmp.name, 'k1hy9lkt_i7i7fd', self.server.server_port)
        with (
            patch.object(app, 'current_instance', return_value=app.Instance(24480, udd)),
            patch.object(app, 'bring_to_front') as bring_to_front,
        ):
            app.open_all_in_sun_browser(['https://claude.ai/a', 'https://claude.ai/b'])
        opened = [unquote(urlsplit(path).query) for method, path in FakeDevTools.requests if method == 'PUT']
        self.assertEqual(opened, ['https://claude.ai/a', 'https://claude.ai/b'])
        bring_to_front.assert_called_once_with(24480)


class MainTest(unittest.TestCase):
    def run_main(self, argv, env=None, sun_error=None):
        stderr = io.StringIO()
        with (
            patch.dict(app.os.environ, env or {}, clear=False),
            patch.object(app, 'open_all_in_sun_browser', side_effect=sun_error) as sun,
            patch.object(app.subprocess, 'run', return_value=app.subprocess.CompletedProcess([], 0)) as run,
            contextlib.redirect_stderr(stderr),
        ):
            code = app.main(argv)
        return code, sun, run, stderr.getvalue()

    def test_claude_url_goes_to_sun_browser(self):
        code, sun, run, _ = self.run_main(['https://claude.ai/new'])
        self.assertEqual(code, 0)
        sun.assert_called_once_with(['https://claude.ai/new'])
        run.assert_not_called()

    def test_other_url_goes_to_open_without_touching_sun_browser(self):
        code, sun, run, _ = self.run_main(['https://example.com/'])
        self.assertEqual(code, 0)
        run.assert_called_once_with(['open', 'https://example.com/'])
        sun.assert_not_called()

    def test_domains_come_from_env(self):
        _, sun, run, _ = self.run_main(
            ['https://claude.ai/new', 'https://example.com/'], env={'SUN_BROWSER_DOMAINS': 'example.com'}
        )
        sun.assert_called_once_with(['https://example.com/'])
        run.assert_called_once_with(['open', 'https://claude.ai/new'])

    def test_sun_browser_not_running_fails_without_falling_back(self):
        code, _, run, stderr = self.run_main(
            ['https://claude.ai/new'], sun_error=app.SunBrowserError('Sun Browser is not running.')
        )
        self.assertEqual(code, 1)
        self.assertIn('not running', stderr)
        run.assert_not_called()

    def test_unreachable_devtools_port_is_reported(self):
        code, _, _, stderr = self.run_main(['https://claude.ai/new'], sun_error=ConnectionRefusedError('refused'))
        self.assertEqual(code, 1)
        self.assertIn('refused', stderr)

    def test_options_are_never_passed_to_open(self):
        code, sun, run, _ = self.run_main(['--hook'])
        self.assertEqual(code, 2)
        run.assert_not_called()
        sun.assert_not_called()

    def test_no_arguments_prints_usage(self):
        code, _, _, stderr = self.run_main([])
        self.assertEqual(code, 2)
        self.assertIn('Usage', stderr)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Behavior tests: uv run test_open_browser.py."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

SPEC = importlib.util.spec_from_file_location('open_browser', Path(__file__).with_name('open-browser.py'))
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)

ENV_KEYS = ('OPEN_BROWSER_TARGET', 'OPEN_BROWSER_PROFILE', 'OPEN_BROWSER_DOMAINS', 'STICKYFINGERS_HOME')


@contextlib.contextmanager
def environment(env=None):
    with patch.dict(app.os.environ):
        for key in ENV_KEYS:
            app.os.environ.pop(key, None)
        app.os.environ.update(env or {})
        yield


# --- StickyFingers ---------------------------------------------------------------------------

HOST = 'Genji.local'
ID_A = '7D770CB0-2320-4925-B23D-A16FDDA407C9'
ID_B = 'A21619C4-5F9B-49AF-878A-E10D38D6A3F1'


def make_sf_profile(root, profile_id, name, lock=None, socket_path=None):
    """A StickyFingers profile dir as the app leaves it: profile.json, user-data, Chromium's singleton links."""
    directory = Path(root) / 'profiles' / profile_id
    udd = directory / 'user-data'
    udd.mkdir(parents=True)
    (directory / 'profile.json').write_text(
        json.dumps({'schemaVersion': 1, 'id': profile_id, 'name': name, 'proxy': {'password': 'secret'}})
    )
    if lock:
        os.symlink(lock, udd / 'SingletonLock')
    if socket_path:
        os.symlink(socket_path, udd / 'SingletonSocket')
    return udd


class FakeSingleton:
    """A Chromium ProcessSingleton listener: reads one message until EOF, answers with `reply`."""

    def __init__(self, reply=b'ACK'):
        self.reply = reply
        self.messages = []
        # macOS caps AF_UNIX paths at 104 bytes, Chromium also keeps its socket in a short temp dir
        self.dir = tempfile.mkdtemp(prefix='ob', dir='/tmp')
        self.path = os.path.join(self.dir, 'SingletonSocket')
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = b''
                while chunk := conn.recv(4096):
                    data += chunk
                self.messages.append(data)
                conn.sendall(self.reply)

    def close(self):
        self.server.close()
        shutil.rmtree(self.dir)


class StickyFingersRootTest(unittest.TestCase):
    def test_default_root_is_application_support(self):
        with environment():
            self.assertEqual(app.stickyfingers_root(), Path.home() / 'Library/Application Support/StickyFingers')

    def test_stickyfingers_home_overrides_the_root(self):
        with environment({'STICKYFINGERS_HOME': '~/tmp/sf-dev'}):
            self.assertEqual(app.stickyfingers_root(), Path.home() / 'tmp/sf-dev')


class FindProfilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def find(self, live_pids):
        return {p.name: p for p in app.find_profiles(self.root, HOST, live_pids)}

    def test_running_profile_has_the_pid_from_its_singleton_lock(self):
        udd = make_sf_profile(self.root, ID_A, 'i@example.com', lock=f'{HOST}-4242')
        make_sf_profile(self.root, ID_B, 'test')
        profiles = self.find({1, 4242})
        self.assertEqual(profiles['i@example.com'], app.Profile(ID_A, 'i@example.com', udd, 4242))
        self.assertIsNone(profiles['test'].pid)

    def test_lock_of_a_dead_process_is_not_running(self):
        make_sf_profile(self.root, ID_A, 'crashed', lock=f'{HOST}-4242')
        self.assertIsNone(self.find({1})['crashed'].pid)

    def test_lock_from_another_host_is_not_running(self):
        make_sf_profile(self.root, ID_A, 'synced', lock='Other-Mac.local-4242')
        self.assertIsNone(self.find({4242})['synced'].pid)

    def test_host_names_with_dashes_keep_their_pid(self):
        make_sf_profile(self.root, ID_A, 'p', lock='my-mac-mini.local-77')
        [profile] = app.find_profiles(self.root, 'my-mac-mini.local', {77})
        self.assertEqual(profile.pid, 77)

    def test_sync_staging_dirs_and_dirs_without_profile_json_are_skipped(self):
        make_sf_profile(self.root, ID_A, 'real')
        (self.root / 'profiles' / f'.sync-new-{ID_B}').mkdir()
        (self.root / 'profiles' / 'stray').mkdir()
        self.assertEqual(list(self.find(set())), ['real'])

    def test_no_profiles_dir(self):
        self.assertEqual(app.find_profiles(self.root, HOST, set()), [])


class PickProfileTest(unittest.TestCase):
    A = app.Profile(ID_A, 'i@example.com', Path('/sf/a/user-data'), 11)
    B = app.Profile(ID_B, 'Work', Path('/sf/b/user-data'), 22)
    IDLE = app.Profile('C0FFEE00-0000-0000-0000-000000000000', 'idle', Path('/sf/c/user-data'), None)

    def test_the_only_running_profile_is_used(self):
        self.assertEqual(app.pick_profile([self.A, self.IDLE]), self.A)

    def test_nothing_running_tells_user_to_open_stickyfingers(self):
        with self.assertRaisesRegex(app.BrowserError, 'No StickyFingers profile is running.*StickyFingers'):
            app.pick_profile([self.IDLE])

    def test_several_running_need_a_profile_choice(self):
        with self.assertRaisesRegex(app.BrowserError, r'OPEN_BROWSER_PROFILE.*i@example\.com.*Work'):
            app.pick_profile([self.A, self.B, self.IDLE])

    def test_choice_by_name_ignores_case(self):
        self.assertEqual(app.pick_profile([self.A, self.B], 'work'), self.B)

    def test_choice_by_id_prefix(self):
        self.assertEqual(app.pick_profile([self.A, self.B], 'a21619c4'), self.B)

    def test_chosen_profile_not_running_does_not_fall_back_to_another(self):
        with self.assertRaisesRegex(app.BrowserError, "'idle' is not running"):
            app.pick_profile([self.A, self.IDLE], 'idle')

    def test_unknown_choice_lists_the_profiles(self):
        with self.assertRaisesRegex(app.BrowserError, r'nope.*i@example\.com.*Work.*idle'):
            app.pick_profile([self.A, self.B, self.IDLE], 'nope')

    def test_ambiguous_choice(self):
        twin = app.Profile(ID_B, 'Work', Path('/sf/d/user-data'), None)
        with self.assertRaisesRegex(app.BrowserError, 'matches several'):
            app.pick_profile([self.B, twin], 'work')


class SingletonSocketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def serve(self, reply=b'ACK'):
        singleton = FakeSingleton(reply)
        self.addCleanup(singleton.close)
        udd = make_sf_profile(self.tmp.name, ID_A, 'p', lock=f'{HOST}-1', socket_path=singleton.path)
        return singleton, udd

    def test_url_is_handed_over_as_a_chromium_command_line(self):
        singleton, udd = self.serve()
        url = 'https://claude.com/cai/oauth/authorize?client_id=x&state=y#frag'
        app.send_to_singleton(udd, url)
        self.assertEqual(singleton.messages, [b'START\0/\0open-browser\0' + url.encode()])

    def test_reply_other_than_ack_is_an_error(self):
        _, udd = self.serve(reply=b'SHUTDOWN')
        with self.assertRaisesRegex(app.BrowserError, 'SHUTDOWN'):
            app.send_to_singleton(udd, 'https://claude.ai/new')

    def test_no_listener_raises(self):
        udd = make_sf_profile(self.tmp.name, ID_B, 'gone', socket_path='/tmp/ob-missing/SingletonSocket')
        with self.assertRaises(OSError):
            app.send_to_singleton(udd, 'https://claude.ai/new')

    def test_opens_every_url_then_brings_that_process_to_front(self):
        singleton, udd = self.serve()
        profile = app.Profile(ID_A, 'p', udd, 4242)
        with (
            patch.object(app, 'current_profile', return_value=profile) as current,
            patch.object(app, 'bring_to_front') as bring_to_front,
        ):
            app.open_all_in_stickyfingers(['https://claude.ai/a', 'https://claude.ai/b'], 'p')
        current.assert_called_once_with('p')
        self.assertEqual(
            [m.split(b'\0')[-1] for m in singleton.messages], [b'https://claude.ai/a', b'https://claude.ai/b']
        )
        bring_to_front.assert_called_once_with(4242)


# --- Sun Browser -----------------------------------------------------------------------------

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


def make_sun_profile(root, name, port=60468):
    udd = Path(root) / name
    udd.mkdir()
    (udd / 'DevToolsActivePort').write_text(f'{port}\n/devtools/browser/abc-123')
    return str(udd)


class FakeDevTools(BaseHTTPRequestHandler):
    """Answers the two DevTools HTTP endpoints the Sun Browser target uses, recording each request."""

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
        with self.assertRaisesRegex(app.BrowserError, 'not running.*AdsPower'):
            app.pick_instance([])

    def test_several_instances_need_a_profile_choice(self):
        with self.assertRaisesRegex(app.BrowserError, r'OPEN_BROWSER_PROFILE.*k1hy9lkt.*k1i7l6fc'):
            app.pick_instance([self.A, self.B])

    def test_profile_choice_picks_the_matching_instance(self):
        self.assertEqual(app.pick_instance([self.A, self.B], profile='k1i7l6fc'), self.B)

    def test_unknown_profile_choice(self):
        with self.assertRaisesRegex(app.BrowserError, 'nope'):
            app.pick_instance([self.A], profile='nope')


class DevtoolsPortTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_port_comes_from_devtools_active_port(self):
        udd = make_sun_profile(self.tmp.name, 'k1hy9lkt_i7i7fd', 60468)
        self.assertEqual(app.devtools_port(app.Instance(1, udd)), 60468)

    def test_missing_devtools_active_port(self):
        udd = Path(self.tmp.name) / 'k1hy9lkt_i7i7fd'
        udd.mkdir()
        with self.assertRaisesRegex(app.BrowserError, 'DevToolsActivePort'):
            app.devtools_port(app.Instance(1, str(udd)))


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
        udd = make_sun_profile(self.tmp.name, 'k1hy9lkt_i7i7fd', self.server.server_port)
        with (
            patch.object(app, 'current_instance', return_value=app.Instance(24480, udd)) as current,
            patch.object(app, 'bring_to_front') as bring_to_front,
        ):
            app.open_all_in_sun_browser(['https://claude.ai/a', 'https://claude.ai/b'], 'k1hy9lkt')
        current.assert_called_once_with('k1hy9lkt')
        opened = [unquote(urlsplit(path).query) for method, path in FakeDevTools.requests if method == 'PUT']
        self.assertEqual(opened, ['https://claude.ai/a', 'https://claude.ai/b'])
        bring_to_front.assert_called_once_with(24480)


# --- Routing ---------------------------------------------------------------------------------


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


class MainTest(unittest.TestCase):
    def run_main(self, argv, env=None, error=None):
        stderr = io.StringIO()
        with (
            environment(env),
            patch.object(app, 'open_all_in_stickyfingers', side_effect=error) as sticky,
            patch.object(app, 'open_all_in_sun_browser', side_effect=error) as sun,
            patch.object(app.subprocess, 'run', return_value=app.subprocess.CompletedProcess([], 0)) as run,
            contextlib.redirect_stderr(stderr),
        ):
            code = app.main(argv)
        return code, sticky, sun, run, stderr.getvalue()

    def test_claude_url_goes_to_stickyfingers_by_default(self):
        code, sticky, sun, run, _ = self.run_main(['https://claude.ai/new'])
        self.assertEqual(code, 0)
        sticky.assert_called_once_with(['https://claude.ai/new'], None)
        sun.assert_not_called()
        run.assert_not_called()

    def test_profile_choice_is_passed_to_the_target(self):
        _, sticky, _, _, _ = self.run_main(['https://claude.ai/new'], env={'OPEN_BROWSER_PROFILE': 'Work'})
        sticky.assert_called_once_with(['https://claude.ai/new'], 'Work')

    def test_target_sunbrowser(self):
        env = {'OPEN_BROWSER_TARGET': 'sunbrowser', 'OPEN_BROWSER_PROFILE': 'k1hy9lkt'}
        code, sticky, sun, _, _ = self.run_main(['https://claude.ai/new'], env=env)
        self.assertEqual(code, 0)
        sun.assert_called_once_with(['https://claude.ai/new'], 'k1hy9lkt')
        sticky.assert_not_called()

    def test_target_name_is_case_insensitive(self):
        _, sticky, _, _, _ = self.run_main(['https://claude.ai/new'], env={'OPEN_BROWSER_TARGET': ' StickyFingers '})
        sticky.assert_called_once()

    def test_unknown_target_fails_but_other_urls_still_open(self):
        code, sticky, sun, run, stderr = self.run_main(
            ['https://claude.ai/new', 'https://example.com/'], env={'OPEN_BROWSER_TARGET': 'chrome'}
        )
        self.assertEqual(code, 1)
        self.assertIn('OPEN_BROWSER_TARGET', stderr)
        sticky.assert_not_called()
        sun.assert_not_called()
        run.assert_called_once_with(['open', 'https://example.com/'])

    def test_other_url_goes_to_open_without_touching_any_target(self):
        code, sticky, sun, run, _ = self.run_main(['https://example.com/'])
        self.assertEqual(code, 0)
        run.assert_called_once_with(['open', 'https://example.com/'])
        sticky.assert_not_called()
        sun.assert_not_called()

    def test_domains_come_from_env(self):
        _, sticky, _, run, _ = self.run_main(
            ['https://claude.ai/new', 'https://example.com/'], env={'OPEN_BROWSER_DOMAINS': 'example.com'}
        )
        sticky.assert_called_once_with(['https://example.com/'], None)
        run.assert_called_once_with(['open', 'https://claude.ai/new'])

    def test_target_not_running_fails_without_falling_back(self):
        code, _, _, run, stderr = self.run_main(
            ['https://claude.ai/new'], error=app.BrowserError('No StickyFingers profile is running.')
        )
        self.assertEqual(code, 1)
        self.assertIn('open-browser: No StickyFingers profile is running', stderr)
        run.assert_not_called()

    def test_unreachable_browser_is_reported(self):
        code, _, _, _, stderr = self.run_main(['https://claude.ai/new'], error=ConnectionRefusedError('refused'))
        self.assertEqual(code, 1)
        self.assertIn('refused', stderr)

    def test_options_are_never_passed_to_open(self):
        code, sticky, _, run, _ = self.run_main(['--hook'])
        self.assertEqual(code, 2)
        run.assert_not_called()
        sticky.assert_not_called()

    def test_no_arguments_prints_usage(self):
        code, _, _, _, stderr = self.run_main([])
        self.assertEqual(code, 2)
        self.assertIn('Usage', stderr)


if __name__ == '__main__':
    unittest.main()

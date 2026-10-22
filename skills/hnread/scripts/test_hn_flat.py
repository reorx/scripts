#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Behavior tests: uv run test_hn_flat.py

Runs hn_flat.py as a CLI against a local server that serves an HN-shaped item page,
so both fetchers (real curl and requests) are exercised without touching HN.
"""

import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).with_name('hn_flat.py')

ITEM_HTML = """<html><body><center><table id="hnmain">
<tr><td><table class="fatitem">
<tr class="athing submission" id="100"><td class="title"><span class="titleline">
<a href="https://example.com/post">Example post</a></span></td></tr>
</table></td></tr>
<tr><td><table class="comment-tree">
<tr class="athing comtr" id="101"><td><table><tr>
<td class="ind" indent="0"><img src="s.gif" height="1" width="0"></td>
<td class="default"><div><span class="comhead"><a href="user?id=alice" class="hnuser">alice</a></span></div>
<div class="comment"><div class="commtext c00">Top level point</div></div></td>
</tr></table></td></tr>
<tr class="athing comtr" id="102"><td><table><tr>
<td class="ind" indent="1"><img src="s.gif" height="1" width="40"></td>
<td class="default"><div><span class="comhead"><a href="user?id=bob" class="hnuser">bob</a></span></div>
<div class="comment"><div class="commtext c00">A reply</div></div></td>
</tr></table></td></tr>
</table></td></tr>
</table></center></body></html>"""


class FakeHN(BaseHTTPRequestHandler):
    status = 200
    seen_user_agents: list[str] = []

    def do_GET(self):
        FakeHN.seen_user_agents.append(self.headers.get('User-Agent', ''))
        body = (ITEM_HTML if self.status == 200 else 'Sorry').encode()
        self.send_response(self.status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HNFlatCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FakeHN)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/item?id=100'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeHN.status = 200
        FakeHN.seen_user_agents = []

    def run_script(self, *args):
        env = {**os.environ, 'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'}
        return subprocess.run(
            ['uv', 'run', '--quiet', '--script', str(SCRIPT), self.url, '--stdout', '--no-frontmatter', *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    def assert_rendered(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- @alice [+1]: Top level point', result.stdout)
        self.assertIn('  - @bob: A reply', result.stdout)

    def test_given_default_options_when_fetching_then_use_curl(self):
        result = self.run_script()
        self.assert_rendered(result)
        self.assertEqual(len(FakeHN.seen_user_agents), 1)
        self.assertTrue(FakeHN.seen_user_agents[0].startswith('curl/'), FakeHN.seen_user_agents)

    def test_given_requests_fetcher_when_fetching_then_do_not_pose_as_a_browser(self):
        # HN answers 419 when python-requests sends a browser User-Agent
        result = self.run_script('--fetcher', 'requests')
        self.assert_rendered(result)
        self.assertEqual(len(FakeHN.seen_user_agents), 1)
        self.assertNotIn('Mozilla', FakeHN.seen_user_agents[0])

    def test_given_hn_refuses_when_fetching_then_fail_with_status_and_hint_without_caching(self):
        FakeHN.status = 419
        for fetcher in ('curl', 'requests'):
            with self.subTest(fetcher=fetcher), tempfile.TemporaryDirectory() as cache_dir:
                result = self.run_script('--fetcher', fetcher, '--cache-dir', cache_dir)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('419', result.stderr)
                self.assertIn('--fetcher', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(list(Path(cache_dir).iterdir()), [])

    def test_given_cached_page_when_fetching_again_then_skip_the_network(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            self.assert_rendered(self.run_script('--cache-dir', cache_dir))
            self.assert_rendered(self.run_script('--cache-dir', cache_dir))
        self.assertEqual(len(FakeHN.seen_user_agents), 1)


if __name__ == '__main__':
    unittest.main()

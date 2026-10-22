#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Behavior tests: uv run test_hn_flat.py

Runs hn_flat.py as a CLI against a local server that plays HN (item page), the Algolia
HN API and the official Firebase API, so every fetcher (real curl, requests, Algolia)
and the fallback between them are exercised without touching the real services.
"""

import json
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


def algolia_node(node_id, author, text, children=()):
    return {'id': node_id, 'type': 'comment', 'author': author, 'text': text, 'children': list(children)}


# Algolia lists comments by id; carol's comment was deleted but still has a reply
ALGOLIA_ITEM = {
    'id': 100,
    'type': 'story',
    'title': 'Example post',
    'url': 'https://example.com/post',
    'author': 'op',
    'text': None,
    'children': [
        algolia_node(101, 'alice', 'Top level point', [algolia_node(102, 'bob', 'A reply')]),
        algolia_node(103, None, None, [algolia_node(104, 'dave', 'Orphan reply')]),
        algolia_node(105, 'erin', 'First <i>para</i> &amp; more<p>Second para'),
    ],
}
# HN's ranking of the top-level comments; 106 is a dead comment Algolia leaves out
FIREBASE_ITEM = {'id': 100, 'type': 'story', 'kids': [105, 106, 103, 101]}


class FakeHN(BaseHTTPRequestHandler):
    html_status = 200
    html_body = ITEM_HTML
    refuse_curl = False
    algolia_status = 200
    firebase_status = 200
    requests_seen: list[tuple[str, str]] = []

    def do_GET(self):
        user_agent = self.headers.get('User-Agent', '')
        FakeHN.requests_seen.append((self.path, user_agent))
        if self.path.startswith('/api/v1/items/100'):
            self.reply(self.algolia_status, json.dumps(ALGOLIA_ITEM), 'application/json')
        elif self.path.startswith('/v0/item/100.json'):
            self.reply(self.firebase_status, json.dumps(FIREBASE_ITEM), 'application/json')
        elif self.refuse_curl and user_agent.startswith('curl/'):
            self.reply(419, 'Sorry', 'text/html')
        else:
            self.reply(self.html_status, self.html_body if self.html_status == 200 else 'Sorry', 'text/html')

    def reply(self, status, text, content_type):
        body = text.encode()
        self.send_response(status)
        self.send_header('Content-Type', f'{content_type}; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def paths_seen():
    return [path for path, _ in FakeHN.requests_seen]


def api_requests():
    return [path for path in paths_seen() if not path.startswith('/item')]


class HNFlatCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FakeHN)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.url = f'{base}/item?id=100'
        cls.env = {
            **os.environ,
            'NO_PROXY': '127.0.0.1,localhost',
            'no_proxy': '127.0.0.1,localhost',
            'HNREAD_ALGOLIA_ITEM_URL': f'{base}/api/v1/items/{{id}}',
            'HNREAD_FIREBASE_ITEM_URL': f'{base}/v0/item/{{id}}.json',
        }

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeHN.html_status = 200
        FakeHN.html_body = ITEM_HTML
        FakeHN.refuse_curl = False
        FakeHN.algolia_status = 200
        FakeHN.firebase_status = 200
        FakeHN.requests_seen = []

    def run_script(self, *args):
        return subprocess.run(
            ['uv', 'run', '--quiet', '--script', str(SCRIPT), self.url, '--stdout', '--no-frontmatter', *args],
            capture_output=True,
            text=True,
            env=self.env,
            timeout=120,
        )

    def assert_rendered_html(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- @alice [+1]: Top level point', result.stdout)
        self.assertIn('  - @bob: A reply', result.stdout)

    def assert_rendered_algolia(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn('- @alice [+1]: Top level point', out)
        self.assertIn('  - @bob: A reply', out)
        # replies to a deleted comment move up to its place instead of disappearing
        self.assertIn('\n- @dave: Orphan reply', '\n' + out)
        self.assertIn('- @erin: First para & more\n\n  Second para', out)
        self.assertNotIn('None', out)
        self.assertNotIn('<i>', out)

    def assert_order(self, text, *needles):
        positions = [text.index(needle) for needle in needles]
        self.assertEqual(positions, sorted(positions), f'expected order {needles} in:\n{text}')


class FetcherBehavior(HNFlatCLI):
    def test_given_default_options_when_hn_answers_then_use_only_curl(self):
        result = self.run_script()
        self.assert_rendered_html(result)
        self.assertEqual(len(FakeHN.requests_seen), 1)
        self.assertTrue(FakeHN.requests_seen[0][1].startswith('curl/'), FakeHN.requests_seen)

    def test_given_requests_fetcher_when_fetching_then_do_not_pose_as_a_browser(self):
        # HN answers 419 when python-requests sends a browser User-Agent
        result = self.run_script('--fetcher', 'requests')
        self.assert_rendered_html(result)
        self.assertEqual(len(FakeHN.requests_seen), 1)
        self.assertNotIn('Mozilla', FakeHN.requests_seen[0][1])

    def test_given_algolia_fetcher_when_fetching_then_rank_top_level_comments_like_hn(self):
        result = self.run_script('--fetcher', 'algolia')
        self.assert_rendered_algolia(result)
        self.assert_order(result.stdout, '@erin', '@dave', '@alice')
        self.assertIn('chronological', result.stderr)
        self.assertEqual([p for p in paths_seen() if p.startswith('/item')], [])

    def test_given_firebase_down_when_using_algolia_then_keep_chronological_order(self):
        FakeHN.firebase_status = 500
        result = self.run_script('--fetcher', 'algolia')
        self.assert_rendered_algolia(result)
        self.assert_order(result.stdout, '@alice', '@dave', '@erin')


class FallbackBehavior(HNFlatCLI):
    def test_given_hn_refuses_curl_when_auto_then_fall_back_to_requests(self):
        FakeHN.refuse_curl = True
        result = self.run_script()
        self.assert_rendered_html(result)
        self.assertIn('419', result.stderr)
        self.assertEqual(paths_seen(), ['/item?id=100', '/item?id=100'])

    def test_given_hn_refuses_every_client_when_auto_then_fall_back_to_algolia(self):
        FakeHN.html_status = 419
        result = self.run_script()
        self.assert_rendered_algolia(result)
        self.assertEqual(paths_seen()[:2], ['/item?id=100', '/item?id=100'])
        self.assertTrue(api_requests(), 'Algolia was never asked')

    def test_given_hn_answers_200_without_a_thread_when_auto_then_treat_it_as_a_failure(self):
        FakeHN.html_body = '<html><body>Sorry.</body></html>'
        result = self.run_script()
        self.assert_rendered_algolia(result)
        self.assertEqual(paths_seen()[:2], ['/item?id=100', '/item?id=100'])

    def test_given_explicit_fetcher_when_it_fails_then_do_not_fall_back(self):
        FakeHN.html_status = 419
        result = self.run_script('--fetcher', 'curl')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('419', result.stderr)
        self.assertIn('--fetcher auto', result.stderr)
        self.assertEqual(api_requests(), [])

    def test_given_every_fetcher_fails_when_auto_then_exit_with_hint_and_no_cache(self):
        FakeHN.html_status = 419
        FakeHN.algolia_status = 503
        with tempfile.TemporaryDirectory() as cache_dir:
            result = self.run_script('--cache-dir', cache_dir)
            self.assertEqual(result.returncode, 1, result.stderr)
            for name in ('curl', 'requests', 'algolia'):
                self.assertIn(f'{name} failed', result.stderr)
            self.assertIn('Wait a few minutes', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(list(Path(cache_dir).iterdir()), [])


class CacheBehavior(HNFlatCLI):
    def test_given_cached_page_when_fetching_again_then_skip_the_network(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            self.assert_rendered_html(self.run_script('--cache-dir', cache_dir))
            self.assert_rendered_html(self.run_script('--cache-dir', cache_dir))
        self.assertEqual(len(FakeHN.requests_seen), 1)

    def test_given_cached_algolia_thread_when_fetching_again_then_keep_ranking_without_network(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            first = self.run_script('--fetcher', 'algolia', '--cache-dir', cache_dir)
            seen = len(FakeHN.requests_seen)
            second = self.run_script('--cache-dir', cache_dir)
        self.assert_rendered_algolia(second)
        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual(len(FakeHN.requests_seen), seen)


if __name__ == '__main__':
    unittest.main()

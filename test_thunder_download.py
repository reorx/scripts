#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Behavior tests; real downloads use a temporary local HTTP server."""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).with_name('thunder-download.py')
spec = importlib.util.spec_from_file_location('thunder_download', SCRIPT)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def download_list(urls):
    return 'thunderx://' + json.dumps({'tasks': [{'url': url} for url in urls]})


class BehaviorTests(unittest.TestCase):
    def test_extracts_urls_and_removes_duplicates_in_order(self):
        urls = ['https://example.org/a', 'https://example.org/b']
        self.assertEqual(app.parse_tasks(download_list(urls + urls)), urls)

    def test_rejects_invalid_lists_before_downloading(self):
        for text in (
            '',
            'thunderx://{',
            'thunderx://[]',
            'thunderx://{}',
            'thunderx://{"tasks":[]}',
            'thunderx://{"tasks":[null]}',
            'thunderx://{"tasks":[{"url":123}]}',
            download_list(['file:///etc/passwd']),
            download_list(['https://example.org/a\n  dir=/tmp']),
            download_list(['https://']),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                app.parse_tasks(text)

    def test_default_destination_and_safe_aria2_settings(self):
        args = app.parse_args(['list.txt'])
        self.assertEqual(args.directory, Path.home() / 'Downloads')
        command = app.aria2_command('/bin/aria2c', args.directory)
        for option in (
            '--no-conf=true',
            '--max-concurrent-downloads=2',
            '--continue=true',
            '--auto-file-renaming=false',
            '--allow-overwrite=false',
            '--input-file=-',
        ):
            self.assertIn(option, command)
        self.assertEqual(app.parse_args(['list.txt', '-d', '/tmp/files']).directory, Path('/tmp/files'))

    @unittest.skipUnless(shutil.which('aria2c'), 'aria2c is not installed')
    def test_waits_for_all_downloads_limits_concurrency_and_reports_failure(self):
        state = {'active': 0, 'peak': 0}
        lock = threading.Lock()
        payload = b'local download verification\n' * 1024

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/missing':
                    self.send_error(404)
                    return
                with lock:
                    state['active'] += 1
                    state['peak'] = max(state['peak'], state['active'])
                try:
                    time.sleep(0.15)
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                finally:
                    with lock:
                        state['active'] -= 1

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'list.txt'
            destination = root / 'download dir'
            source.write_text(download_list([f'{base}/{i}.bin' for i in range(5)]))
            command = [sys.executable, str(SCRIPT), str(source), '-d', str(destination)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(state['peak'], 2)
            for i in range(5):
                self.assertEqual((destination / f'{i}.bin').read_bytes(), payload)
            # Re-running must not create numbered duplicate files.
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(list(destination.iterdir())), 5)
            source.write_text(download_list([f'{base}/missing', f'{base}/last.bin']))
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((destination / 'last.bin').read_bytes(), payload)


if __name__ == '__main__':
    unittest.main()

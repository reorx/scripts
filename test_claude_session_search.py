#!/usr/bin/env python3
"""Tests for claude_session_search.py: the order sessions are listed in.

Sessions are listed newest first prompt first. Ties (most often: several sessions that never got
a prompt) fall back to the most recently updated, then to the session ID, so the order never
depends on how the file system happens to list a directory. agent-session-manager's `asm` uses
the same order and is diffed against this script line by line.

Run: python3 test_claude_session_search.py
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('claude_session_search', HERE / 'claude_session_search.py')
css = importlib.util.module_from_spec(spec)
sys.modules['claude_session_search'] = css
spec.loader.exec_module(css)

PROJECT = '-Users-me-Code-alpha'
T0 = 1_790_000_000  # unix seconds


def write_transcript(projects: Path, sid: str, mtime: int, prompt: str | None = None, ts: str = '') -> None:
    """A transcript with one human prompt, or none at all (an empty session)."""
    path = projects / PROJECT / f'{sid}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [{'type': 'permission-mode', 'permissionMode': 'default', 'sessionId': sid}]
    if prompt is not None:
        records.append(
            {'type': 'user', 'message': {'role': 'user', 'content': prompt}, 'timestamp': ts, 'sessionId': sid}
        )
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))
    os.utime(path, (mtime, mtime))


class SessionOrderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.projects = root / 'projects'
        self.projects.mkdir()
        self.saved = (css.PROJECTS_DIR, css.HISTORY_FILE)
        css.PROJECTS_DIR = self.projects
        css.HISTORY_FILE = root / 'history.jsonl'  # missing: no history rows

    def tearDown(self):
        css.PROJECTS_DIR, css.HISTORY_FILE = self.saved
        self.tmp.cleanup()

    def listed_ids(self) -> list[str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            css.list_sessions(Namespace(list='alpha', days=0, limit=100, full=False))
        lines = re.sub(r'\x1b\[[0-9;]*m', '', out.getvalue()).splitlines()  # the script always colors
        return [line.split()[1] if line.startswith('?') else line.split()[2] for line in lines if 'prompts,' in line]

    def test_sessions_with_a_prompt_come_first_newest_prompt_first(self):
        write_transcript(self.projects, 'aaaa0001', T0, 'older', '2026-09-01T08:00:00.000Z')
        write_transcript(self.projects, 'aaaa0002', T0 - 100, 'newer', '2026-09-02T08:00:00.000Z')
        write_transcript(self.projects, 'aaaa0003', T0 + 100)
        self.assertEqual(self.listed_ids(), ['aaaa0002', 'aaaa0001', 'aaaa0003'])

    def test_sessions_without_a_prompt_are_ordered_by_last_update_newest_first(self):
        # names chosen so that name order and update order disagree
        write_transcript(self.projects, '543beb41', T0)
        write_transcript(self.projects, '8d22938d', T0 + 1320)
        write_transcript(self.projects, '11112222', T0 + 60)
        self.assertEqual(self.listed_ids(), ['8d22938d', '11112222', '543beb41'])

    def test_full_ties_fall_back_to_the_session_id(self):
        for sid in ['cccc0003', 'aaaa0001', 'bbbb0002']:
            write_transcript(self.projects, sid, T0)
        self.assertEqual(self.listed_ids(), ['aaaa0001', 'bbbb0002', 'cccc0003'])

    def test_lookup_by_id_prefix_uses_the_same_order(self):
        write_transcript(self.projects, 'dddd0001', T0)
        write_transcript(self.projects, 'dddd0002', T0 + 60)
        write_transcript(self.projects, 'dddd0003', T0 - 60, 'a prompt', '2026-09-01T08:00:00.000Z')
        found = [info.session_id for _, info in css.find_sessions('dddd')]
        self.assertEqual(found, ['dddd0003', 'dddd0002', 'dddd0001'])


if __name__ == '__main__':
    unittest.main()

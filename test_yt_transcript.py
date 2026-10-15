#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Behavior tests: uv run test_yt_transcript.py."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('yt_transcript', Path(__file__).with_name('yt-transcript.py'))
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


def make_info(language='en-US', manual=(), auto=()):
    formats = [{'ext': 'json3', 'url': 'https://example.invalid/timedtext'}]
    return {
        'id': 'z42ybkbKU0w',
        'title': 'A video',
        'language': language,
        'subtitles': {key: formats for key in manual},
        'automatic_captions': {key: formats for key in auto},
    }


def event(start_ms, *words, append=False):
    result = {'tStartMs': start_ms, 'dDurationMs': 2000, 'segs': [{'utf8': word} for word in words]}
    if append:
        result['aAppend'] = 1
    return result


class ChooseTrackBehavior(unittest.TestCase):
    def test_given_manual_subtitles_in_video_language_when_default_then_prefer_them_over_asr(self):
        info = make_info(manual=['en-US'], auto=['en-orig', 'en'])
        self.assertEqual(app.choose_track(info, None), app.Track('en-US', 'manual'))

    def test_given_dubbed_audio_tracks_when_default_then_pick_asr_of_the_original_language(self):
        info = make_info(language='en-US', auto=['ar-orig', 'en', 'fr-orig', 'en-orig', 'zh-Hans'])
        self.assertEqual(app.choose_track(info, None), app.Track('en-orig', 'auto'))

    def test_given_unknown_language_and_single_asr_track_when_default_then_use_it(self):
        info = make_info(language=None, auto=['ja-orig', 'en', 'zh-Hans'])
        self.assertEqual(app.choose_track(info, None), app.Track('ja-orig', 'auto'))

    def test_given_only_live_chat_when_default_then_ignore_it(self):
        info = make_info(manual=['live_chat'], auto=['en-orig'])
        self.assertEqual(app.choose_track(info, None), app.Track('en-orig', 'auto'))

    def test_given_requested_language_without_manual_when_chosen_then_use_machine_translation(self):
        info = make_info(auto=['en-orig', 'en', 'zh-Hans', 'zh-Hant'])
        self.assertEqual(app.choose_track(info, 'zh-Hans'), app.Track('zh-Hans', 'auto-translated'))

    def test_given_base_language_request_when_manual_has_region_then_match_it(self):
        info = make_info(manual=['en-GB'], auto=['en-orig'])
        self.assertEqual(app.choose_track(info, 'en'), app.Track('en-GB', 'manual'))

    def test_given_script_code_request_when_manual_uses_region_code_then_prefer_human_translation(self):
        info = make_info(manual=['en', 'zh-CN', 'zh-TW'], auto=['en-orig', 'zh-Hans', 'zh-Hant'])
        self.assertEqual(app.choose_track(info, 'zh-Hans'), app.Track('zh-CN', 'manual'))
        self.assertEqual(app.choose_track(info, 'zh-Hant'), app.Track('zh-TW', 'manual'))

    def test_given_simplified_request_when_only_traditional_exists_then_do_not_cross_scripts(self):
        info = make_info(manual=['zh-TW'], auto=['en-orig', 'zh-Hans'])
        self.assertEqual(app.choose_track(info, 'zh-Hans'), app.Track('zh-Hans', 'auto-translated'))

    def test_given_unavailable_language_when_chosen_then_point_to_list(self):
        info = make_info(auto=['en-orig', 'en'])
        with self.assertRaisesRegex(LookupError, '--list'):
            app.choose_track(info, 'ko')

    def test_given_no_captions_at_all_when_default_then_fail_clearly(self):
        with self.assertRaisesRegex(LookupError, '没有'):
            app.choose_track(make_info(), None)


class ParseBehavior(unittest.TestCase):
    def test_given_asr_json3_when_parsed_then_join_words_and_drop_newline_appends(self):
        data = {
            'events': [
                {'tStartMs': 0, 'id': 1, 'wpWinPosId': 1},
                event(0, 'Hello', ' everyone.'),
                event(1510, '\n', append=True),
                event(1520, 'this', ' video'),
            ]
        }
        self.assertEqual(
            app.parse_json3(data),
            [
                app.Segment(0.0, 'Hello everyone.'),
                app.Segment(1.52, 'this video'),
            ],
        )

    def test_given_manual_json3_with_two_line_cues_when_parsed_then_collapse_to_one_line(self):
        data = {'events': [event(65000, 'first line\nsecond  line')]}
        self.assertEqual(app.parse_json3(data), [app.Segment(65.0, 'first line second line')])


class FormatBehavior(unittest.TestCase):
    def test_given_short_video_when_timed_then_use_minutes_and_seconds(self):
        text = app.format_timed([app.Segment(0, 'a'), app.Segment(65.4, 'b')])
        self.assertEqual(text, '[00:00] a\n[01:05] b')

    def test_given_video_over_an_hour_when_timed_then_include_hours_everywhere(self):
        text = app.format_timed([app.Segment(5, 'a'), app.Segment(3725, 'b')])
        self.assertEqual(text, '[0:00:05] a\n[1:02:05] b')

    def test_given_speaker_change_markers_when_plain_then_start_new_paragraphs(self):
        segments = [app.Segment(0, 'Hello there.'), app.Segment(1, 'How are'), app.Segment(2, '>> Fine, thanks.')]
        self.assertEqual(app.format_plain(segments), 'Hello there. How are\n\nFine, thanks.')


class DownloadBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []

    def fake_run(self, outcomes):
        def run(cmd, **kwargs):
            self.calls.append(cmd)
            code, stderr = outcomes.pop(0)
            if code == 0:
                out = Path(cmd[cmd.index('-o') + 1])
                lang = cmd[cmd.index('--sub-langs') + 1]
                out.with_name(f'{out.name}.{lang}.json3').write_text(json.dumps({'events': []}))
            return subprocess.CompletedProcess(cmd, code, '', stderr)

        return run

    def test_given_a_track_when_downloaded_then_request_exactly_that_one_language(self):
        with patch.object(app.subprocess, 'run', side_effect=self.fake_run([(0, '')])):
            path = app.download_track(self.root / 'info.json', app.Track('en-orig', 'auto'), self.root, [])
        cmd = self.calls[0]
        self.assertEqual(cmd[cmd.index('--sub-langs') + 1], 'en-orig')
        self.assertIn('--write-auto-subs', cmd)
        self.assertNotIn('--write-subs', cmd)
        self.assertTrue(path.exists())

    def test_given_a_manual_track_when_downloaded_then_ask_for_uploaded_subtitles(self):
        with patch.object(app.subprocess, 'run', side_effect=self.fake_run([(0, '')])):
            app.download_track(self.root / 'info.json', app.Track('en-US', 'manual'), self.root, [])
        self.assertIn('--write-subs', self.calls[0])
        self.assertNotIn('--write-auto-subs', self.calls[0])

    def test_given_rate_limit_when_downloading_then_back_off_and_retry(self):
        outcomes = [(1, 'ERROR: HTTP Error 429: Too Many Requests'), (0, '')]
        with (
            patch.object(app.subprocess, 'run', side_effect=self.fake_run(outcomes)),
            patch.object(app.time, 'sleep') as sleep,
        ):
            path = app.download_track(self.root / 'info.json', app.Track('en-orig', 'auto'), self.root, [])
        self.assertEqual(len(self.calls), 2)
        sleep.assert_called_once()
        self.assertTrue(path.exists())

    def test_given_other_failure_when_downloading_then_fail_without_retry(self):
        with (
            patch.object(app.subprocess, 'run', side_effect=self.fake_run([(1, 'ERROR: Video unavailable')])),
            patch.object(app.time, 'sleep') as sleep,
            self.assertRaisesRegex(RuntimeError, 'unavailable'),
        ):
            app.download_track(self.root / 'info.json', app.Track('en-orig', 'auto'), self.root, [])
        sleep.assert_not_called()


class InputBehavior(unittest.TestCase):
    def test_given_bare_video_id_when_resolved_then_build_watch_url(self):
        self.assertEqual(app.video_url('z42ybkbKU0w'), 'https://www.youtube.com/watch?v=z42ybkbKU0w')

    def test_given_any_url_when_resolved_then_pass_it_through(self):
        self.assertEqual(app.video_url('https://youtu.be/z42ybkbKU0w?t=3'), 'https://youtu.be/z42ybkbKU0w?t=3')


if __name__ == '__main__':
    unittest.main()

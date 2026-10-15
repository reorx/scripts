#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Fetch a YouTube video's transcript through yt-dlp and print it as text.

Picks one caption track — uploaded subtitles in the video's language, else the
speech-recognition track of the original audio — downloads only that track as
json3 and prints timestamped lines, plain paragraphs or JSON.

Needs the `yt-dlp` binary on PATH (brew install yt-dlp); keep it updated, YouTube breaks old versions.

    yt-transcript.py <url-or-id>                # [mm:ss] lines under a metadata header
    yt-transcript.py <url> --format plain       # paragraphs, fewest tokens
    yt-transcript.py <url> --lang zh-Hans       # uploaded or machine-translated track
    yt-transcript.py <url> --list               # available tracks
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')
RETRY_DELAYS = (10, 30)
PARAGRAPH_CHARS = 600
SENTENCE_END = ('.', '?', '!', '。', '？', '！')
KIND_LABELS = {'manual': '上传字幕', 'auto': '自动识别', 'auto-translated': '自动识别 + 机器翻译'}
# Uploaders tag Chinese by region (zh-CN), YouTube's machine translations by script (zh-Hans).
EQUIVALENT = [{'zh-Hans', 'zh-CN', 'zh-SG'}, {'zh-Hant', 'zh-TW', 'zh-HK', 'zh-MO'}]


@dataclass
class Track:
    lang: str
    kind: str  # manual | auto | auto-translated


@dataclass
class Segment:
    start: float
    text: str


def video_url(arg: str) -> str:
    return f'https://www.youtube.com/watch?v={arg}' if VIDEO_ID.fullmatch(arg) else arg


def run_ytdlp(args: list[str]) -> subprocess.CompletedProcess:
    """Run yt-dlp, backing off when YouTube rate-limits with HTTP 429."""
    for delay in (*RETRY_DELAYS, None):
        result = subprocess.run(['yt-dlp', *args], capture_output=True, text=True)
        if result.returncode == 0:
            return result
        if delay is None or '429' not in result.stderr:
            break
        print(f'yt-dlp 被限流（429），{delay} 秒后重试…', file=sys.stderr)
        time.sleep(delay)
    raise RuntimeError(result.stderr.strip() or 'yt-dlp 执行失败')


def fetch_info(url: str, extra: list[str]) -> dict:
    return json.loads(run_ytdlp(['-J', '--no-playlist', *extra, url]).stdout)


def base(lang: str) -> str:
    return lang.split('-')[0]


def match_lang(keys: list[str], lang: str) -> str | None:
    """Exact code, else an equivalent one (zh-Hans → zh-CN), else the bare language (en-US → en),
    else any region of a bare request (en → en-GB).

    Sibling subtags never match each other, so zh-Hans won't fall back to zh-Hant.
    """
    if lang in keys:
        return lang
    group = next((group for group in EQUIVALENT if lang in group), ())
    if key := next((key for key in keys if key in group), None):
        return key
    if '-' in lang:
        return base(lang) if base(lang) in keys else None
    return next((key for key in keys if base(key) == lang), None)


def first_match(keys: list[str], codes: list[str]) -> str | None:
    return next((key for code in codes if (key := match_lang(keys, code))), None)


def split_tracks(info: dict) -> tuple[list[str], dict[str, str], list[str]]:
    """Uploaded subtitles, ASR tracks keyed by language, and machine translations.

    Auto-dubbed videos carry one `<lang>-orig` ASR track per dubbed audio track,
    so "-orig" alone doesn't identify the original language.
    """
    manual = [key for key in info.get('subtitles') or {} if key != 'live_chat']
    auto = list(info.get('automatic_captions') or {})
    asr = {key.removesuffix('-orig'): key for key in auto if key.endswith('-orig')}
    translated = [key for key in auto if not key.endswith('-orig')]
    return manual, asr, translated


def find_track(info: dict, lang: str | None) -> Track | None:
    manual, asr, translated = split_tracks(info)
    language = info.get('language')
    codes = [lang] if lang else [language, base(language)] if language else []
    if key := first_match(manual, codes):
        return Track(key, 'manual')
    if key := first_match(list(asr), codes):
        return Track(asr[key], 'auto')
    if key := first_match(translated, codes):
        # Older listings have no -orig tracks; there the video-language key is the original ASR.
        original = not asr and language and base(key) == base(language)
        return Track(key, 'auto' if original else 'auto-translated')
    if lang:
        return None
    if manual:
        return Track(manual[0], 'manual')
    if len(asr) == 1:
        return Track(next(iter(asr.values())), 'auto')
    return None


def choose_track(info: dict, lang: str | None) -> Track:
    if track := find_track(info, lang):
        return track
    if not info.get('automatic_captions') and not split_tracks(info)[0]:
        raise LookupError('这个视频没有任何字幕')
    wanted = lang or info.get('language') or '视频原始语言'
    raise LookupError(f'没有匹配 {wanted} 的字幕；用 --list 查看可用字幕，再用 --lang 指定')


def download_track(info_path: Path, track: Track, outdir: Path, extra: list[str]) -> Path:
    """Download only the chosen track; asking yt-dlp for many languages at once is what triggers 429."""
    write = '--write-subs' if track.kind == 'manual' else '--write-auto-subs'
    run_ytdlp(
        [
            '--load-info-json',
            str(info_path),
            '--skip-download',
            write,
            '--sub-langs',
            track.lang,
            '--sub-format',
            'json3',
            *extra,
            '-o',
            str(outdir / 'sub'),
        ]
    )
    path = outdir / f'sub.{track.lang}.json3'
    if not path.exists():
        raise RuntimeError(f'yt-dlp 没有写出字幕文件：{path.name}')
    return path


def fetch_transcript(info: dict, track: Track, extra: list[str]) -> list[Segment]:
    """Reuse the extracted info so the download doesn't hit the watch page a second time."""
    with tempfile.TemporaryDirectory(prefix='yt-transcript-') as tmp:
        info_path = Path(tmp) / 'info.json'
        info_path.write_text(json.dumps(info))
        return parse_json3(json.loads(download_track(info_path, track, Path(tmp), extra).read_text()))


def parse_json3(data: dict) -> list[Segment]:
    """One segment per caption event; ASR's `aAppend` events hold only a newline and drop out."""
    segments = []
    for event in data.get('events', []):
        text = ' '.join(''.join(seg.get('utf8', '') for seg in event.get('segs', [])).split())
        if text:
            segments.append(Segment(event.get('tStartMs', 0) / 1000, text))
    return segments


def stamp(seconds: float, hours: bool) -> str:
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f'{h}:{m:02d}:{s:02d}' if hours else f'{m:02d}:{s:02d}'


def format_timed(segments: list[Segment]) -> str:
    hours = bool(segments) and segments[-1].start >= 3600
    return '\n'.join(f'[{stamp(seg.start, hours)}] {seg.text}' for seg in segments)


def format_plain(segments: list[Segment]) -> str:
    """Join captions into paragraphs, breaking on ASR speaker changes (`>>`) and after long runs."""
    paragraphs, current = [], []

    def flush():
        if current:
            paragraphs.append(' '.join(current))
            current.clear()

    for seg in segments:
        for index, part in enumerate(seg.text.split('>>')):
            if index:
                flush()
            if part := part.strip():
                current.append(part)
        if sum(map(len, current)) > PARAGRAPH_CHARS and current[-1].endswith(SENTENCE_END):
            flush()
    flush()
    return '\n\n'.join(paragraphs)


def header(info: dict, track: Track) -> str:
    date = info.get('upload_date') or ''
    if len(date) == 8:
        date = f'{date[:4]}-{date[4:6]}-{date[6:]}'
    meta = ' · '.join(filter(None, [info.get('channel') or info.get('uploader'), date, info.get('duration_string')]))
    lines = [info.get('title'), meta, info.get('webpage_url'), f'字幕：{track.lang}（{KIND_LABELS[track.kind]}）']
    return '\n'.join(f'# {line}' for line in lines if line)


def render(info: dict, track: Track, segments: list[Segment], fmt: str, with_header: bool) -> str:
    if fmt == 'json':
        video = {
            key: info.get(key)
            for key in ('id', 'title', 'channel', 'upload_date', 'duration', 'webpage_url', 'language')
        }
        return json.dumps(
            {'video': video, 'track': asdict(track), 'segments': [asdict(seg) for seg in segments]},
            ensure_ascii=False,
            indent=2,
        )
    body = format_plain(segments) if fmt == 'plain' else format_timed(segments)
    return f'{header(info, track)}\n\n{body}' if with_header else body


def describe_tracks(info: dict) -> str:
    manual, asr, translated = split_tracks(info)
    default = find_track(info, None)
    return '\n'.join(
        [
            f'视频语言：{info.get("language") or "未知"}',
            f'上传字幕：{", ".join(manual) or "无"}',
            f'自动识别（每条音轨一份）：{", ".join(asr.values()) or "无"}',
            f'机器翻译（{len(translated)} 种）：{", ".join(translated) or "无"}',
            f'默认使用：{f"{default.lang}（{KIND_LABELS[default.kind]}）" if default else "无法自动判断，请用 --lang 指定"}',
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='用 yt-dlp 获取 YouTube 视频字幕并输出为文本。')
    parser.add_argument('video', help='视频 URL 或 11 位视频 ID')
    parser.add_argument('--lang', help='字幕语言代码，如 en、zh-Hans；默认取视频原始语言')
    parser.add_argument(
        '--format',
        choices=['timed', 'plain', 'json'],
        default='timed',
        help='timed：逐行带时间戳（默认）；plain：合并成段落，最省 token；json：结构化',
    )
    parser.add_argument('--no-header', action='store_true', help='不输出标题、频道等元数据头')
    parser.add_argument('--list', action='store_true', help='列出可用字幕后退出')
    parser.add_argument('--cookies-from-browser', metavar='BROWSER', help='透传给 yt-dlp，用于年龄限制或会员视频')
    return parser


def execute(args: argparse.Namespace) -> None:
    if not shutil.which('yt-dlp'):
        raise RuntimeError('找不到 yt-dlp，请先 brew install yt-dlp')
    extra = ['--cookies-from-browser', args.cookies_from_browser] if args.cookies_from_browser else []
    info = fetch_info(video_url(args.video), extra)
    if args.list:
        print(describe_tracks(info))
        return
    track = choose_track(info, args.lang)
    segments = fetch_transcript(info, track, extra)
    print(render(info, track, segments, args.format, not args.no_header))


def main() -> int:
    args = build_parser().parse_args()
    try:
        execute(args)
    except (RuntimeError, LookupError, OSError, json.JSONDecodeError) as error:
        print(f'错误：{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Dump all open Google Chrome tabs (title + url) into a dated markdown file.

Tabs are grouped by window, rendered as markdown links, and the active tab of
each window is marked with a star. Titles containing `[` / `]` are escaped so
the link syntax stays intact.

By default the snapshot goes to ~/Documents/chrome-tabs/chrome-tabs-<date>.md;
if that file already exists a `-HHMM` suffix is appended so previous snapshots
of the same day are never lost (use -f to overwrite instead).

Usage:
  ./chrome-tabs.py                  # write ~/Documents/chrome-tabs/chrome-tabs-2026-09-11.md
  ./chrome-tabs.py -o ~/notes       # write into another directory
  ./chrome-tabs.py --stdout         # print markdown, write nothing
  ./chrome-tabs.py --dedupe         # drop duplicate URLs (keeps first occurrence)
  ./chrome-tabs.py -f               # overwrite today's file instead of suffixing
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SEP = "\x1f"  # unit separator, safe against tabs/pipes inside titles
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "chrome-tabs"

APPLESCRIPT = f"""
tell application "Google Chrome"
    set out to ""
    set winIndex to 0
    repeat with w in windows
        set winIndex to winIndex + 1
        set activeIdx to active tab index of w
        set tabIndex to 0
        repeat with t in tabs of w
            set tabIndex to tabIndex + 1
            set out to out & winIndex & "{SEP}" & tabIndex & "{SEP}" & activeIdx & "{SEP}" & (title of t) & "{SEP}" & (URL of t) & linefeed
        end repeat
    end repeat
    return out
end tell
"""


def fetch_tabs():
    proc = subprocess.run(
        ["osascript", "-e", APPLESCRIPT], capture_output=True, text=True
    )
    if proc.returncode != 0:
        sys.exit(f"osascript failed: {proc.stderr.strip()}")

    tabs = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split(SEP)
        if len(parts) != 5:
            continue
        win, idx, active, title, url = parts
        tabs.append(
            {
                "window": int(win),
                "index": int(idx),
                "active": int(idx) == int(active),
                "title": title.strip() or url,
                "url": url,
            }
        )
    return tabs


def dedupe_tabs(tabs):
    seen = set()
    result = []
    for tab in tabs:
        if tab["url"] in seen:
            continue
        seen.add(tab["url"])
        result.append(tab)
    return result


def escape(text):
    for ch in ("[", "]"):
        text = text.replace(ch, "\\" + ch)
    return text


def render(tabs, stamp):
    windows = sorted({t["window"] for t in tabs})
    lines = [
        f"# Chrome Tabs {stamp:%Y-%m-%d %H:%M}",
        "",
        f"共 {len(windows)} 个窗口，{len(tabs)} 个标签页。",
        "",
    ]
    for win in windows:
        win_tabs = [t for t in tabs if t["window"] == win]
        lines.append(f"## Window {win} ({len(win_tabs)} tabs)")
        lines.append("")
        for tab in win_tabs:
            mark = " ⭐" if tab["active"] else ""
            lines.append(f"- [{escape(tab['title'])}]({tab['url']}){mark}")
        lines.append("")
    return "\n".join(lines) + "\n"


def resolve_path(out_dir, stamp, force):
    path = out_dir / f"chrome-tabs-{stamp:%Y-%m-%d}.md"
    if path.exists() and not force:
        path = out_dir / f"chrome-tabs-{stamp:%Y-%m-%d-%H%M}.md"
    return path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Save open Google Chrome tabs as a dated markdown list."
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory to write into (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--stdout", action="store_true", help="print markdown instead of writing a file"
    )
    parser.add_argument(
        "--dedupe", action="store_true", help="drop duplicate URLs, keeping the first"
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite today's file instead of adding a -HHMM suffix",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    tabs = fetch_tabs()
    if not tabs:
        sys.exit("No tabs found — is Chrome running?")

    total = len(tabs)
    if args.dedupe:
        tabs = dedupe_tabs(tabs)

    stamp = datetime.now()
    content = render(tabs, stamp)
    if args.stdout:
        sys.stdout.write(content)
        return

    out_dir = args.output_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = resolve_path(out_dir, stamp, args.force)
    path.write_text(content, encoding="utf-8")

    dropped = total - len(tabs)
    suffix = f" ({dropped} duplicates dropped)" if dropped else ""
    print(f"{len(tabs)} tabs -> {path}{suffix}")


if __name__ == "__main__":
    main()

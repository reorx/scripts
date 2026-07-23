#!/usr/bin/env python3
"""ropen — open a remote file/folder (scp syntax) with a local app.

Usage:
    ropen.py user@host:path/to/file     download to cache, then open
    ropen.py host:path/to/dir           folders work too (scp -r)
    ropen.py                            TUI of recently opened files

The remote path is copied into ~/.local/share/ropen/cache, preserving the
host/path layout, and opened with the system opener (open / xdg-open).

With no argument, a curses list of recently opened files is shown:
    j / ↓   move down
    k / ↑   move up
    enter   download and open the selected entry again
    q / esc quit
"""

import curses
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ropen"
CACHE_DIR = DATA_DIR / "cache"
HISTORY_FILE = DATA_DIR / "history.json"


def parse_spec(spec):
    """Split an scp-style spec into (spec, host, remote_path).

    'user@genji.zt:Downloads/test.txt' -> (spec, 'genji.zt', 'Downloads/test.txt')
    """
    if ":" not in spec:
        raise ValueError(f"invalid scp spec (missing ':'): {spec!r}")
    remote, remote_path = spec.split(":", 1)
    if not remote or not remote_path:
        raise ValueError(f"invalid scp spec: {spec!r}")
    host = remote.split("@")[-1]
    return host, remote_path


def local_target(host, remote_path):
    """Map a remote path to its local cache path, sanitizing traversal parts."""
    parts = [p for p in remote_path.split("/") if p not in ("", ".", "..")]
    return CACHE_DIR / host / Path(*parts)


def download(spec, target):
    """Copy the remote path into the cache, replacing any stale copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    elif target.exists() or target.is_symlink():
        target.unlink()
    subprocess.run(["scp", "-r", spec, str(target.parent) + os.sep], check=True)


def opener_cmd():
    return ["open"] if platform.system() == "Darwin" else ["xdg-open"]


def open_path(target):
    subprocess.run(opener_cmd() + [str(target)], check=True)


def load_history():
    if not HISTORY_FILE.exists():
        return []
    return json.loads(HISTORY_FILE.read_text())


def save_history(entries):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(entries, indent=2))


def record_open(spec, target):
    entries = [e for e in load_history() if e.get("spec") != spec]
    entries.append({"spec": spec, "local_path": str(target), "opened_at": time.time()})
    save_history(entries)


def ropen(spec):
    """Download the spec into the cache, open it, and record the open."""
    host, remote_path = parse_spec(spec)
    target = local_target(host, remote_path)
    print(f"↓ downloading {spec}")
    download(spec, target)
    print(f"↗ opening {target}")
    open_path(target)
    record_open(spec, target)


def human_time(ts):
    delta = time.time() - ts
    if delta < 60:
        rel = "just now"
    elif delta < 3600:
        rel = f"{int(delta // 60)}m ago"
    elif delta < 86400:
        rel = f"{int(delta // 3600)}h ago"
    else:
        rel = f"{int(delta // 86400)}d ago"
    abs_ = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    return abs_, rel


def tui(stdscr, entries):
    """Render the recent-files list; return the chosen spec or None."""
    curses.curs_set(0)
    idx = 0
    offset = 0
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        max_rows = max(1, height - 3)
        if idx < offset:
            offset = idx
        elif idx >= offset + max_rows:
            offset = idx - max_rows + 1

        stdscr.addstr(0, 0, "ropen — recent files"[: width - 1], curses.A_BOLD)
        stdscr.addstr(1, 0, "j/k move  enter open  q quit"[: width - 1], curses.A_DIM)
        for row, e in enumerate(entries[offset : offset + max_rows]):
            i = offset + row
            abs_, rel = human_time(e["opened_at"])
            line = f"{abs_}  {rel:>8}   {e['spec']}"[: width - 1]
            attr = curses.A_REVERSE if i == idx else curses.A_NORMAL
            stdscr.addstr(row + 3, 0, line, attr)
        stdscr.refresh()

        key = stdscr.getch()
        if key in (ord("q"), 27):
            return None
        if key in (ord("j"), curses.KEY_DOWN):
            idx = min(idx + 1, len(entries) - 1)
        elif key in (ord("k"), curses.KEY_UP):
            idx = max(idx - 1, 0)
        elif key in (curses.KEY_ENTER, 10, 13):
            return entries[idx]["spec"]


def main(argv):
    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0

    if len(argv) > 1:
        ropen(argv[1])
        return 0

    entries = sorted(load_history(), key=lambda e: e["opened_at"], reverse=True)
    if not entries:
        print("no recent files yet. usage: ropen.py user@host:path")
        return 0
    spec = curses.wrapper(tui, entries)
    if spec:
        ropen(spec)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["tiktoken>=0.8"]
# ///
"""List the largest AGENTS.md files under ~/Code, by token count.

Files are found the way ripgrep would search them: .gitignore (inside git
repos), .ignore, .rgignore and the global git excludes apply, hidden
directories are skipped. Symlinks are followed, so an AGENTS.md -> CLAUDE.md
link or a project directory linked into ~/Code counts too; a file reached
through several paths is listed once, by its direct path.

Tokens are counted with tiktoken's o200k_base encoding (GPT-4o / GPT-5).
Claude's tokenizer is not public; its counts run somewhat higher, but the
ranking is the same. Rows over the threshold are yellow; the threshold
defaults to DEFAULT_MAX_TOKENS and can be set with $AGENTS_MD_MAX_TOKENS.

    agents-md-top.py                          # top 20 under ~/Code
    agents-md-top.py -n 50                    # top 50
    agents-md-top.py ~/Work                   # another root
    AGENTS_MD_MAX_TOKENS=3000 agents-md-top.py
"""

import argparse
import functools
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import tiktoken

FILENAME = 'AGENTS.md'
ENCODING = 'o200k_base'
# About the 85th percentile of ~/Code on 2026-11-15 (median 2.3k), well under the
# sizes where agents start truncating or warning (~8-10k tokens).
DEFAULT_MAX_TOKENS = 5000
THRESHOLD_ENV = 'AGENTS_MD_MAX_TOKENS'
DEFAULT_LIMIT = 20

YELLOW = '\x1b[33m'
BOLD = '\x1b[1m'
DIM = '\x1b[2m'
RESET = '\x1b[0m'


@dataclass(frozen=True)
class Entry:
    path: Path
    tokens: int
    size: int
    mtime: datetime
    project: str


def find_agents_files(root: Path) -> list[Path]:
    """AGENTS.md files rg would search under root, one path per real file.

    rg lists every file and the name is matched here: an rg --glob is an
    override that would bring back AGENTS.md files a .gitignore excludes.
    """
    proc = subprocess.run(['rg', '--files', '--follow', '--null', str(root)], capture_output=True)
    # Exit 2 also covers partial errors such as broken symlinks; only fail when nothing came back.
    if proc.returncode == 2 and not proc.stdout:
        raise RuntimeError(f'rg failed: {proc.stderr.decode(errors="replace").strip()}')
    paths = [Path(p) for p in proc.stdout.decode().split('\0') if p and Path(p).name == FILENAME]
    return dedupe(paths, root)


def dedupe(paths: list[Path], root: Path) -> list[Path]:
    """Keep one path per real file, preferring one not reached through a symlinked directory."""
    real_root = root.resolve()

    def preference(path: Path):
        via_link = path.parent.resolve() != real_root / path.parent.relative_to(root)
        return (via_link, len(path.parts), str(path))

    best: dict[Path, Path] = {}
    for path in sorted(paths, key=preference):
        best.setdefault(path.resolve(), path)
    return list(best.values())


@functools.cache
def encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING)


def count_tokens(text: str) -> int:
    # encode_ordinary: a literal "<|endoftext|>" in a doc is text, not a special token.
    return len(encoding().encode_ordinary(text))


def project_of(path: Path, root: Path) -> str:
    parts = path.relative_to(root).parts
    return parts[0] if len(parts) > 1 else '-'


def measure(path: Path, root: Path) -> Entry:
    stat = path.stat()
    text = path.read_bytes().decode('utf-8', errors='replace')
    return Entry(
        path=path,
        tokens=count_tokens(text),
        size=stat.st_size,
        mtime=datetime.fromtimestamp(stat.st_mtime),
        project=project_of(path, root),
    )


def collect(root: Path) -> list[Entry]:
    """Every AGENTS.md under root, largest token count first."""
    entries = [measure(path, root) for path in find_agents_files(root)]
    return sorted(entries, key=lambda e: (-e.tokens, -e.size, str(e.path)))


def read_threshold(env) -> int:
    raw = env.get(THRESHOLD_ENV)
    if raw is None:
        return DEFAULT_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ValueError(f'{THRESHOLD_ENV} must be a positive integer, got {raw!r}')
    return value


def human_size(n: int) -> str:
    if n < 1024:
        return f'{n}B'
    for unit in 'KMG':
        n /= 1024
        if n < 1024 or unit == 'G':
            return f'{n:.1f}{unit}'


def display_path(path: Path, home: Path) -> str:
    if path.is_relative_to(home):
        return str(Path('~') / path.relative_to(home))
    return str(path)


def render(entries: list[Entry], *, root: Path, threshold: int, limit: int, color: bool, home: Path) -> str:
    where = display_path(root, home)
    if not entries:
        return f'No {FILENAME} under {where}'

    def paint(code: str, text: str) -> str:
        return f'{code}{text}{RESET}' if color else text

    shown = entries[:limit]
    header = ('PATH', 'TOKENS', 'SIZE', 'MTIME', 'PROJECT')
    rows = [
        (display_path(e.path, home), f'{e.tokens:,}', human_size(e.size), e.mtime.strftime('%Y-%m-%d %H:%M'), e.project)
        for e in shown
    ]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    right_aligned = {1, 2}

    def line(cells) -> str:
        padded = (
            cell.rjust(w) if i in right_aligned else cell.ljust(w) for i, (cell, w) in enumerate(zip(cells, widths))
        )
        return '  '.join(padded).rstrip()

    lines = [paint(BOLD, line(header))]
    for e, row in zip(shown, rows):
        text = line(row)
        lines.append(paint(YELLOW, text) if e.tokens > threshold else text)

    over = sum(e.tokens > threshold for e in entries)
    count = (
        f'{len(entries)} {FILENAME}' if len(shown) == len(entries) else f'top {len(shown)} of {len(entries)} {FILENAME}'
    )
    footer = f'{count} under {where} · {over} over {threshold:,} tokens (${THRESHOLD_ENV}) · tiktoken {ENCODING}'
    lines += ['', paint(DIM, footer)]
    return '\n'.join(lines)


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        'root', nargs='?', type=Path, default=Path.home() / 'Code', help='directory to scan (default: ~/Code)'
    )
    parser.add_argument(
        '-n', '--limit', type=int, default=DEFAULT_LIMIT, help=f'rows to show (default: {DEFAULT_LIMIT})'
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    root = Path(os.path.abspath(args.root.expanduser()))
    try:
        threshold = read_threshold(os.environ)
        if not root.is_dir():
            raise ValueError(f'{root} is not a directory')
        if shutil.which('rg') is None:
            raise RuntimeError('rg (ripgrep) not found in PATH')
        entries = collect(root)
    except (ValueError, RuntimeError, OSError) as e:
        print(f'agents-md-top: {e}', file=sys.stderr)
        return 1
    color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ
    print(render(entries, root=root, threshold=threshold, limit=args.limit, color=color, home=Path.home()))
    return 0


if __name__ == '__main__':
    sys.exit(main())

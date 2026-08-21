#!/usr/bin/env python3
"""Split sections out of a Markdown file.

Commands:
  list  <file>                      List all headings in the file.
  split <file> <heading> [-o OUT]   Extract a section into a separate file
                                    and leave a reference link in place.

The <heading> argument must be the full heading line, e.g. "# Heading1".
OUT is an output file path relative to the directory of <file>
(default: <slug>.md in the same directory).
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

NOTICE_TEMPLATE = (
    '> **Note:** The original section "{title}" has been split into a separate file. See [{title}]({link}).'
)

FENCE_RE = re.compile(r'^(```|~~~)')
HEADING_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')


def iter_headings(lines):
    """Yield (line_index, level, title, raw_line) for headings outside code fences."""
    fence = None
    for i, line in enumerate(lines):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            continue
        m = HEADING_RE.match(line)
        if m:
            yield i, len(m.group(1)), m.group(2), line.rstrip('\n')


def slugify(title):
    text = unicodedata.normalize('NFKC', title)
    text = re.sub(r"[`*_\[\](){}<>!#\"'|:;,./\\?]+", '', text)
    text = re.sub(r'\s+', '-', text.strip()).lower()
    return text or 'section'


def cmd_list(path):
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    headings = list(iter_headings(lines))
    if not headings:
        print('No headings found.')
        return
    for i, level, title, _raw in headings:
        indent = '  ' * (level - 1)
        print(f'{i + 1:>5}  {indent}{"#" * level} {title}')


def find_section(lines, heading_line):
    """Return (start, end, level, title). end is exclusive."""
    target = heading_line.strip()
    headings = list(iter_headings(lines))
    matches = [h for h in headings if h[3].strip() == target]
    if not matches:
        sys.exit(f'Error: heading not found: {target}')
    if len(matches) > 1:
        positions = ', '.join(str(m[0] + 1) for m in matches)
        print(
            f'Warning: heading appears {len(matches)} times (lines {positions}); using the first one.',
            file=sys.stderr,
        )
    start, level, title, _raw = matches[0]
    end = len(lines)
    for i, lvl, _t, _r in headings:
        if i > start and lvl <= level:
            end = i
            break
    return start, end, level, title


def cmd_split(path, heading_line, output):
    content = path.read_text(encoding='utf-8')
    lines = content.splitlines(keepends=True)
    start, end, _level, title = find_section(lines, heading_line)

    rel_output = Path(output) if output else Path(f'{slugify(title)}.md')
    target_path = path.parent / rel_output
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        sys.exit(f'Error: target file already exists: {target_path}')

    section = lines[start:end]
    section_text = ''.join(section)
    if not section_text.endswith('\n'):
        section_text += '\n'
    target_path.write_text(section_text, encoding='utf-8')

    link = rel_output.as_posix()
    replacement = [
        lines[start] if lines[start].endswith('\n') else lines[start] + '\n',
        '\n',
        NOTICE_TEMPLATE.format(title=title, link=link) + '\n',
        '\n',
    ]
    new_lines = lines[:start] + replacement + lines[end:]
    path.write_text(''.join(new_lines), encoding='utf-8')

    print(f'Section "{title}" ({end - start} lines) -> {target_path}')
    print(f'Reference link left in {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)

    p_list = sub.add_parser('list', help='list headings in the file')
    p_list.add_argument('file', type=Path)

    p_split = sub.add_parser('split', help='split a section into a separate file')
    p_split.add_argument('file', type=Path)
    p_split.add_argument('heading', help='full heading line, e.g. "# Heading1"')
    p_split.add_argument(
        '-o',
        '--output',
        default=None,
        help='output file path, relative to the file (default: <slug>.md in the same directory)',
    )

    args = parser.parse_args()
    if not args.file.is_file():
        sys.exit(f'Error: file not found: {args.file}')

    if args.command == 'list':
        cmd_list(args.file)
    else:
        cmd_split(args.file, args.heading, args.output)


if __name__ == '__main__':
    main()

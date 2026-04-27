#!/usr/bin/env python3
"""
btmlist - list and inspect macOS Background Task Management items.

These are the same items you see in System Settings > General >
Login Items & Extensions: launch agents, launch daemons, login items,
helper tools, quicklook/spotlight extensions, and the developer group
headers that wrap them.

Source of truth: `sfltool dumpbtm`. This script just parses that output
and presents it as a flat, filterable table (or JSON), so you can find
out what mystery entries like "won fen" actually point to on disk.

Usage examples:
    btmlist.py                          # table of all real items (skip dev group headers)
    btmlist.py --all                    # include developer group headers
    btmlist.py --name 'won fen'         # search by name (case-insensitive substring)
    btmlist.py --developer 'won fen'    # filter by developer name
    btmlist.py --enabled                # only enabled items
    btmlist.py --disabled               # only disabled items
    btmlist.py --type 'legacy agent'    # filter by type label
    btmlist.py --json                   # full structured JSON
    btmlist.py --reveal 'Clash Verge'   # open the item's folder in Finder
    btmlist.py --paths                  # one path per line (scriptable)
"""

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from typing import Iterable
from urllib.parse import unquote, urlparse


# ---------- parsing ----------

ITEM_HEADER_RE = re.compile(r'^ #\d+:\s*$')
SECTION_HEADER_RE = re.compile(r'^ Records for UID (-?\d+)\s*:\s*(\S+)')
KV_RE = re.compile(r'^\s{2,}([A-Za-z][A-Za-z .]*?):\s?(.*)$')


@dataclass
class Item:
    uid: str = ''
    section: str = ''
    name: str = ''
    developer: str = ''
    team_id: str = ''
    type: str = ''
    type_code: str = ''
    flags: str = ''
    disposition: str = ''
    enabled: bool | None = None
    identifier: str = ''
    url: str = ''
    path: str = ''  # decoded filesystem path from URL
    executable_path: str = ''
    bundle_id: str = ''
    parent_identifier: str = ''
    embedded: list[str] = field(default_factory=list)
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def best_path(self) -> str:
        return self.executable_path or self.path or ''

    @property
    def is_group(self) -> bool:
        # "developer" type entries are parent group headers (no path of their own).
        return self.type == 'developer'


def _decode_url_path(url: str) -> str:
    if not url or url == '(null)':
        return ''
    try:
        parsed = urlparse(url)
        if parsed.scheme == 'file':
            return unquote(parsed.path).rstrip('/') or '/'
    except ValueError:
        pass
    return ''


def _parse_disposition(value: str) -> bool | None:
    # Example: "[enabled, allowed, notified] (0xb)"
    inside = value.split(']', 1)[0].lstrip('[')
    parts = [p.strip() for p in inside.split(',') if p.strip()]
    if 'enabled' in parts:
        return True
    if 'disabled' in parts:
        return False
    return None


def _split_type(value: str) -> tuple[str, str]:
    # Example: "legacy daemon (0x10010)"
    m = re.match(r'(.*?)\s*\(([^)]+)\)\s*$', value)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return value.strip(), ''


def parse_dump(text: str) -> list[Item]:
    items: list[Item] = []
    section_uid = ''
    section_uuid = ''

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        m = SECTION_HEADER_RE.match(line)
        if m:
            section_uid, section_uuid = m.group(1), m.group(2)
            i += 1
            continue

        if ITEM_HEADER_RE.match(line):
            item = Item(uid=section_uid, section=section_uuid)
            i += 1
            current_key: str | None = None
            while i < len(lines):
                nxt = lines[i]
                if ITEM_HEADER_RE.match(nxt) or SECTION_HEADER_RE.match(nxt):
                    break
                # Embedded list entries look like "    #1: <id>"
                emb = re.match(r'^\s{4,}#\d+:\s*(.*)$', nxt)
                if emb and current_key in {'Embedded Item Identifiers'}:
                    item.embedded.append(emb.group(1).strip())
                    i += 1
                    continue
                kv = KV_RE.match(nxt)
                if kv:
                    key = kv.group(1).strip()
                    val = kv.group(2).strip()
                    current_key = key
                    item.raw[key] = val
                    if key == 'Name':
                        item.name = val if val != '(null)' else ''
                    elif key == 'Developer Name':
                        item.developer = val if val != '(null)' else ''
                    elif key == 'Team Identifier':
                        item.team_id = val
                    elif key == 'Type':
                        item.type, item.type_code = _split_type(val)
                    elif key == 'Flags':
                        item.flags = val
                    elif key == 'Disposition':
                        item.disposition = val
                        item.enabled = _parse_disposition(val)
                    elif key == 'Identifier':
                        item.identifier = val
                    elif key == 'URL':
                        item.url = '' if val == '(null)' else val
                        item.path = _decode_url_path(val)
                    elif key == 'Executable Path':
                        item.executable_path = val
                    elif key == 'Bundle Identifier':
                        item.bundle_id = val
                    elif key == 'Parent Identifier':
                        item.parent_identifier = val
                i += 1
            items.append(item)
            continue

        i += 1

    return items


# ---------- IO helpers ----------


def run_dumpbtm() -> str:
    if shutil.which('sfltool') is None:
        sys.exit('error: sfltool not found (requires macOS).')
    proc = subprocess.run(['sfltool', 'dumpbtm'], capture_output=True, text=True, check=False)
    # sfltool prints to stdout even on success; fall back to stderr if empty.
    return proc.stdout or proc.stderr


# ---------- filtering ----------


def _ci(needle: str, haystack: str) -> bool:
    return needle.lower() in haystack.lower()


def filter_items(
    items: Iterable[Item],
    *,
    name: str | None = None,
    developer: str | None = None,
    type_: str | None = None,
    identifier: str | None = None,
    only_enabled: bool = False,
    only_disabled: bool = False,
    include_groups: bool = False,
) -> list[Item]:
    out: list[Item] = []
    for it in items:
        if not include_groups and it.is_group:
            continue
        if name and not _ci(name, it.name):
            continue
        if developer and not _ci(developer, it.developer):
            continue
        if type_ and not _ci(type_, it.type):
            continue
        if identifier and not _ci(identifier, it.identifier):
            continue
        if only_enabled and it.enabled is not True:
            continue
        if only_disabled and it.enabled is not False:
            continue
        out.append(it)
    return out


# ---------- rendering ----------


def _status(it: Item) -> str:
    if it.enabled is True:
        return 'on'
    if it.enabled is False:
        return 'off'
    return '?'


def render_table(items: list[Item]) -> str:
    headers = ('STATUS', 'TYPE', 'NAME', 'DEVELOPER', 'PATH')
    rows = [(_status(it), it.type or '-', it.name or '-', it.developer or '-', it.best_path or '-') for it in items]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i == len(widths) - 1:  # don't pad the last column
                continue
            widths[i] = max(widths[i], len(cell))

    def fmt(row: tuple[str, ...]) -> str:
        parts = []
        for i, cell in enumerate(row):
            if i == len(widths) - 1:
                parts.append(cell)
            else:
                parts.append(cell.ljust(widths[i]))
        return '  '.join(parts)

    lines = [fmt(headers), fmt(tuple('-' * w for w in widths))]
    lines.extend(fmt(r) for r in rows)
    return '\n'.join(lines)


def render_paths(items: list[Item]) -> str:
    return '\n'.join(it.best_path for it in items if it.best_path)


def render_json(items: list[Item]) -> str:
    return json.dumps([asdict(it) for it in items], indent=2, ensure_ascii=False)


# ---------- actions ----------


def reveal(items: list[Item]) -> int:
    if not items:
        print('no matches', file=sys.stderr)
        return 1
    for it in items:
        target = it.best_path
        if not target:
            print(f'skip (no path): {it.name or it.identifier}', file=sys.stderr)
            continue
        print(f'reveal: {target}')
        subprocess.run(['open', '-R', target], check=False)
    return 0


# ---------- main ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description='List and inspect macOS Background Task Management items.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--name', help='filter by name (case-insensitive substring)')
    p.add_argument('--developer', help='filter by developer name')
    p.add_argument('--type', dest='type_', help="filter by type label, e.g. 'legacy agent'")
    p.add_argument('--identifier', help='filter by identifier substring')
    p.add_argument('--enabled', action='store_true', help='only enabled items')
    p.add_argument('--disabled', action='store_true', help='only disabled items')
    p.add_argument('--all', action='store_true', help='include developer group headers')
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument('--json', action='store_true', help='emit JSON')
    fmt.add_argument('--paths', action='store_true', help='emit one path per line')
    fmt.add_argument('--reveal', action='store_true', help='open matching item(s) in Finder')
    p.add_argument('--input', help='read sfltool dumpbtm output from a file instead of running it')
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.input:
        with open(args.input, encoding='utf-8') as f:
            text = f.read()
    else:
        text = run_dumpbtm()

    items = parse_dump(text)
    items = filter_items(
        items,
        name=args.name,
        developer=args.developer,
        type_=args.type_,
        identifier=args.identifier,
        only_enabled=args.enabled,
        only_disabled=args.disabled,
        include_groups=args.all,
    )

    if args.reveal:
        return reveal(items)
    if args.json:
        print(render_json(items))
    elif args.paths:
        print(render_paths(items))
    else:
        print(render_table(items))
    return 0


if __name__ == '__main__':
    sys.exit(main())

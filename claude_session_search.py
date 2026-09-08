#!/usr/bin/env python3
"""Search text in recent Claude Code sessions.

Examples:
    python3 claude_session_search.py grafana
    python3 claude_session_search.py -d 3 -r user -r assistant "netdata"
    python3 claude_session_search.py -d 14 -r tool --project breeze "curl"

List sessions of a project (newest first) with ID and the first prompt:
    python3 claude_session_search.py -L ~/Code/tenderbuddy
    python3 claude_session_search.py -L . -d 30 --full
    python3 claude_session_search.py -L tenderbuddy        # substring match on project dir names
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_DIR = Path.home() / '.claude' / 'projects'
ROLES = ('user', 'assistant', 'tool')

C_RESET = '\033[0m'
C_BOLD = '\033[1m'
C_DIM = '\033[2m'
C_HL = '\033[1;31m'
C_BLUE = '\033[34m'
C_GRAY = '\033[38;5;245m'  # 256-color gray; \033[2m (dim) is not rendered by some terminals
ROLE_COLORS = {'user': '\033[36m', 'assistant': '\033[32m', 'tool': '\033[33m'}


@dataclass
class Match:
    role: str
    timestamp: str
    snippet: str
    detail: str  # e.g. tool name


def parse_args():
    p = argparse.ArgumentParser(description='Search recent Claude Code sessions')
    p.add_argument('query', nargs='?', help="text or regex to search for, e.g. 'envops (show|copy|set|list-keys)'")
    p.add_argument(
        '-L',
        '--list',
        nargs='?',
        const='.',
        metavar='PATH',
        help='list sessions of the project at PATH (default: cwd) newest first, with session ID and first prompt; '
        'PATH may also be a substring of a project dir name',
    )
    p.add_argument(
        '-d',
        '--days',
        type=float,
        help='only sessions modified within N days (default: 7 for search, unlimited for --list)',
    )
    p.add_argument(
        '-r', '--role', action='append', choices=ROLES, dest='roles', help='roles to search (repeatable); default: all'
    )
    p.add_argument('-p', '--project', help='only projects whose dir name contains this substring')
    p.add_argument(
        '-l',
        '--label',
        action='append',
        dest='labels',
        help="only matches whose label contains this substring, e.g. 'tool_use:Bash', 'tool_result', 'thinking' (repeatable)",
    )
    p.add_argument('--case-sensitive', action='store_true', help='case-sensitive matching (default: insensitive)')
    p.add_argument('-C', '--context', type=int, default=80, help='chars of context around each match (default: 80)')
    p.add_argument('-n', '--limit', type=int, default=200, help='max matches/sessions to show (default: 200)')
    p.add_argument('--full', action='store_true', help='--list: print the whole first prompt instead of one line')
    args = p.parse_args()
    if args.list is None and args.query is None:
        p.error('query is required unless --list is given')
    return args


def iter_session_files(days: float | None, project_filter: str | None):
    cutoff = time.time() - days * 86400 if days else 0
    if not PROJECTS_DIR.is_dir():
        sys.exit(f'projects dir not found: {PROJECTS_DIR}')
    for proj in sorted(PROJECTS_DIR.iterdir()):
        if not proj.is_dir():
            continue
        if project_filter and project_filter.lower() not in proj.name.lower():
            continue
        for f in proj.glob('*.jsonl'):
            if f.stat().st_mtime >= cutoff:
                yield proj.name, f


def iter_texts(record: dict):
    """Yield (role, text, detail, tool_input) pieces from one JSONL record.

    tool_input is the parsed input dict for tool_use blocks, else None.
    """
    rtype = record.get('type')
    msg = record.get('message')
    if rtype not in ('user', 'assistant') or not isinstance(msg, dict):
        return
    content = msg.get('content')
    if isinstance(content, str):
        if rtype == 'user':
            yield 'user', content, '', None
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get('type')
        if btype == 'text':
            yield rtype, block.get('text', ''), '', None
        elif btype == 'thinking' and rtype == 'assistant':
            yield 'assistant', block.get('thinking', ''), 'thinking', None
        elif btype == 'tool_use':
            inp = block.get('input', {})
            if not isinstance(inp, dict):
                inp = {'input': inp}
            text = '\n'.join(f'{k}: {stringify(v)}' for k, v in inp.items())
            yield 'tool', text, f'tool_use:{block.get("name", "?")}', inp
        elif btype == 'tool_result':
            inner = block.get('content')
            if isinstance(inner, list):
                text = '\n'.join(b.get('text', '') for b in inner if isinstance(b, dict) and b.get('type') == 'text')
            else:
                text = inner if isinstance(inner, str) else ''
            yield 'tool', text, 'tool_result', None


def stringify(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def make_snippet(text: str, m: re.Match, ctx: int) -> str:
    start = max(0, m.start() - ctx)
    end = min(len(text), m.end() + ctx)
    prefix = '…' if start > 0 else ''
    suffix = '…' if end < len(text) else ''
    snippet = text[start : m.start()] + C_HL + text[m.start() : m.end()] + C_RESET + text[m.end() : end]
    snippet = snippet.replace('\n', '⏎')
    return prefix + snippet + suffix


def highlight_all(text: str, pattern: re.Pattern, resume: str = '') -> str:
    """Highlight all matches; `resume` is the color to restore after each match."""
    return pattern.sub(lambda m: C_HL + m.group(0) + C_RESET + resume, text)


MAX_FIELD = 300
WRAP_LEN = 80  # vim 默认排版宽度（textwidth 习惯值 78–80，取 80）
SHFMT = shutil.which('shfmt')


def format_command(cmd: str) -> str:
    """Reformat a shell command with shfmt when any line exceeds WRAP_LEN."""
    if not SHFMT or all(len(ln) <= WRAP_LEN for ln in cmd.splitlines()):
        return cmd
    try:
        r = subprocess.run([SHFMT, '-i', '2'], input=cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return cmd
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.rstrip('\n')
    return cmd


def render_tool_use(inp: dict, pattern: re.Pattern, ctx: int) -> str:
    """Multiline rendering of a tool_use input: description first as `# ...`,
    then command as `$ ...`, both in full; other fields truncated (around the
    match if there is one)."""
    inp = dict(inp)
    desc = inp.pop('description', None)
    cmd = inp.pop('command', None)
    lines = []
    if desc is not None:
        lines.append(f'{C_GRAY}# {highlight_all(stringify(desc), pattern, C_GRAY)}{C_RESET}')
    if cmd is not None:
        lines.append(f'{C_GRAY}${C_RESET} {highlight_all(format_command(stringify(cmd)), pattern)}')
    for k, v in inp.items():
        s = stringify(v)
        if len(s) <= MAX_FIELD:
            s = highlight_all(s, pattern)
        else:
            m = pattern.search(s)
            s = make_snippet(s, m, ctx) if m else s[:MAX_FIELD].replace('\n', '⏎') + '…'
        lines.append(f'{C_DIM}{k}:{C_RESET} {s}')
    return '\n'.join(lines)


def fmt_time(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
        return dt.strftime('%m-%d %H:%M')
    except (ValueError, AttributeError):
        return '?'


def search_file(path: Path, pattern: re.Pattern, roles: set[str], labels: list[str] | None, ctx: int) -> list[Match]:
    matches = []
    with open(path, errors='replace') as fp:
        for line in fp:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            for role, text, detail, tool_input in iter_texts(record):
                if role not in roles or not text:
                    continue
                if labels and not any(lb.lower() in detail.lower() for lb in labels):
                    continue
                m = pattern.search(text)
                if not m:
                    continue
                if tool_input is not None:
                    snippet = render_tool_use(tool_input, pattern, ctx)
                else:
                    snippet = make_snippet(text, m, ctx)
                matches.append(Match(role, fmt_time(record.get('timestamp', '')), snippet, detail))
    return matches


# ---------------------------------------------------------------------------
# --list mode


@dataclass
class SessionInfo:
    session_id: str
    started: str  # ISO timestamp of the first prompt ('' if none)
    first_prompt: str
    prompts: int  # number of human prompts


def encode_project_path(path: str) -> str:
    """Map an absolute project path to its dir name under ~/.claude/projects."""
    return re.sub(r'[^A-Za-z0-9-]', '-', path)


def resolve_project_dirs(arg: str) -> list[Path]:
    p = Path(arg).expanduser()
    if p.is_dir():
        d = PROJECTS_DIR / encode_project_path(str(p.resolve()))
        if d.is_dir():
            return [d]
        sys.exit(f'no sessions recorded for {p.resolve()} (expected {d})')
    hits = [d for d in sorted(PROJECTS_DIR.iterdir()) if d.is_dir() and arg.lower() in d.name.lower()]
    if not hits:
        sys.exit(f'no project dir matches {arg!r} under {PROJECTS_DIR}')
    return hits


_TAG_BLOCKS = re.compile(r'<(system-reminder|command-message|ide_opened_file|ide_selection)>.*?</\1>\s*', re.S)
_COMMAND = re.compile(r'<command-name>(.*?)</command-name>\s*(?:<command-args>(.*?)</command-args>)?', re.S)


def clean_prompt(text: str) -> str:
    """Strip harness-injected wrappers so the user's own words remain."""
    text = _TAG_BLOCKS.sub('', text)
    text = _COMMAND.sub(lambda m: f'{m.group(1).strip()} {(m.group(2) or "").strip()}'.strip(), text)
    return text.strip()


def human_prompt_text(record: dict) -> str | None:
    """Return the text of a user record if it is a prompt typed by the human, else None."""
    if record.get('type') != 'user' or record.get('isSidechain'):
        return None
    content = record.get('message', {}).get('content')
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']
        if not parts:
            return None  # tool_result-only record
        text = '\n'.join(parts)
    else:
        return None
    if text.startswith('[Image: source:'):
        return None  # image attachment carrier that follows an image prompt
    return text


def session_info(path: Path) -> SessionInfo:
    first, started, prompts = '', '', 0
    with open(path, errors='replace') as fp:
        for line in fp:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = human_prompt_text(record)
            if text is None:
                continue
            prompts += 1
            if not first:
                first = clean_prompt(text)
                started = record.get('timestamp', '')
    return SessionInfo(path.stem, started, first, prompts)


def fmt_datetime(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M')
    except (ValueError, AttributeError):
        return '?'


def human_size(n: int) -> str:
    for unit in ('B', 'K', 'M', 'G'):
        if n < 1024 or unit == 'G':
            return f'{n:.0f}{unit}' if unit == 'B' else f'{n:.1f}{unit}'
        n /= 1024
    return f'{n:.1f}G'


PROMPT_LINE_LEN = 240


def list_sessions(args):
    cutoff = time.time() - args.days * 86400 if args.days else 0
    shown = 0
    for proj_dir in resolve_project_dirs(args.list):
        files = [f for f in proj_dir.glob('*.jsonl') if f.stat().st_mtime >= cutoff]
        infos = [(session_info(f), f) for f in files]
        infos.sort(key=lambda t: t[0].started or '', reverse=True)
        print(f'{C_BOLD}{proj_dir.name}{C_RESET} {C_DIM}({len(infos)} sessions){C_RESET}')
        for info, f in infos:
            if shown >= args.limit:
                break
            st = f.stat()
            meta = f'{info.prompts} prompts, {human_size(st.st_size)}, updated {datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")}'
            print(f'\n{C_BLUE}{fmt_datetime(info.started)}{C_RESET}  {C_BOLD}{info.session_id}{C_RESET}  {C_GRAY}{meta}{C_RESET}')
            prompt = info.first_prompt or f'{C_DIM}(no prompt){C_RESET}'
            if args.full:
                print('\n'.join('    ' + ln for ln in prompt.splitlines()))
            else:
                one = prompt.replace('\n', '⏎')
                if len(one) > PROMPT_LINE_LEN:
                    one = one[:PROMPT_LINE_LEN] + '…'
                print(f'    {one}')
            shown += 1
        print()


def main():
    args = parse_args()
    if args.list is not None:
        list_sessions(args)
        return
    if args.days is None:
        args.days = 7
    roles = set(args.roles or ROLES)
    flags = 0 if args.case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(args.query, flags)
    except re.error:
        pattern = re.compile(re.escape(args.query), flags)

    files = sorted(iter_session_files(args.days, args.project), key=lambda t: t[1].stat().st_mtime, reverse=True)
    if not files:
        print('no sessions found in the given range')
        return

    total = shown = 0
    for proj, f in files:
        matches = search_file(f, pattern, roles, args.labels, args.context)
        if not matches:
            continue
        total += len(matches)
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
        print(f'\n{C_BOLD}{proj}{C_RESET} {C_DIM}{f.name}  (updated {mtime}, {len(matches)} matches){C_RESET}')
        for m in matches:
            if shown >= args.limit:
                break
            color = ROLE_COLORS[m.role]
            tag = f'{m.role}' + (f'/{m.detail}' if m.detail else '')
            header = f'\n{C_BLUE}{m.timestamp}{C_RESET} {color}[{tag}]{C_RESET}'
            if m.detail.startswith('tool_use:'):
                print(f'{header}\n{m.snippet}')
            elif '\n' in m.snippet:
                body = '\n'.join('      ' + ln for ln in m.snippet.split('\n'))
                print(f'{header}\n{body}')
            else:
                print(f'{header} {m.snippet}')
            shown += 1
        if shown >= args.limit:
            break

    print(
        f'\n{C_BOLD}{total} matches{C_RESET} in {len(files)} sessions scanned'
        + (f' (showing first {args.limit})' if total > args.limit else '')
    )


if __name__ == '__main__':
    main()

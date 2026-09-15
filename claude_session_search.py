#!/usr/bin/env python3
"""Search text in recent Claude Code sessions.

Examples:
    python3 claude_session_search.py grafana
    python3 claude_session_search.py -d 3 -r user -r assistant "netdata"
    python3 claude_session_search.py -d 14 -r tool --project breeze "curl"

List sessions of a project (newest first) with ID and the first prompt.
Sessions whose transcript was removed by Claude Code's cleanup (cleanupPeriodDays,
default 30) are recovered from ~/.claude/history.jsonl and marked [history only]:
    python3 claude_session_search.py -L ~/Code/tenderbuddy
    python3 claude_session_search.py -L . -d 30 --full
    python3 claude_session_search.py -L tenderbuddy -n 1000   # substring match on project dir names

Show one session (by ID or ID prefix) with its whole first prompt, also recovered from
~/.claude/history.jsonl when the transcript is gone:
    python3 claude_session_search.py -s 6713db6f-1959-41e0-aa93-7540895709b0
    python3 claude_session_search.py -s 6713db6f
"""

import argparse
import glob
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
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        '-L',
        '--list',
        nargs='?',
        const='.',
        metavar='PATH',
        help='list sessions of the project at PATH (default: cwd) newest first, with session ID and first prompt; '
        'PATH may also be a substring of a project dir name',
    )
    mode.add_argument(
        '-s',
        '--session',
        metavar='ID',
        help='show the session with this ID (or ID prefix): project, stats and its whole first prompt',
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
    if args.list is None and args.session is None and args.query is None:
        p.error('query is required unless --list or --session is given')
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
#
# Two sources: transcripts under ~/.claude/projects/<encoded-path>/<session>.jsonl
# (removed by Claude Code after `cleanupPeriodDays`, default 30) and the global
# ~/.claude/history.jsonl, which keeps every typed prompt with its project path
# and sessionId and is never cleaned up. Transcripts win; history fills the gaps.

HISTORY_FILE = Path.home() / '.claude' / 'history.jsonl'
HISTORY_GAP_MS = 2 * 3600 * 1000  # rows without sessionId (pre 2025-11) are split into sessions on this gap
PASTE_CACHE_DIR = Path.home() / '.claude' / 'paste-cache'  # pasted text of newer history rows, by contentHash


@dataclass
class SessionInfo:
    session_id: str  # '' when unknown (old history rows)
    started: str  # ISO timestamp of the first prompt ('' if none)
    first_prompt: str
    prompts: int  # number of human prompts
    source: str  # 'transcript' | 'history'
    updated: str = ''  # ISO timestamp of last activity
    size: int | None = None  # transcript size in bytes


def encode_project_path(path: str) -> str:
    """Map an absolute project path to its dir name under ~/.claude/projects."""
    return re.sub(r'[^A-Za-z0-9-]', '-', path)


def ms_to_iso(ts_ms: int | float) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).isoformat()


def load_history() -> dict[str, list[dict]]:
    """history.jsonl rows grouped by encoded project name, in file (chronological) order."""
    by_project: dict[str, list[dict]] = {}
    if not HISTORY_FILE.is_file():
        return by_project
    with open(HISTORY_FILE, errors='replace') as fp:
        for line in fp:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get('project') and 'display' in row:
                by_project.setdefault(encode_project_path(row['project']), []).append(row)
    return by_project


def resolve_project_keys(arg: str, history: dict[str, list[dict]]) -> list[str]:
    """Encoded project names matching `arg` (a path, or a substring of a name)."""
    known = {d.name for d in PROJECTS_DIR.iterdir() if d.is_dir()} if PROJECTS_DIR.is_dir() else set()
    known |= history.keys()
    p = Path(arg).expanduser()
    if p.is_dir():
        key = encode_project_path(str(p.resolve()))
        if key in known:
            return [key]
        sys.exit(f'no sessions recorded for {p.resolve()} (neither {PROJECTS_DIR / key} nor {HISTORY_FILE})')
    hits = sorted(k for k in known if arg.lower() in k.lower())
    if not hits:
        sys.exit(f'no project matches {arg!r} in {PROJECTS_DIR} or {HISTORY_FILE}')
    return hits


_TAG_BLOCKS = re.compile(r'<(system-reminder|command-message|ide_opened_file|ide_selection)>.*?</\1>\s*', re.S)
_COMMAND = re.compile(r'<command-name>(.*?)</command-name>\s*(?:<command-args>(.*?)</command-args>)?', re.S)


def clean_prompt(text: str) -> str:
    """Strip harness-injected wrappers so the user's own words remain."""
    text = _TAG_BLOCKS.sub('', text)
    text = _COMMAND.sub(lambda m: f'{m.group(1).strip()} {(m.group(2) or "").strip()}'.strip(), text)
    return text.strip()


_PASTE_REF = re.compile(r'\[Pasted text #(\d+)(?: \+\d+ lines)?\]')


def expand_pasted(display: str, pasted: dict) -> str:
    """Put pasted text back into a history row's `display`, which only keeps `[Pasted text #N +M lines]`.

    The text is inline in pastedContents, or (newer rows) in paste-cache/<contentHash>.txt, which
    Claude Code cleans up as well; placeholders that can't be resolved are kept as is.
    """

    def repl(m: re.Match) -> str:
        item = pasted.get(m.group(1)) or {}
        if 'content' in item:
            return item['content']
        cached = PASTE_CACHE_DIR / f'{item.get("contentHash")}.txt'
        return cached.read_text(errors='replace') if item.get('contentHash') and cached.is_file() else m.group(0)

    return _PASTE_REF.sub(repl, display)


def human_prompt_text(record: dict) -> str | None:
    """Return the text of a user record if it is a prompt typed by the human, else None."""
    if record.get('type') != 'user' or record.get('isSidechain') or record.get('isMeta'):
        return None  # isMeta: harness-injected, e.g. the <local-command-caveat> before a /command
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
    st = path.stat()
    return SessionInfo(path.stem, started, first, prompts, 'transcript', ms_to_iso(st.st_mtime * 1000), st.st_size)


def history_sessions(rows: list[dict]) -> list[SessionInfo]:
    """Group history rows (chronological) into sessions."""
    groups: dict[str, list[dict]] = {}
    anon = 0
    for row in rows:
        sid = row.get('sessionId') or ''
        if not sid:
            prev = groups.get(f'\0{anon}')
            if prev is None or row['timestamp'] - prev[-1]['timestamp'] > HISTORY_GAP_MS:
                anon += 1
            sid = f'\0{anon}'
        groups.setdefault(sid, []).append(row)
    infos = []
    for sid, grp in groups.items():
        first = next((r for r in grp if not r['display'].startswith('/')), grp[0])
        infos.append(
            SessionInfo(
                '' if sid.startswith('\0') else sid,
                ms_to_iso(grp[0]['timestamp']),
                clean_prompt(expand_pasted(first['display'], first.get('pastedContents') or {})),
                len(grp),
                'history',
                ms_to_iso(grp[-1]['timestamp']),
            )
        )
    return infos


def merge_sessions(transcripts: list[SessionInfo], history: list[SessionInfo]) -> list[SessionInfo]:
    """Transcript info wins; history adds sessions whose transcript is gone."""
    seen = {t.session_id for t in transcripts}
    return transcripts + [h for h in history if h.session_id not in seen]


def fmt_datetime(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M')
    except (ValueError, AttributeError):
        return '?'


def human_size(n: float) -> str:
    for unit in ('B', 'K', 'M', 'G'):
        if n < 1024 or unit == 'G':
            return f'{n:.0f}{unit}' if unit == 'B' else f'{n:.1f}{unit}'
        n /= 1024
    return f'{n:.1f}G'


PROMPT_LINE_LEN = 240


def print_session(info: SessionInfo, full: bool):
    sid = info.session_id or '(unknown session id)'
    meta = f'{info.prompts} prompts, updated {fmt_datetime(info.updated)}'
    if info.size is not None:
        meta = f'{info.prompts} prompts, {human_size(info.size)}, updated {fmt_datetime(info.updated)}'
    tag = '' if info.source == 'transcript' else f' {C_DIM}[history only]{C_RESET}'
    print(f'\n{C_BLUE}{fmt_datetime(info.started)}{C_RESET}  {C_BOLD}{sid}{C_RESET}  {C_GRAY}{meta}{C_RESET}{tag}')
    prompt = info.first_prompt or f'{C_DIM}(no prompt){C_RESET}'
    if full:
        print('\n'.join('    ' + ln for ln in prompt.splitlines()))
    else:
        one = prompt.replace('\n', '⏎')
        if len(one) > PROMPT_LINE_LEN:
            one = one[:PROMPT_LINE_LEN] + '…'
        print(f'    {one}')


def list_sessions(args):
    cutoff_iso = ms_to_iso((time.time() - args.days * 86400) * 1000) if args.days else ''
    history = load_history()
    shown = 0
    for key in resolve_project_keys(args.list, history):
        proj_dir = PROJECTS_DIR / key
        transcripts = [session_info(f) for f in proj_dir.glob('*.jsonl')] if proj_dir.is_dir() else []
        infos = merge_sessions(transcripts, history_sessions(history.get(key, [])))
        infos = [i for i in infos if i.updated >= cutoff_iso]
        infos.sort(key=lambda i: i.started, reverse=True)
        n_hist = sum(1 for i in infos if i.source == 'history')
        print(f'{C_BOLD}{key}{C_RESET} {C_DIM}({len(infos)} sessions, {len(infos) - n_hist} with transcript){C_RESET}')
        for info in infos:
            if shown >= args.limit:
                print(f'\n{C_DIM}… limit of {args.limit} sessions reached, use -n to show more{C_RESET}')
                break
            print_session(info, args.full)
            shown += 1
        print()


# ---------------------------------------------------------------------------
# --session mode: same two sources as --list, looked up by session ID


def find_sessions(prefix: str) -> list[tuple[str, SessionInfo]]:
    """Sessions whose ID starts with `prefix`, as (project key, info); a transcript wins over history rows."""
    found = []
    if PROJECTS_DIR.is_dir():
        found = [(f.parent.name, session_info(f)) for f in PROJECTS_DIR.glob(f'*/{glob.escape(prefix)}*.jsonl')]
    seen = {info.session_id for _, info in found}
    for key, rows in load_history().items():
        rows = [r for r in rows if (r.get('sessionId') or '').startswith(prefix)]
        found += [(key, info) for info in history_sessions(rows) if info.session_id not in seen]
    return sorted(found, key=lambda t: t[1].started, reverse=True)


def show_sessions(args):
    found = find_sessions(args.session)
    if not found:
        sys.exit(
            f'no session matches {args.session!r} in {PROJECTS_DIR} or {HISTORY_FILE} '
            '(a session that never received a prompt leaves no record)'
        )
    for key, info in found[: args.limit]:
        print(f'{C_BOLD}{key}{C_RESET}')
        print_session(info, full=True)
        print()


def main():
    args = parse_args()
    if args.list is not None:
        list_sessions(args)
        return
    if args.session is not None:
        show_sessions(args)
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

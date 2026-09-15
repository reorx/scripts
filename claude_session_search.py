#!/usr/bin/env python3
"""Search, list and inspect Claude Code sessions. The manual is MANUAL below, printed by --help."""

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

MANUAL = r"""NAME
       claude_session_search.py - search, list and inspect Claude Code sessions

SYNOPSIS
       claude_session_search.py [-d DAYS] [-p SUBSTRING] [-r ROLE]...
                                [-l SUBSTRING]... [--case-sensitive]
                                [-C CHARS] [-n LIMIT] QUERY
       claude_session_search.py -L [PATH] [-d DAYS] [-n LIMIT] [--full]
       claude_session_search.py -s ID [-n LIMIT]
       claude_session_search.py -h | --help

DESCRIPTION
       claude_session_search.py reads the session data Claude Code keeps under
       ~/.claude and works in one of three modes:

       search mode (default)
              Find QUERY in the messages of recently active sessions and
              print every match with its time, role and surrounding text.

       list mode (-L)
              List the sessions of a project, newest first, each with its
              session ID, a few stats and its first prompt.

       session mode (-s)
              Show the session with a given ID or ID prefix, together with
              its project and its complete first prompt.

       Claude Code deletes transcripts whose last activity is older than its
       cleanupPeriodDays setting (default 30 days), but never cleans up
       ~/.claude/history.jsonl, its log of every prompt you typed. Search
       mode reads transcripts only. List and session modes read the history
       too, so sessions whose transcript is gone still show up there, marked
       [history only].

       Options that do not apply to the selected mode are ignored.

OPTIONS
   Search mode
       QUERY
              A Python regular expression, matched against the text of each
              message piece (see --role). A QUERY that is not a valid regular
              expression is matched as literal text, so '[Image #1' needs no
              escaping. Quote QUERY to protect it from the shell.

       -d, --days DAYS
              Only scan transcripts modified within the last DAYS days.
              Fractions are allowed (0.25 is 6 hours); 0 scans every
              transcript on disk. Default: 7.

       -p, --project SUBSTRING
              Only scan projects whose directory name contains SUBSTRING,
              ignoring case. The directory name is the project path with
              every character other than a letter, digit or "-" replaced by
              "-": sessions started in /Users/me/Code/campus_watch are stored
              in ~/.claude/projects/-Users-me-Code-campus-watch, so write
              campus-watch, not campus_watch.

       -r, --role ROLE
              Only search message pieces of ROLE, which is one of:

                  user       text of user messages: your prompts, and what
                             Claude Code adds on your behalf, such as
                             system reminders and command output
                  assistant  Claude's replies and thinking
                  tool       tool calls (their input) and tool results

              Repeat the option to search several roles. Default: all three.

       -l, --label SUBSTRING
              Only keep matches whose label contains SUBSTRING, ignoring case.
              Repeat the option to accept several labels. The label follows
              the role in the output, as in [tool/tool_use:Bash]:

                  thinking         Claude's thinking, if its text was saved
                  tool_use:NAME    the input of a call to the tool NAME, e.g.
                                   tool_use:Bash, tool_use:Edit, tool_use:Read
                  tool_result      the output a tool returned

              Prompts and replies have no label, so any -l leaves them out.
              -l tool_use accepts calls to all tools; -l tool accepts tool
              results as well.

       --case-sensitive
              Match QUERY case-sensitively. Default: ignore case.

       -C, --context CHARS
              Show CHARS characters on each side of a match. Default: 80.

       -n, --limit LIMIT
              Stop after printing LIMIT matches. Default: 200.

   List mode
       -L, --list [PATH]
              List the sessions of a project instead of searching. Without
              PATH, the project is the current directory. If a directory
              exists at PATH (relative paths and ~ are resolved), it must be
              the directory the sessions were started in. Otherwise PATH is a
              substring of project directory names, matched as described
              under --project; it can select several projects, such as a
              repository and its worktrees, which are listed one after the
              other.

       -d, --days DAYS
              Only list sessions whose last activity lies within the last DAYS
              days. Default: no limit.

       -n, --limit LIMIT
              Stop after LIMIT sessions, counted across all listed projects.
              Default: 200.

       --full
              Print first prompts in full, keeping their line breaks. By
              default a first prompt is joined into one line, with ⏎ marking
              the line breaks, and cut after 240 characters.

   Session mode
       -s, --session ID
              Show the session whose ID is ID or starts with ID; the first 8
              characters are practically always enough. Transcript file names
              in all projects and the session IDs recorded in the history are
              looked up. When several sessions match, all of them are shown,
              newest first. The first prompt is always printed in full.

       -n, --limit LIMIT
              Show at most LIMIT sessions. Default: 200.

   General
       -h, --help
              Print this manual and exit.

OUTPUT
       All modes print ANSI colors, even when the output is not a terminal
       (see NOTES). Times are in the local time zone.

   Search mode
       Transcripts are scanned newest first. Each transcript with matches
       gets a header naming the project directory, the transcript file (the
       session ID plus .jsonl), when it was last modified and how many
       matches it has. Its matches follow in conversation order:

           PROJECT-DIR SESSION-ID.jsonl  (updated TIME, N matches)

           MM-DD HH:MM [ROLE/LABEL] …text before MATCH text after…

       The first match in a message piece is shown with CHARS characters of
       context (-C) on each side; "…" marks cut text and "⏎" a line break.
       A tool call is shown on several lines instead: its description as
       "# ..." and its shell command as "$ ...", both in full and with every
       match highlighted, then its other input fields as "field: value",
       cut around the match when longer than 300 characters. Commands with
       a line longer than 80 characters are reformatted by shfmt -i 2 if
       shfmt(1) is installed.

       A summary comes last:

           N matches in M sessions scanned (showing first LIMIT)

       M is the number of transcripts within DAYS. Scanning stops once LIMIT
       matches have been printed, so N then only counts the matches found
       up to that point.

   List mode
       Each project gets a header with the number of sessions listed and how
       many of them still have a transcript, followed by two lines per
       session:

           PROJECT-DIR (N sessions, M with transcript)

           STARTED  SESSION-ID  N prompts, SIZE, updated TIME [history only]
               FIRST PROMPT

       STARTED
              Time of the first prompt.

       SESSION-ID
              The session's UUID, as accepted by -s and claude --resume.
              Prompts from before the history recorded session IDs (about
              2025-11) are grouped into sessions wherever two prompts are
              more than two hours apart, and shown as (unknown session id).

       N prompts
              Number of prompts you sent (see FIRST PROMPT).

       SIZE
              Size of the transcript; absent for history-only sessions.

       updated TIME
              Last activity: the modification time of the transcript, or the
              time of the last prompt for history-only sessions.

       [history only]
              The transcript has been deleted; the session was recovered
              from ~/.claude/history.jsonl.

       FIRST PROMPT
              On one line, or in full with --full.

   Session mode
       Like list mode, except that each session is preceded by its project
       directory and the first prompt is always printed in full. When no
       session matches, the reason is printed to standard error and the exit
       status is 1.

FIRST PROMPT
       The first prompt of a session is the first message you typed in it.
       How it is found depends on where the session comes from.

       From a transcript
              The first user message that is none of: a message of a
              subagent (sidechain), a tool result, the attachment record that
              follows an image, or text injected by Claude Code (isMeta), such
              as the <local-command-caveat> written before a slash command.
              Wrappers like <system-reminder>, <command-message>,
              <ide_opened_file> and <ide_selection> are removed, and a slash
              command is shown as "/name args". Slash commands count as
              prompts, so a session started by /clear shows /clear. The
              prompt count follows the same rules.

       From the history
              The first prompt that does not start with "/", or the very
              first one if all of them do; the prompt count is the number of
              prompts recorded. The history keeps pasted text apart from the
              prompt, which only holds a placeholder such as
              [Pasted text #1 +12 lines]. Placeholders are replaced by the
              pasted text, stored in the history itself or, for newer
              prompts, in ~/.claude/paste-cache. Placeholders whose text has
              been cleaned up stay as they are. Images are never stored.

EXIT STATUS
       0
              Success, including a search that finds nothing.

       1
              ~/.claude/projects does not exist (search mode), no project
              matches PATH (-L), or no session matches ID (-s). The reason is
              printed to standard error.

       2
              Invalid command line.

FILES
       ~/.claude/projects/PROJECT-DIR/SESSION-ID.jsonl
              Transcript of a session, stored under the directory of the
              project it was started in. Read by all modes. Transcripts of
              subagents, in PROJECT-DIR/SESSION-ID/subagents/, are not read.

       ~/.claude/history.jsonl
              Every prompt typed into Claude Code, with its project path,
              time, pasted text and, since about 2025-11, session ID. Read by
              list and session modes.

       ~/.claude/paste-cache/HASH.txt
              Pasted text of newer prompts in the history. Old entries are
              removed, like transcripts. Read by list and session modes.

HISTORY
       2026-07-19
              Search mode: role, label, project and time filters, context
              size, regular expressions that fall back to literal text, and
              tool calls shown as description plus full command, reformatted
              with shfmt.

       2026-09-08
              List mode (-L): the sessions of a project with ID, stats and
              first prompt. Sessions whose transcript has been deleted are
              recovered from ~/.claude/history.jsonl. QUERY became optional
              and the default of --days depends on the mode.

       2026-09-15
              Session mode (-s): look up a session by ID or ID prefix. Pasted
              text in prompts from the history is expanded, and text injected
              by Claude Code is no longer taken for the first prompt. -h and
              --help print this manual.

NOTES
       Color codes are printed even when the output goes to a pipe or a
       file. Page long output with less -R, or strip the codes with sed:

           claude_session_search.py -L | less -R
           claude_session_search.py -s 2149bb6d | sed 's/\x1b\[[0-9;]*m//g'

       Only the Python standard library (3.10 or later) is needed; shfmt is
       optional.

BUGS
       Search mode reads neither the history nor subagent transcripts, so it
       cannot find text in sessions whose transcript has been deleted, or
       text that only appears inside a subagent's own conversation.

       Claude Code saves most thinking blocks without their text, so
       -l thinking finds only the few that kept it.

       A session that never received a prompt leaves neither a transcript
       nor a history entry, so -s cannot find it, even when a tool such as
       herdr reports its ID.

       CLAUDE_CONFIG_DIR is ignored; data is always read from ~/.claude.

EXAMPLES
   Search
       claude_session_search.py grafana
              Find "grafana" in any message of the sessions active in the
              last 7 days.

       claude_session_search.py 'envops (show|copy|set|list-keys)'
              QUERY is a regular expression; quote it for the shell.

       claude_session_search.py '[Pasted text'
              Not a valid regular expression, so it is searched literally.

       claude_session_search.py --case-sensitive -d 30 TODO
              Match case-sensitively, in the last 30 days.

       claude_session_search.py -d 3 -r user -r assistant worktree
              Only prompts and Claude's replies of the last 3 days, not tool
              calls or tool output.

       claude_session_search.py -r user -d 0 -n 50 resume
              Only the user side of all transcripts on disk; stop after 50
              matches.

       claude_session_search.py -l tool_use:Bash 'docker compose'
              Only shell commands Claude ran; each match shows the command's
              description and the whole command.

       claude_session_search.py -l tool_use:Edit -l tool_use:Write parse_args
              Only file edits and file writes that contain "parse_args".

       claude_session_search.py -l tool_result -C 200 Traceback
              Only tool output, with 200 characters of context.

       claude_session_search.py -l thinking -d 30 'the user'
              Only Claude's thinking, over 30 days, since few thinking blocks
              keep their text (see BUGS).

       claude_session_search.py -p tenderbuddy -d 14 curl
              Only projects whose directory name contains "tenderbuddy", its
              worktrees included, in the last 14 days.

       claude_session_search.py -d 0.25 migration
              Only transcripts modified in the last 6 hours.

   List
       claude_session_search.py -L
              The sessions of the project in the current directory.

       claude_session_search.py -L ~/Code/tenderbuddy
              The sessions started in ~/Code/tenderbuddy.

       claude_session_search.py -L vibe-reader-hn
              Every project whose directory name contains "vibe-reader-hn":
              the repository, its worktrees and vibe-reader-hn-chrome, one
              block each.

       claude_session_search.py -L campus-watch
              The substring form for ~/Code/campus_watch, which also matches
              ~/Code/anyun-campus-watch; -L campus_watch finds nothing,
              because "_" is stored as "-".

       claude_session_search.py -L . -d 30 --full
              Sessions active in the last 30 days, with complete first
              prompts.

       claude_session_search.py -L tenderbuddy -n 1000
              Raise the limit of 200 sessions to reach older ones.

   Session
       claude_session_search.py -s aac00ccd-6495-4264-98de-13e9a1fa7c2b
              Show a session by its full ID.

       claude_session_search.py -s 2149bb6d
              Show a session by an ID prefix. Its transcript is gone, so it
              is recovered from the history, pasted text included.

   Workflows
       Find where something was done, check what that session was about,
       then resume it from its project directory with the full ID that -s
       prints:

           claude_session_search.py -d 30 -l tool_use:Bash 'rsync -a'
           claude_session_search.py -s 7bb051d3
           cd ~/Code/campus_watch && claude --resume SESSION-ID

       Recall what you asked in the current project during the last week:

           claude_session_search.py -L -d 7 --full | less -R

SEE ALSO
       claude --help, for claude --resume and claude --continue; the Claude
       Code settings documentation, for cleanupPeriodDays; shfmt(1), less(1).
"""

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


_MAN_HEADING = re.compile(r'^((?:   )?)(\S.*)$', re.M)  # section (column 0) or subsection (column 3) heading
_MAN_TAG = re.compile(r'^( {7})(\S.*)$(?=\n {14}\S)', re.M)  # tag of a paragraph indented below it


def print_manual():
    """Print MANUAL; on a terminal, headings and paragraph tags are bold as in man(1)."""
    text = MANUAL
    if sys.stdout.isatty():
        for pattern in (_MAN_HEADING, _MAN_TAG):
            text = pattern.sub(rf'\1{C_BOLD}\2{C_RESET}', text)
    print(text, end='')


class ManualAction(argparse.Action):
    """-h/--help: print the manual and exit at once, like argparse's own help action."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, default=argparse.SUPPRESS, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print_manual()
        parser.exit()


def build_parser() -> argparse.ArgumentParser:
    # options are documented in MANUAL, keep the two in sync
    p = argparse.ArgumentParser(usage='%(prog)s QUERY | -L [PATH] | -s ID  [options]  (see --help)', add_help=False)
    p.add_argument('-h', '--help', action=ManualAction)
    p.add_argument('query', nargs='?')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('-L', '--list', nargs='?', const='.', metavar='PATH')
    mode.add_argument('-s', '--session', metavar='ID')
    p.add_argument('-d', '--days', type=float)
    p.add_argument('-r', '--role', action='append', choices=ROLES, dest='roles')
    p.add_argument('-p', '--project')
    p.add_argument('-l', '--label', action='append', dest='labels')
    p.add_argument('--case-sensitive', action='store_true')
    p.add_argument('-C', '--context', type=int, default=80)
    p.add_argument('-n', '--limit', type=int, default=200)
    p.add_argument('--full', action='store_true')
    return p


def parse_args():
    p = build_parser()
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

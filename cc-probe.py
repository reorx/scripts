#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Capture the first request Claude Code sends and report what it carries.

Runs `claude -p` with ANTHROPIC_BASE_URL pointed at a local server that records the first
/v1/messages request and answers 400, so no model runs and no usage is spent. The request is
split into named items (system prompt sections, tools, deferred tool names, skills by source,
agents, CLAUDE.md files, MCP instructions, other context), and the runtime state is read from
it: version, model, effort, thinking, fast mode, permission mode, Artifact, claude.ai skills,
git snapshot, MCP servers.

Tokens: the total comes from Anthropic's free count_tokens endpoint, called with the login
Claude Code sent (only an Anthropic credential, kept in memory, never printed or saved), and
items are scaled from their size. Scaling uses the request's average characters per token,
so text denser in tokens than that (Chinese, for one) comes out low: `--count exact` counts
each item by removing it (one count_tokens call per item, ~20 s). `--count offline` uses 3.5
characters per token and makes no call.

    cc-probe.py                                   # what `claude` sends from this directory
    cc-probe.py --via cl                          # through a zsh function from ~/.zshrc_fn
    cc-probe.py --via 'with-artifact cl' --all    # every item, not only the largest
    cc-probe.py --all --kind 'skill*'             # just the skill listing
    cc-probe.py --no-mcp --no-hooks               # skip MCP servers and hooks
    cc-probe.py --save a.json && ... && cc-probe.py diff a.json b.json
    cc-probe.py --via cl --expect-absent Artifact --max-tokens 40000   # exit 1 when not met
    cc-probe.py -- --model sonnet                 # anything after -- goes to claude

HERDR_* variables are dropped so the herdr SessionStart hook leaves the current pane alone.
CLAUDE_CODE_ARTIFACT=1 is set because headless runs leave Artifact out while interactive
sessions load it (`--headless` skips this). MCP servers that connect after the first request
is sent are missing from it, as they would be from an interactive session's first turn.
"""

import argparse
import copy
import fnmatch
import http.server
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CHARS_PER_TOKEN = 3.5
PROMPT = 'say ok'
DEFAULT_RC = '~/.zshrc_fn'
LIST_HEADERS = {
    'The following deferred tools': 'deferred',
    'Available agent types': 'agent',
    'The following skills are available': 'skill',
}
LIST_ITEM = {
    'skill': re.compile(r'- (\S+?)(?::(?: |$)|$)'),
    'agent': re.compile(r'- (.+?):(?: |$)'),
}
# Only these settings keys and env switches are read from settings.json and shown;
# the env block can hold secrets, so nothing outside the list is printed.
SETTINGS_KEYS = [
    'model',
    'effortLevel',
    'enableArtifact',
    'disableArtifact',
    'syncClaudeAiSkills',
    'syncClaudeAiPlugins',
    'disableClaudeAiConnectors',
    'includeGitInstructions',
    'attribution',
    'promptSuggestionEnabled',
    'awaySummaryEnabled',
    'autoCompactWindow',
    'skillOverrides',
    'deniedMcpServers',
]
SWITCH_ENV = [
    'CLAUDE_CODE_DISABLE_ARTIFACT',
    'CLAUDE_CODE_ARTIFACT',
    'CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT',
    'CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS',
    'CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION',
    'CLAUDE_CODE_USE_POWERSHELL_TOOL',
    'CLAUDE_CODE_DISABLE_CRON',
    'CLAUDE_CODE_DISABLE_BUNDLED_SKILLS',
    'CLAUDE_CODE_DISABLE_ADVISOR_TOOL',
    'CLAUDE_CODE_AUTO_COMPACT_WINDOW',
    'ENABLE_TOOL_SEARCH',
]
FORWARD_HEADERS = ('authorization', 'x-api-key', 'anthropic-beta', 'anthropic-version', 'user-agent', 'x-app')


class ProbeError(Exception):
    pass


class CountError(Exception):
    pass


@dataclass
class Item:
    kind: str
    name: str | None
    loc: tuple  # ('tool', name) | ('system', block) | ('message', message, block)
    start: int = 0
    end: int = 0
    chars: int = 0
    source: str | None = None
    tokens: int = 0

    def public(self):
        out = {'kind': self.kind, 'name': self.name, 'chars': self.chars, 'tokens': self.tokens}
        if self.source:
            out['source'] = self.source
        return out


def config_dir():
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')


# ---------- capture ----------


class FakeApi:
    """Stands in for the API on 127.0.0.1: records every request and answers each with 400."""

    def __init__(self):
        self.requests = []
        seen = self.requests

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, self.read_body()))
                body = b'{"type":"error","error":{"type":"invalid_request_error","message":"captured by cc-probe"}}'
                self.send_response(400)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.send_response(404)
                self.send_header('content-length', '0')
                self.end_headers()

            def read_body(self):
                if 'chunked' not in (self.headers.get('transfer-encoding') or ''):
                    return self.rfile.read(int(self.headers.get('content-length') or 0))
                out = b''
                while size := int(self.rfile.readline().strip() or b'0', 16):
                    out += self.rfile.read(size)
                    self.rfile.readline()
                self.rfile.readline()
                return out

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def close(self):
        self.httpd.shutdown()

    def first_request(self):
        for path, headers, body in self.requests:
            if '/v1/messages' not in path or 'count_tokens' in path:
                continue
            req = json.loads(body)
            if req.get('system'):
                return req, headers
        return None, None


def claude_args(opts):
    args = ['-p', '--no-session-persistence']
    if opts.no_mcp:
        args.append('--strict-mcp-config')
    settings = json.loads(opts.settings) if opts.settings else {}
    if opts.no_hooks:
        settings['disableAllHooks'] = True
    if settings:
        args += ['--settings', json.dumps(settings)]
    return args + opts.claude_args + [PROMPT]


def launch_command(opts, args):
    if not opts.via:
        return ['claude', *args]
    rc = os.path.expanduser(opts.rc)
    return ['zsh', '-f', '-c', f'source {shlex.quote(rc)}; {opts.via} "$@"', 'cc-probe', *args]


def child_env(opts, base_url):
    env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_') and k not in opts.unset}
    if not opts.headless and 'CLAUDE_CODE_ARTIFACT' not in opts.unset:
        env.setdefault('CLAUDE_CODE_ARTIFACT', '1')
    env.update(dict(kv.split('=', 1) for kv in opts.env))
    env['ANTHROPIC_BASE_URL'] = base_url
    return env


def capture(opts):
    api = FakeApi()
    try:
        proc = subprocess.run(
            launch_command(opts, claude_args(opts)),
            env=child_env(opts, api.url),
            cwd=opts.cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=opts.timeout,
        )
    finally:
        api.close()
    req, headers = api.first_request()
    if req is None:
        raise ProbeError(f'claude sent no request (exit {proc.returncode})\n{proc.stderr.strip()[-2000:]}')
    return req, headers


# ---------- breakdown ----------


def lines_with_offsets(text):
    """(offset, line, starts_paragraph) for each line."""
    pos, after_blank = 0, True
    for line in text.split('\n'):
        yield pos, line, after_blank
        after_blank = not line.strip()
        pos += len(line) + 1


def segment_name(text):
    if text.startswith('x-anthropic-billing-header'):
        return 'billing header'
    lines = [l.strip() for l in text.split('\n') if l.strip() and l.strip() != '<system-reminder>']
    return (lines[0] if lines else '(blank)')[:60]


def parse_text(text, loc, heading_kind):
    """Cut a prompt text into sections: `# ` headings, MCP servers, listings and their entries,
    loose paragraphs. The items cover the text end to end."""
    cuts, mode = [], None
    for pos, line, para in lines_with_offsets(text):
        if not line.strip():
            continue
        header = next((kind for prefix, kind in LIST_HEADERS.items() if line.startswith(prefix)), None)
        entry = LIST_ITEM[mode].match(line) if mode in LIST_ITEM else None
        if line.startswith('# '):
            name = line[2:].strip()
            mode = 'mcp-head' if name == 'MCP Server Instructions' else 'section'
            cuts.append((pos, heading_kind, name))
        elif line.startswith('## ') and mode in ('mcp-head', 'mcp'):
            mode = 'mcp'
            cuts.append((pos, 'mcp', line[3:].strip()))
        elif header:
            mode = header
            cuts.append((pos, header, 'deferred tool names' if header == 'deferred' else f'({header} list)'))
        elif entry:
            cuts.append((pos, mode, entry.group(1)))
        elif para and mode in (None, 'deferred', 'skill', 'agent'):
            mode = 'section'
            cuts.append((pos, heading_kind, None))
    if not cuts:
        return []
    cuts[0] = (0, *cuts[0][1:])
    items = []
    for i, (start, kind, name) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else len(text)
        items.append(Item(kind, name or segment_name(text[start:end]), loc, start, end, end - start))
    return items


def parse_instructions(text, loc):
    """The CLAUDE.md reminder: one item per `Contents of <path> (...)` file."""
    cuts = [(0, 'context', None)]
    for pos, line, _ in lines_with_offsets(text):
        if m := re.match(r'Contents of (.+?) \(', line):
            cuts.append((pos, 'instructions', m.group(1)))
    items = []
    for i, (start, kind, name) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else len(text)
        if end > start:
            items.append(Item(kind, name or segment_name(text[start:end]), loc, start, end, end - start))
    return items


def block_texts(message):
    content = message.get('content')
    if isinstance(content, str):
        return [content]
    return [b.get('text') if b.get('type') == 'text' else None for b in content or []]


def is_reminder(text):
    s = text.strip()
    return s.startswith('<system-reminder>') and s.endswith('</system-reminder>')


def breakdown(req):
    items = []
    for b, block in enumerate(req.get('system') or []):
        text = block if isinstance(block, str) else block.get('text', '')
        items += parse_text(text, ('system', b), 'system')
    for tool in req.get('tools') or []:
        name = tool.get('name') or tool.get('type')
        kind = 'tool-mcp' if name.startswith('mcp__') else 'tool'
        items.append(Item(kind, name, ('tool', name), chars=len(json.dumps(tool, ensure_ascii=False))))
    for m, message in enumerate(req.get('messages') or []):
        for b, text in enumerate(block_texts(message)):
            if not text:
                continue
            loc = ('message', m, b)
            if 'Codebase and user instructions' in text[:300]:
                items += parse_instructions(text, loc)
            elif message.get('role') == 'system' or is_reminder(text):
                items += parse_text(text, loc, 'context')
            else:
                items.append(Item('prompt', 'prompt', loc, 0, len(text), len(text)))
    return items


def deferred_names(req, items):
    names = []
    for item in items:
        if item.kind == 'deferred':
            names += [l.strip() for l in item_text(req, item).split('\n')[1:] if l.strip()]
    return names


def item_text(req, item):
    if item.loc[0] == 'system':
        block = req['system'][item.loc[1]]
        text = block if isinstance(block, str) else block['text']
    else:
        text = block_texts(req['messages'][item.loc[1]])[item.loc[2]]
    return text[item.start : item.end]


def synced_plugins():
    root = config_dir() / 'plugins' / 'synced'
    if not root.is_dir():
        return set()
    return {p.name for account in root.iterdir() if account.is_dir() for p in account.iterdir() if p.is_dir()}


def skill_source(name, cwd, plugins):
    if name.startswith('('):
        return 'header'
    if name.startswith('anthropic-skills:'):
        return 'claude.ai'
    if ':' in name:
        return 'claude.ai plugin' if name.split(':')[0] in plugins else 'plugin'
    cfg, project = config_dir(), Path(cwd) / '.claude'
    if (cfg / 'skills' / name).exists():
        return 'user'
    if (cfg / 'commands' / f'{name}.md').exists():
        return 'command'
    if (project / 'skills' / name).exists() or (project / 'commands' / f'{name}.md').exists():
        return 'project'
    return 'bundled'


def label_sources(items, cwd):
    plugins = synced_plugins()
    for item in items:
        if item.kind == 'skill':
            item.source = skill_source(item.name, cwd, plugins)
        elif item.kind == 'agent' and ':' in item.name:
            item.source = 'claude.ai plugin' if item.name.split(':')[0] in plugins else 'plugin'


# ---------- counting ----------


def without(req, item):
    """A copy of the request with one item taken out."""
    r = copy.deepcopy(req)
    where = item.loc[0]
    if where == 'tool':
        r['tools'] = [t for t in r['tools'] if (t.get('name') or t.get('type')) != item.loc[1]]
        return r
    if where == 'system':
        block = r['system'][item.loc[1]]
        if isinstance(block, str):
            r['system'][item.loc[1]] = block[: item.start] + block[item.end :]
        else:
            block['text'] = block['text'][: item.start] + block['text'][item.end :]
        r['system'] = [b for b in r['system'] if (b if isinstance(b, str) else b.get('text', '')).strip()]
        return r
    message = r['messages'][item.loc[1]]
    if isinstance(message['content'], str):
        text = message['content'][: item.start] + message['content'][item.end :]
        message['content'] = text if text.strip() else '.'
        return r
    block = message['content'][item.loc[2]]
    block['text'] = block['text'][: item.start] + block['text'][item.end :]
    if not block['text'].strip():
        block['text'] = '.'
        block.pop('cache_control', None)
    return r


class Counter:
    """count_tokens with the credential Claude Code sent, if it is an Anthropic one."""

    def __init__(self, headers):
        auth, key = headers.get('authorization', ''), headers.get('x-api-key', '')
        self.usable = auth.startswith('Bearer sk-ant-') or key.startswith('sk-ant-')
        self.headers = {k: headers[k] for k in FORWARD_HEADERS if k in headers}
        self.headers['content-type'] = 'application/json'
        self.url = os.environ.get('CC_PROBE_API_BASE', 'https://api.anthropic.com').rstrip('/')
        self.url += '/v1/messages/count_tokens?beta=true'

    def count(self, req):
        body = {'model': req['model'], 'messages': req['messages']}
        for key in ('system', 'tools'):
            if req.get(key):
                body[key] = req[key]
        data = json.dumps(body).encode()
        for attempt in range(3):
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(self.url, data=data, headers=self.headers), timeout=60
                ) as resp:
                    return json.load(resp)['input_tokens']
            except urllib.error.HTTPError as e:
                if e.code != 429 and e.code < 500:
                    raise CountError(f'count_tokens {e.code}: {e.read()[:200].decode(errors="replace")}') from e
            time.sleep(1 + attempt)
        raise CountError('count_tokens kept failing (429/5xx)')


def measure(req, headers, items, mode):
    """Fill item tokens and return (total, counting label). Falls back to estimates."""
    chars = sum(i.chars for i in items)
    counter = Counter(headers)
    total, label = None, None
    if mode == 'offline':
        label = 'estimate (offline)'
    elif not counter.usable:
        label = 'estimate (no Anthropic credential to count with)'
    else:
        try:
            total = counter.count(req)
            label = 'count_tokens'
            if mode == 'exact':
                with ThreadPoolExecutor(6) as pool:
                    counts = list(pool.map(lambda i: counter.count(without(req, i)), items))
                for item, n in zip(items, counts):
                    item.tokens = max(0, total - n)
                return total, 'count_tokens (per item)'
        except (CountError, urllib.error.URLError, TimeoutError) as e:
            label = f'estimate ({e})' if total is None else f'count_tokens (total only; items estimated: {e})'
    ratio = total / chars if total else 1 / CHARS_PER_TOKEN
    for item in items:
        item.tokens = round(item.chars * ratio)
    return total if total is not None else round(chars / CHARS_PER_TOKEN), label


# ---------- state ----------


def runtime_state(req, headers, items, deferred):
    tools = req.get('tools') or []
    names = {t.get('name') for t in tools} | set(deferred)
    version = re.search(r'claude-cli/([\w.\-]+)', headers.get('user-agent', ''))
    billing = next((i for i in items if i.name == 'billing header'), None)
    entrypoint = re.search(r'cc_entrypoint=([\w-]+)', item_text(req, billing)) if billing else None
    permission = next(
        (
            s['classifier_context'].get('permission_mode')
            for s in req.get('safeguards') or []
            if isinstance(s, dict) and isinstance(s.get('classifier_context'), dict)
        ),
        None,
    )
    if permission is None:
        # bypass mode sends no permission_mode; the "While <mode> mode is active:" paragraph names it
        mode = next((m for i in items if (m := re.match(r'While (.+?) mode is active', i.name))), None)
        permission = mode.group(1) if mode else None
    mcp = {m.group(1) for n in names if n and (m := re.match(r'mcp__(.+?)__', n))}
    mcp |= {i.name for i in items if i.kind == 'mcp'}
    listed = lambda kind: [i for i in items if i.kind == kind and not i.name.startswith('(')]
    return {
        'version': version.group(1) if version else None,
        'entrypoint': entrypoint.group(1) if entrypoint else None,
        'model': req.get('model'),
        'effort': (req.get('output_config') or {}).get('effort'),
        'thinking': (req.get('thinking') or {}).get('type'),
        'fast': req.get('speed') == 'fast',
        'permission_mode': permission,
        'max_tokens': req.get('max_tokens'),
        'artifact': 'Artifact' in names,
        'claude_ai_skills': sum(i.source == 'claude.ai' for i in items),
        'claude_ai_plugin_items': sum(i.source == 'claude.ai plugin' for i in items),
        'git_snapshot': any(i.kind == 'context' and i.name == 'gitStatus' for i in items),
        'git_attribution': any(i.name.startswith('Attribution for git') for i in items),
        'mcp_servers': sorted(mcp),
        'tools_full': sum(not t.get('defer_loading') for t in tools),
        'tools_deferred': len(deferred),
        'skills': len(listed('skill')),
        'agents': len(listed('agent')),
        'instruction_files': [i.name for i in items if i.kind == 'instructions'],
    }


def user_settings():
    path = config_dir() / 'settings.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    out = {k: data[k] for k in SETTINGS_KEYS if k in data}
    deny = [d for d in (data.get('permissions') or {}).get('deny', []) if re.fullmatch(r'[\w-]+', d)]
    if deny:
        out['permissions.deny'] = deny
    env = {k: v for k, v in (data.get('env') or {}).items() if k in SWITCH_ENV}
    if env:
        out['env'] = env
    return out


def kind_label(item):
    return f'{item.kind}/{item.source}' if item.kind == 'skill' and item.source else item.kind


def build_report(req, headers, items, total, counting, meta):
    deferred = deferred_names(req, items)
    kinds = {}
    for item in items:
        k = kinds.setdefault(kind_label(item), {'kind': kind_label(item), 'items': 0, 'chars': 0, 'tokens': 0})
        k['items'] += 1
        k['chars'] += item.chars
        k['tokens'] += item.tokens
    return {
        'meta': meta,
        'state': runtime_state(req, headers, items, deferred),
        'settings': user_settings(),
        'totals': {'tokens': total, 'chars': sum(i.chars for i in items), 'counting': counting},
        'kinds': sorted(kinds.values(), key=lambda k: -k['tokens']),
        'items': [i.public() for i in items],
        'deferred': deferred,
    }


# ---------- output ----------


def fmt(value):
    if isinstance(value, bool):
        return 'on' if value else 'off'
    if isinstance(value, list):
        return ', '.join(map(str, value)) or '-'
    return '-' if value is None else str(value)


def tilde(path):
    home = str(Path.home())
    return '~' + path[len(home) :] if path and path.startswith(home) else path


def render(report, opts):
    s, t, m = report['state'], report['totals'], report['meta']
    out = [
        f'cc-probe · Claude Code {fmt(s["version"])} ({fmt(s["entrypoint"])}) · '
        f'{"via `" + m["via"] + "`" if m["via"] else "claude"} · {tilde(m["cwd"])}',
        f'model {s["model"]} · effort {fmt(s["effort"])} · thinking {fmt(s["thinking"])} · fast {fmt(s["fast"])} · '
        f'permission {fmt(s["permission_mode"])} · max_tokens {fmt(s["max_tokens"])}',
        '',
        f'Total  {t["tokens"]:,} tokens [{t["counting"]}] · {t["chars"]:,} chars · '
        f'{s["tools_full"]} tools in full, {s["tools_deferred"]} deferred · {s["skills"]} skills · {s["agents"]} agents',
        '',
        'Switches',
        f'  Artifact            {fmt(s["artifact"])}',
        f'  claude.ai skills    {s["claude_ai_skills"]}',
        f'  claude.ai plugins   {s["claude_ai_plugin_items"]} skills/agents',
        f'  git snapshot        {fmt(s["git_snapshot"])}',
        f'  git attribution     {fmt(s["git_attribution"])}',
        f'  MCP servers         {fmt(s["mcp_servers"])}' + ('' if m['mcp'] else '  (--no-mcp)'),
        f'  CLAUDE.md files     {fmt([tilde(p) for p in s["instruction_files"]])}',
        '',
        'By kind',
        f'  {"kind":<24}{"items":>6}{"chars":>10}{"tokens":>9}',
    ]
    out += [f'  {k["kind"]:<24}{k["items"]:>6}{k["chars"]:>10,}{k["tokens"]:>9,}' for k in report['kinds']]
    items = [
        i
        for i in report['items']
        if not opts.kind
        or fnmatch.fnmatchcase(i['kind'] + '/' + i.get('source', ''), opts.kind + '*')
        or fnmatch.fnmatchcase(i['kind'], opts.kind)
    ]
    items.sort(key=lambda i: -i['tokens'])
    title = 'All items' if opts.all else f'Largest items (top {opts.top})'
    if not opts.all:
        items = items[: opts.top]
    out += ['', title, f'  {"tokens":>7} {"chars":>8}  {"kind":<18}name']
    for i in items:
        kind = i['kind'] + (f'/{i["source"]}' if i.get('source') else '')
        out.append(f'  {i["tokens"]:>7,} {i["chars"]:>8,}  {kind:<18}{tilde(i["name"])}')
    if report['settings']:
        out += ['', f'Settings ({tilde(str(config_dir() / "settings.json"))})']
        out += [f'  {k} = {json.dumps(v, ensure_ascii=False)}' for k, v in report['settings'].items()]
    return '\n'.join(out)


def save(path, req, report):
    clean = {k: v for k, v in req.items() if k != 'metadata'}
    Path(path).write_text(json.dumps({'request': clean, 'report': report}, ensure_ascii=False, indent=1))


def check(report, opts):
    names = {i['name'] for i in report['items'] if i['kind'] != 'prompt' and not i['name'].startswith('(')}
    names |= set(report['deferred'])
    failures = []
    for pattern in opts.expect_absent:
        hits = sorted(n for n in names if fnmatch.fnmatchcase(n, pattern))
        if hits:
            failures.append(f'expected no {pattern!r}, found: {", ".join(hits[:8])}')
    for pattern in opts.expect_present:
        if not any(fnmatch.fnmatchcase(n, pattern) for n in names):
            failures.append(f'expected {pattern!r}, found none')
    if opts.max_tokens is not None and report['totals']['tokens'] > opts.max_tokens:
        failures.append(f'{report["totals"]["tokens"]:,} tokens is over --max-tokens {opts.max_tokens:,}')
    return failures


# ---------- diff ----------


def diff_reports(a, b):
    ia = {(i['kind'], i['name']): i for i in a['items']}
    ib = {(i['kind'], i['name']): i for i in b['items']}
    state = {k: [a['state'].get(k), b['state'].get(k)] for k in a['state'] if a['state'].get(k) != b['state'].get(k)}
    changed = [
        {**ib[k], 'tokens_delta': ib[k]['tokens'] - ia[k]['tokens'], 'chars_delta': ib[k]['chars'] - ia[k]['chars']}
        for k in ia
        if k in ib and ia[k]['chars'] != ib[k]['chars']
    ]
    return {
        'state': state,
        'removed': sorted((ia[k] for k in ia if k not in ib), key=lambda i: -i['tokens']),
        'added': sorted((ib[k] for k in ib if k not in ia), key=lambda i: -i['tokens']),
        'changed': sorted(changed, key=lambda i: i['tokens_delta']),
        'tokens': [a['totals']['tokens'], b['totals']['tokens']],
        'tokens_delta': b['totals']['tokens'] - a['totals']['tokens'],
    }


def render_diff(d):
    out = ['state:'] + [f'  {k}: {fmt(v[0])} -> {fmt(v[1])}' for k, v in d['state'].items()] if d['state'] else []
    out.append('items:')
    out += [f'  - {i["kind"]} {i["name"]}  ({-i["tokens"]:+,})' for i in d['removed']]
    out += [f'  + {i["kind"]} {i["name"]}  ({i["tokens"]:+,})' for i in d['added']]
    out += [f'  ~ {i["kind"]} {i["name"]}  ({i["tokens_delta"]:+,})' for i in d['changed']]
    a, b = d['tokens']
    out.append(f'total: {a:,} -> {b:,} tokens ({d["tokens_delta"]:+,})')
    return '\n'.join(out)


# ---------- cli ----------


def parse_capture_args(argv):
    extra = []
    if '--' in argv:
        i = argv.index('--')
        argv, extra = argv[:i], argv[i + 1 :]
    p = argparse.ArgumentParser(prog='cc-probe.py', description='Capture and report what Claude Code sends first.')
    p.add_argument('--via', help='run through this zsh command instead of claude, e.g. "cl" or "with-artifact clfast"')
    p.add_argument('--rc', default=DEFAULT_RC, help=f'zsh file sourced for --via (default {DEFAULT_RC})')
    p.add_argument(
        '--cwd', default=os.getcwd(), help='directory to run claude in (CLAUDE.md and git snapshot depend on it)'
    )
    p.add_argument('--no-mcp', action='store_true', help='skip MCP servers (--strict-mcp-config)')
    p.add_argument('--no-hooks', action='store_true', help='turn hooks off for the probe (disableAllHooks)')
    p.add_argument('--settings', help='settings JSON for this run, merged with --no-hooks into one --settings')
    p.add_argument('--env', action='append', default=[], metavar='K=V', help='set an env var for claude')
    p.add_argument('--unset', action='append', default=[], metavar='K', help='remove an env var for claude')
    p.add_argument('--headless', action='store_true', help='do not set CLAUDE_CODE_ARTIFACT=1')
    p.add_argument('--count', choices=['auto', 'exact', 'offline'], default='auto', help='how to count tokens')
    p.add_argument('--all', action='store_true', help='list every item')
    p.add_argument('--kind', help='only list items of this kind (glob), e.g. "skill*", "tool"')
    p.add_argument('--top', type=int, default=15, help='largest items to list (default 15)')
    p.add_argument('--json', action='store_true', help='print the report as JSON')
    p.add_argument(
        '--save', metavar='FILE', help='save the request (no credentials or account ids) and report for diff'
    )
    p.add_argument(
        '--expect-absent',
        action='append',
        default=[],
        metavar='GLOB',
        help='exit 1 if a tool/skill/agent/MCP name matches',
    )
    p.add_argument('--expect-present', action='append', default=[], metavar='GLOB', help='exit 1 if no name matches')
    p.add_argument('--max-tokens', type=int, help='exit 1 if the total is over this')
    p.add_argument('--timeout', type=float, default=180, help='seconds to wait for claude (default 180)')
    opts = p.parse_args(argv)
    opts.claude_args = extra
    return opts


def run_capture(argv):
    opts = parse_capture_args(argv)
    try:
        req, headers = capture(opts)
    except (ProbeError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f'cc-probe: {e}', file=sys.stderr)
        return 2
    items = breakdown(req)
    label_sources(items, opts.cwd)
    total, counting = measure(req, headers, items, opts.count)
    meta = {
        'via': opts.via,
        'cwd': str(Path(opts.cwd).resolve()),
        'captured_at': datetime.now().isoformat(timespec='seconds'),
        'mcp': not opts.no_mcp,
        'hooks': not opts.no_hooks,
        'claude_args': claude_args(opts),
    }
    report = build_report(req, headers, items, total, counting, meta)
    if opts.save:
        save(opts.save, req, report)
    print(json.dumps(report, ensure_ascii=False, indent=1) if opts.json else render(report, opts))
    failures = check(report, opts)
    for failure in failures:
        print(f'cc-probe: {failure}', file=sys.stderr)
    return 1 if failures else 0


def run_diff(argv):
    p = argparse.ArgumentParser(prog='cc-probe.py diff', description='Compare two captures saved with --save.')
    p.add_argument('a')
    p.add_argument('b')
    p.add_argument('--json', action='store_true')
    opts = p.parse_args(argv)
    a, b = (json.loads(Path(f).read_text())['report'] for f in (opts.a, opts.b))
    d = diff_reports(a, b)
    print(json.dumps(d, ensure_ascii=False, indent=1) if opts.json else render_diff(d))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['diff']:
        return run_diff(argv[1:])
    if argv[:1] == ['capture']:
        argv = argv[1:]
    return run_capture(argv)


if __name__ == '__main__':
    sys.exit(main())

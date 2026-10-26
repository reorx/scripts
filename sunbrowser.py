#!/usr/bin/env python3
"""Run agent-browser inside the running AdsPower Sun Browser.

Usage:
  sunbrowser.py <agent-browser args>   e.g. sunbrowser.py open https://claude.ai/new
  sunbrowser.py --ws                   print the browser's CDP WebSocket URL
  sunbrowser.py --hook                 Claude Code PreToolUse guard for Bash

AdsPower starts Sun Browser with --remote-debugging-port=0, so the CDP port changes on
every launch; it is read from DevToolsActivePort in the profile's user-data-dir.
Commands run with --pin-tab, so the session opens a tab of its own instead of taking over
the user's active tab, and in the `sunbrowser` session unless --session or
AGENT_BROWSER_SESSION names another. `close` closes that tab, then detaches; the browser
keeps running. Set SUNBROWSER_PROFILE to an AdsPower profile id when several are open.

The hook denies Bash commands that open claude.ai with plain agent-browser and points
the agent to this script instead.
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAIN_PROCESS_RE = re.compile(r'^\s*(\d+)\s+.*/SunBrowser\.app/Contents/MacOS/SunBrowser\s(.*)$')
USER_DATA_DIR_RE = re.compile(r'--user-data-dir=(.+?)(?=\s--|$)')
AGENT_BROWSER_RE = re.compile(r'(?:^|[\s;&|(`])agent-browser\b')
CLAUDE_AI_RE = re.compile(r'\bclaude\.ai\b')
DEFAULT_SESSION = 'sunbrowser'
HOOK_REASON = (
    "claude.ai pages are opened in the user's Sun Browser (AdsPower), not in agent-browser's own Chrome. "
    'Pass the same agent-browser arguments to `sunbrowser.py` instead, e.g. '
    '`sunbrowser.py open https://claude.ai/...`, and finish with `sunbrowser.py close`.'
)


class SunBrowserError(Exception):
    pass


@dataclass(frozen=True)
class Instance:
    pid: int
    user_data_dir: str

    @property
    def profile(self):
        # AdsPower names the dir <profile id>_<suffix>
        return Path(self.user_data_dir).name.split('_')[0]


def find_instances(ps_text):
    instances = []
    for line in ps_text.splitlines():
        match = MAIN_PROCESS_RE.match(line)
        if not match or '--type=' in match.group(2):
            continue
        udd = USER_DATA_DIR_RE.search(match.group(2))
        if udd:
            instances.append(Instance(int(match.group(1)), udd.group(1)))
    return instances


def resolve_ws(instances, profile=None):
    if not instances:
        raise SunBrowserError('Sun Browser is not running. Open the profile in AdsPower first.')
    if profile:
        instances = [i for i in instances if profile in (i.profile, Path(i.user_data_dir).name)]
        if not instances:
            raise SunBrowserError(f'No running Sun Browser profile matches SUNBROWSER_PROFILE={profile}.')
    if len(instances) > 1:
        ids = ', '.join(i.profile for i in instances)
        raise SunBrowserError(f'Several Sun Browser profiles are open; set SUNBROWSER_PROFILE to one of: {ids}')
    port_file = Path(instances[0].user_data_dir) / 'DevToolsActivePort'
    if not port_file.exists():
        raise SunBrowserError(f'{port_file} is missing; Sun Browser was started without remote debugging.')
    port, path = port_file.read_text().split()[:2]
    return f'ws://127.0.0.1:{port}{path}'


def plan_commands(args, ws, env):
    base = ['agent-browser', '--cdp', ws, '--pin-tab']
    has_session = any(a == '--session' or a.startswith('--session=') for a in args)
    if not has_session and not env.get('AGENT_BROWSER_SESSION'):
        base += ['--session', DEFAULT_SESSION]
    # Detaching leaves the session's tab open in the user's browser, so close it first
    if args[-1:] == ['close'] and args[-2:-1] != ['tab']:
        return [base + args[:-1] + ['tab', 'close'], base + args]
    return [base + args]


def hook_reason(event):
    if event.get('tool_name') != 'Bash':
        return None
    command = event.get('tool_input', {}).get('command', '')
    if AGENT_BROWSER_RE.search(command) and CLAUDE_AI_RE.search(command) and 'sunbrowser' not in command:
        return HOOK_REASON
    return None


def run_hook(stdin_text):
    try:
        event = json.loads(stdin_text)
    except json.JSONDecodeError:
        return
    reason = hook_reason(event) if isinstance(event, dict) else None
    if reason:
        output = {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}
        print(json.dumps({'hookSpecificOutput': output}))


def current_ws():
    ps = subprocess.run(['ps', '-axww', '-o', 'pid=,command='], capture_output=True, text=True, check=True)
    return resolve_ws(find_instances(ps.stdout), os.environ.get('SUNBROWSER_PROFILE'))


def main(argv):
    if argv[:1] == ['--hook']:
        run_hook(sys.stdin.read())
        return 0
    if argv[:1] in (['-h'], ['--help']):
        print(__doc__.strip())
        return 0
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        ws = current_ws()
    except SunBrowserError as e:
        print(f'sunbrowser: {e}', file=sys.stderr)
        return 1
    if argv == ['--ws']:
        print(ws)
        return 0
    *before, last = plan_commands(argv, ws, os.environ)
    for command in before:
        subprocess.run(command)
    os.execvp(last[0], last)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

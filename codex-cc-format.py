#!/usr/bin/env -S uv run --script
"""Adapt Codex PostToolUse patches to the exact Claude Code cc-format command."""
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
import json
import os
from pathlib import Path
import subprocess
import sys


CLAUDE_COMMAND = r'''jq -r '.tool_input.file_path' | { read file_path; if echo "$file_path" | grep -Eq '\.(py|ts|tsx|js)$'; then cc-format "$file_path"; fi; }'''


def changed_paths(event):
    tool_input = event.get('tool_input', {})
    if event.get('tool_name') in ('Edit', 'MultiEdit', 'Write'):
        return [tool_input['file_path']] if tool_input.get('file_path') else []
    if event.get('tool_name') != 'apply_patch':
        return []
    paths = []
    for line in tool_input.get('command', '').splitlines():
        if line.startswith(('*** Add File: ', '*** Update File: ')):
            paths.append(line.split(': ', 1)[1])
        elif line.startswith('*** Move to: ') and paths:
            paths[-1] = line.removeprefix('*** Move to: ')
    return list(dict.fromkeys(paths))


def main():
    event = json.load(sys.stdin)
    os.chdir(event.get('cwd') or os.getcwd())
    status = 0
    for path in changed_paths(event):
        if not Path(path).is_file():
            continue
        # Keep the extension filter, quoting, PATH resolution and formatter flags
        # in the original command. Only adapt Codex's multi-file input schema.
        result = subprocess.run(
            ['/bin/bash', '-c', CLAUDE_COMMAND],
            input=json.dumps({'tool_input': {'file_path': path}}),
            text=True, stdout=sys.stderr,
        )
        status = result.returncode or status
    return status


if __name__ == '__main__':
    sys.exit(main())

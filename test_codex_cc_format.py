#!/usr/bin/env -S uv run --script
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('codex-cc-format.py')


class HookBehavior(unittest.TestCase):
    def run_hook(self, tool_input, files, expected, tool_name='apply_patch'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in files:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('x=1\n')
            mock = root / 'cc-format'
            mock.write_text('#!/bin/bash\nprintf "%s\\n" "$1" >> "$CALL_LOG"\n')
            mock.chmod(0o755)
            log = root / 'calls'
            result = subprocess.run(
                ['uv', 'run', str(SCRIPT)],
                input=json.dumps({'tool_name': tool_name, 'tool_input': tool_input, 'cwd': directory}),
                text=True, capture_output=True,
                env={**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}', 'CALL_LOG': str(log)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(log.read_text().splitlines() if log.exists() else [], expected)

    def test_create_update_move_delete_and_extension_filter(self):
        patch = '''*** Begin Patch
*** Add File: new.py
+x=1
*** Update File: old.ts
*** Move to: space dir/new.ts
@@
-x
+y
*** Update File: view.tsx
@@
-x
+y
*** Update File: app.js
@@
-x
+y
*** Delete File: gone.py
*** Add File: notes.md
+hello
*** Add File: skip.jsx
+hello
*** End Patch'''
        files = ['new.py', 'space dir/new.ts', 'view.tsx', 'app.js', 'notes.md', 'skip.jsx']
        self.run_hook({'command': patch}, files, files[:4])

    def test_failed_patch_missing_file_is_not_formatted(self):
        self.run_hook({'command': '*** Begin Patch\n*** Add File: missing.py\n+x\n*** End Patch'}, [], [])

    def test_claude_compatible_input(self):
        self.run_hook({'file_path': 'hello.py'}, ['hello.py'], ['hello.py'], 'Write')

    def test_bash_does_not_trigger(self):
        self.run_hook({'command': 'echo x > hello.py'}, ['hello.py'], [], 'Bash')

    def test_embedded_command_is_identical_to_claude(self):
        import runpy
        module = runpy.run_path(str(SCRIPT), run_name='test_module')
        settings = json.loads((Path.home() / '.claude/settings.json').read_text())
        command = next(h['command'] for g in settings['hooks']['PostToolUse'] for h in g['hooks'] if 'cc-format' in h.get('command', ''))
        self.assertEqual(module['CLAUDE_COMMAND'], command)


if __name__ == '__main__':
    unittest.main()

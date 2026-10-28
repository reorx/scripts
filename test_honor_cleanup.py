#!/usr/bin/env -S uv run --script
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('honor-cleanup.py')
FAKE_ADB = """#!/usr/bin/env -S uv run --script
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ['FAKE_STATE'])
with (root / 'calls').open('a') as f:
    f.write(json.dumps(args) + '\\n')
if args == ['devices']:
    print('List of devices attached\\nAB9UUT4510000125\\t' + os.environ.get('DEVICE_STATUS', 'device'))
elif args[-2:] == ['getprop', 'ro.product.model']:
    print(os.environ.get('MODEL', 'ALI-AN00'))
elif 'list' in args:
    print((root / 'packages').read_text())
elif 'uninstall' in args:
    if os.environ.get('FAIL_UNINSTALL'):
        print('Failure [DELETE_FAILED_INTERNAL_ERROR]')
    else:
        p = root / 'packages'
        p.write_text('\\n'.join(x for x in p.read_text().splitlines() if x != 'package:' + args[-1]))
        print('Success')
else:
    sys.exit(2)
"""


class CleanupBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'calls').touch()
        adb = self.root / 'adb'
        adb.write_text(FAKE_ADB)
        adb.chmod(0o755)
        (self.root / 'packages').write_text(
            'package:com.tencent.mm\npackage:com.phoenix.read\npackage:com.unwanted.game\n'
        )
        self.env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ['PATH'], FAKE_STATE=str(self.root))

    def run_script(self, *args):
        return subprocess.run(['uv', 'run', str(SCRIPT), *args], env=self.env, text=True, capture_output=True)

    def calls(self):
        return [json.loads(x) for x in (self.root / 'calls').read_text().splitlines()]

    def test_preview_lists_extra_without_uninstalling(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('com.unwanted.game', result.stdout)
        self.assertFalse(any('uninstall' in x for x in self.calls()))

    def test_apply_removes_only_extra_from_user_zero_and_verifies(self):
        result = self.run_script('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        removals = [x for x in self.calls() if 'uninstall' in x]
        self.assertEqual(
            removals, [['-s', 'AB9UUT4510000125', 'shell', 'pm', 'uninstall', '--user', '0', 'com.unwanted.game']]
        )
        self.assertEqual(sum('list' in x for x in self.calls()), 2)
        self.assertIn('package:com.phoenix.read', (self.root / 'packages').read_text())

    def test_wrong_model_never_mutates(self):
        self.env['MODEL'] = 'OTHER'
        self.assertNotEqual(self.run_script('--apply').returncode, 0)
        self.assertFalse(any('uninstall' in x for x in self.calls()))

    def test_unauthorized_device_never_mutates(self):
        self.env['DEVICE_STATUS'] = 'unauthorized'
        self.assertNotEqual(self.run_script('--apply').returncode, 0)
        self.assertFalse(any('uninstall' in x for x in self.calls()))

    def test_failed_uninstall_is_reported(self):
        self.env['FAIL_UNINSTALL'] = '1'
        result = self.run_script('--apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Failure', result.stderr)

    def test_malformed_package_list_never_mutates(self):
        (self.root / 'packages').write_text('Error: user unavailable')
        self.assertNotEqual(self.run_script('--apply').returncode, 0)
        self.assertFalse(any('uninstall' in x for x in self.calls()))


if __name__ == '__main__':
    unittest.main()

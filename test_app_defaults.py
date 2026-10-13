#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Behavior tests: uv run test_app_defaults.py."""

import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("app_defaults", Path(__file__).with_name("app-defaults.py"))
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


class AppDefaultsBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = app.Target("com.example.tool", "com.example.tool")

    def test_given_an_app_path_when_resolved_then_use_bundle_identifier(self):
        bundle = self.root / "Example.app"
        (bundle / "Contents" / "MacOS").mkdir(parents=True)
        (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "com.example.tool", "CFBundleExecutable": "Example",
        }))
        result = app.resolve_target(str(bundle), "standard")
        self.assertEqual(result.bundle_id, "com.example.tool")
        self.assertEqual(result.executable, (bundle / "Contents/MacOS/Example").resolve())

    def test_given_a_domain_when_no_app_is_installed_then_inspect_still_works(self):
        with patch.object(app, "find_apps", return_value=[]):
            result = app.resolve_target("com.example.tool", "standard")
        self.assertEqual(result.domain, "com.example.tool")
        self.assertIsNone(result.app_path)

    def test_given_ambiguous_app_names_when_resolved_then_require_an_exact_path(self):
        with patch.object(app, "find_apps", return_value=[Path("/A/Tool.app"), Path("/B/Tool.app")]):
            with self.assertRaisesRegex(ValueError, "多个"):
                app.resolve_target("Tool", "standard")

    def test_given_an_unrelated_invalid_info_plist_when_finding_an_app_then_skip_it(self):
        broken = self.root / "Broken.app"
        working = self.root / "Working.app"
        for path in (broken, working):
            (path / "Contents").mkdir(parents=True)
        (broken / "Contents/Info.plist").write_text("not a plist")
        (working / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.example.tool"}))
        with patch.object(app.Path, "glob", return_value=[broken, working]):
            self.assertEqual(app.find_apps("com.example.tool"), [working])

    def test_given_nested_secrets_when_displayed_then_redact_without_hiding_shortcuts(self):
        source = {"provider": {"apiKey": "secret"}, "KeyboardShortcuts_open": "json", "credentials": "hidden"}
        result = app.display_value(source)
        self.assertEqual(result["provider"]["apiKey"], "<redacted>")
        self.assertEqual(result["credentials"], "<redacted>")
        self.assertEqual(result["KeyboardShortcuts_open"], "json")
        self.assertEqual(source["provider"]["apiKey"], "secret")

    def test_given_false_text_when_parsed_then_it_is_false_not_truthy(self):
        self.assertIs(app.parse_value("bool", "false"), False)
        with self.assertRaises(ValueError):
            app.parse_value("bool", "maybe")

    def test_given_nonfinite_float_or_json_null_when_parsed_then_reject_before_writing(self):
        for kind, text in [("float", "nan"), ("json", '{"value": null}')]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                app.parse_value(kind, text)

    def test_given_a_literal_string_when_written_then_pass_it_without_shell_expansion(self):
        value = '$(touch /tmp/never-create) "quoted"'
        with patch.object(app, "read_preferences", side_effect=[{"keep": 7}, {"keep": 7, "message": value}]), \
             patch.object(app, "save_backup", return_value=self.root / "backup.plist") as backup, \
             patch.object(app, "run_command") as command:
            app.set_preference(self.target, "message", "string", value)
        backup.assert_called_once_with(self.target, {"keep": 7})
        self.assertEqual(command.call_args.args[0], ["defaults", "write", self.target.domain, "message", "-string", value])

    def test_given_missing_key_when_deleted_then_do_not_create_a_backup_or_mutate(self):
        with patch.object(app, "read_preferences", return_value={}), \
             patch.object(app, "save_backup") as backup, patch.object(app, "run_command") as command:
            with self.assertRaisesRegex(ValueError, "不存在"):
                app.delete_preference(self.target, "absent")
        backup.assert_not_called()
        command.assert_not_called()

    def test_given_a_dry_run_when_setting_then_preview_without_backups_or_writes(self):
        args = app.build_parser().parse_args(["set", "Example", "enabled", "false", "--type", "bool", "--dry-run"])
        with patch.object(app, "resolve_target", return_value=self.target), \
             patch.object(app, "read_preferences", return_value={"enabled": True}), \
             patch.object(app, "save_backup") as backup, patch.object(app, "run_command") as command, \
             patch("builtins.print") as output:
            app.execute(args)
        preview = json.loads(output.call_args.args[0])
        self.assertIs(preview["new"], False)
        self.assertIs(preview["old"], True)
        backup.assert_not_called()
        command.assert_not_called()

    def test_given_a_backup_when_saved_then_preserve_types_and_restrict_permissions(self):
        original = {"enabled": False, "height": 600.0, "nested": [1, b"data"]}
        path = app.save_backup(self.target, original, self.root / "backups")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        payload = plistlib.loads(path.read_bytes())
        self.assertEqual(payload["preferences"], original)
        self.assertEqual(payload["domain"], self.target.domain)

    def test_given_another_domains_backup_when_restoring_then_refuse_without_writing(self):
        path = app.save_backup(self.target, {"value": 1}, self.root)
        with patch.object(app, "run_command") as command, self.assertRaisesRegex(ValueError, "不匹配"):
            app.restore_preferences(app.Target("com.other.app", "com.other.app"), path)
        command.assert_not_called()

    def test_given_a_backup_when_restoring_then_backup_current_state_before_replacing(self):
        path = app.save_backup(self.target, {"old": False}, self.root)
        with patch.object(app, "read_preferences", side_effect=[{"new": True}, {"old": False}]), \
             patch.object(app, "save_backup", return_value=self.root / "undo.plist") as backup, \
             patch.object(app, "run_command") as command:
            app.restore_preferences(self.target, path)
        backup.assert_called_once_with(self.target, {"new": True})
        command_args = command.call_args.args[0]
        self.assertEqual(command_args[:3], ["defaults", "write", self.target.domain])
        self.assertEqual(plistlib.loads(command_args[3].encode()), {"old": False})

    def test_given_new_keys_after_backup_when_restored_then_remove_those_keys(self):
        path = app.save_backup(self.target, {"old": False}, self.root)
        state = {"old": True, "new": "after snapshot"}

        def simulate_defaults(args, *, input_data=None):
            if args[1] == "import":
                state.update(plistlib.loads(input_data))
            elif args[1] == "write" and len(args) == 4:
                state.clear()
                state.update(plistlib.loads(args[3].encode()))

        with patch.object(app, "read_preferences", side_effect=lambda target: state.copy()), \
             patch.object(app, "save_backup", return_value=self.root / "undo.plist"), \
             patch.object(app, "run_command", side_effect=simulate_defaults):
            app.restore_preferences(self.target, path)
        self.assertEqual(state, {"old": False})

    def test_given_arm64_small_string_when_scanned_then_recover_key_and_type(self):
        lines = """_example:
0000000100001000 bl _objc_msgSend$standardUserDefaults
0000000100001004 mov x19, x0
0000000100001008 mov x0, #0x6970
000000010000100c movk x0, #0x6e6e, lsl #16
0000000100001010 movk x0, #0x6465, lsl #32
0000000100001014 mov x1, #0xe600000000000000
0000000100001018 bl _bridgeToObjectiveCSo8NSString
000000010000101c mov x2, x0
0000000100001020 mov x0, x19
0000000100001024 bl "_objc_msgSend$boolForKey:"
""".splitlines()
        findings, unresolved = app.scan_arm64(lines)
        self.assertEqual([(f.key, f.access, f.value_type) for f in findings], [("pinned", "read", "bool")])
        self.assertEqual(unresolved, 0)

    def test_given_kvc_or_unknown_receiver_when_scanned_then_do_not_claim_preferences(self):
        lines = """_example:
0000000100001000 add x8, x8, #0x20 ; literal pool for: "preferredImageVisibility"
0000000100001004 mov x1, x8
0000000100001008 bl _bridgeToObjectiveCSo8NSString
000000010000100c mov x3, x0
0000000100001010 bl "_objc_msgSend$setValue:forKey:"
0000000100001014 bl "_objc_msgSend$objectForKey:"
""".splitlines()
        findings, _ = app.scan_arm64(lines)
        self.assertEqual(findings, [])

    def test_given_dynamic_key_on_defaults_when_scanned_then_report_incomplete_coverage(self):
        lines = """_example:
0000000100001000 bl _objc_msgSend$standardUserDefaults
0000000100001004 bl "_objc_msgSend$stringForKey:"
""".splitlines()
        findings, unresolved = app.scan_arm64(lines)
        self.assertEqual(findings, [])
        self.assertEqual(unresolved, 1)

    def test_given_missing_domain_when_read_then_return_empty_only_for_that_error(self):
        missing = subprocess.CompletedProcess([], 1, b"", b"Domain com.example.tool does not exist")
        failed = subprocess.CompletedProcess([], 1, b"", b"Permission denied")
        with patch.object(app.subprocess, "run", return_value=missing):
            self.assertEqual(app.read_preferences(self.target), {})
        with patch.object(app.subprocess, "run", return_value=failed), self.assertRaises(RuntimeError):
            app.read_preferences(self.target)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Behavior tests: uv run test_mac_keepawake.py.

The parsing tests use output captured on this machine. The end-to-end tests start real
keep-awake sessions of a few seconds (harmless: they only hold a sleep assertion) and
are skipped while a real session is running, because `on` would replace it.
"""

import importlib.machinery
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("mac-keepawake")
LOADER = importlib.machinery.SourceFileLoader("mac_keepawake", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
km = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = km
LOADER.exec_module(km)

PS_SAMPLE = """\
  576     1 /usr/libexec/powerd
21407 20993 claude --dangerously-skip-permissions
26477 21407 caffeinate -i -t 300
40001     1 /Users/reorx/.local/share/uv/python/bin/python3 /Users/reorx/Code/scripts/skills/systools/scripts/mac-keepawake _watch --since 1761100000 --until 1761128800
40002 40001 /usr/bin/caffeinate -i -s -w 40001 -t 28860
"""

ASSERTIONS_SAMPLE = """\
Assertion status system-wide:
   PreventSystemSleep             1
   PreventUserIdleSystemSleep     1
Listed by owning process:
   pid 1162(useractivityd): [0x0014d46400018606] 00:00:00 PreventUserIdleSystemSleep named: "BTLEAdvertisement.264EEEA7-370D-4496-A430-CECE497302F6"
	Timeout will fire in 59 secs Action=TimeoutActionTurnOff
   pid 26477(caffeinate): [0x0014d441000185bd] 00:00:35 PreventUserIdleSystemSleep named: "caffeinate command-line tool"
	Details: caffeinate asserting for 300 secs
   pid 40002(caffeinate): [0x0014d53800018754] 00:00:01 PreventUserIdleSystemSleep named: "caffeinate command-line tool"
   pid 40002(caffeinate): [0x0014d53800078755] 00:00:01 PreventSystemSleep named: "caffeinate command-line tool"
   pid 576(powerd): [0x0014cc5c0001a608] 00:34:16 PreventUserIdleSystemSleep named: "Powerd - Prevent sleep while display is on"
   pid 1004(nsurlsessiond): [0x0014d462000b8602] 00:00:02 BackgroundTask named: "NSURLSessionTask 89083AA2"
Kernel Assertions: 0x4=USB
"""

CUSTOM_SAMPLE = """\
Battery Power:
 Sleep On Power Button 1
 displaysleep         10
 sleep                1
 disksleep            10
AC Power:
 Sleep On Power Button 1
 displaysleep         20
 sleep                1
 disksleep            10
"""

BATT_SAMPLE = """\
Now drawing from 'AC Power'
 -InternalBattery-0 (id=37748835)	79%; charging; 1:09 remaining present: true
"""

DISPLAYS_SAMPLE = """\
{"SPDisplaysDataType": [{"spdisplays_ndrvs": [
  {"_name": "LG ULTRAFINE", "spdisplays_main": "spdisplays_yes", "spdisplays_online": "spdisplays_yes"},
  {"_name": "Color LCD", "spdisplays_connection_type": "spdisplays_internal", "spdisplays_online": "spdisplays_yes"}
]}]}
"""


class DurationBehavior(unittest.TestCase):
    def test_given_no_duration_when_turning_on_then_it_lasts_the_24h_maximum(self):
        self.assertEqual(km.parse_duration(None), 24 * 3600)

    def test_given_hours_minutes_or_seconds_when_parsed_then_converted_to_seconds(self):
        cases = {"8h": 8 * 3600, "90m": 5400, "1h30m": 5400, "45s": 45, "24h": 86400}
        for text, secs in cases.items():
            with self.subTest(text=text):
                self.assertEqual(km.parse_duration(text), secs)

    def test_given_more_than_24h_when_parsed_then_rejected_instead_of_clamped(self):
        for text in ("25h", "24h1m", "1500m"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "24h"):
                km.parse_duration(text)

    def test_given_a_bare_number_zero_or_garbage_when_parsed_then_rejected(self):
        for text in ("8", "0m", "abc", "", "1d"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                km.parse_duration(text)


class SessionDiscoveryBehavior(unittest.TestCase):
    def test_given_our_watcher_and_its_caffeinate_when_scanning_ps_then_one_session_is_found(self):
        sessions = km.find_sessions(PS_SAMPLE)
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual((s.watcher_pid, s.caffeinate_pid), (40001, 40002))
        self.assertEqual((s.since, s.until), (1761100000, 1761128800))

    def test_given_another_tools_caffeinate_when_scanning_ps_then_it_is_never_claimed(self):
        claimed = {pid for s in km.find_sessions(PS_SAMPLE) for pid in (s.watcher_pid, s.caffeinate_pid)}
        self.assertNotIn(26477, claimed)

    def test_given_no_watcher_when_scanning_ps_then_no_session_even_if_caffeinate_runs(self):
        only_claude = "\n".join(PS_SAMPLE.splitlines()[:3])
        self.assertEqual(km.find_sessions(only_claude), [])

    def test_given_a_watcher_whose_caffeinate_died_when_scanning_ps_then_session_has_no_caffeinate(self):
        without_child = "\n".join(PS_SAMPLE.splitlines()[:4])
        [s] = km.find_sessions(without_child)
        self.assertIsNone(s.caffeinate_pid)


class StopBehavior(unittest.TestCase):
    def test_given_a_session_when_stopped_then_only_its_own_two_processes_are_signalled(self):
        signalled = []
        km.signal_sessions(km.find_sessions(PS_SAMPLE), kill=lambda pid, sig: signalled.append((pid, sig)))
        self.assertEqual(sorted(signalled), [(40001, signal.SIGTERM), (40002, signal.SIGTERM)])


class SystemStateBehavior(unittest.TestCase):
    def test_given_pmset_assertions_when_parsed_then_sleep_blockers_are_listed_per_pid(self):
        assertions = km.parse_assertions(ASSERTIONS_SAMPLE)
        ours = [a.kind for a in assertions if a.pid == 40002]
        self.assertEqual(ours, ["PreventUserIdleSystemSleep", "PreventSystemSleep"])

    def test_given_other_blockers_when_listed_then_ours_powerd_and_non_sleep_kinds_are_excluded(self):
        others = km.other_blockers(km.parse_assertions(ASSERTIONS_SAMPLE), exclude_pids={40002})
        self.assertEqual(sorted(a.pid for a in others), [1162, 26477])

    def test_given_pmset_custom_when_parsed_then_sleep_timers_per_power_source(self):
        settings = km.parse_power_settings(CUSTOM_SAMPLE)
        self.assertEqual(settings["AC Power"], {"displaysleep": 20, "sleep": 1})
        self.assertEqual(settings["Battery Power"], {"displaysleep": 10, "sleep": 1})

    def test_given_pmset_batt_when_parsed_then_current_power_source(self):
        self.assertEqual(km.parse_power_source(BATT_SAMPLE), "AC Power")

    def test_given_display_json_when_parsed_then_only_external_online_displays_count(self):
        self.assertEqual(km.parse_external_displays(DISPLAYS_SAMPLE), ["LG ULTRAFINE"])

    def test_given_sleep_timers_when_described_then_the_normal_behavior_is_spelled_out(self):
        self.assertEqual(
            km.describe_profile({"displaysleep": 20, "sleep": 1}),
            "display off after 20 min idle, system sleeps right after (sleep timer 1 min)",
        )
        self.assertEqual(
            km.describe_profile({"displaysleep": 10, "sleep": 30}),
            "display off after 10 min idle, system sleep after 30 min idle",
        )
        self.assertIn("never idle-sleeps", km.describe_profile({"displaysleep": 10, "sleep": 0}))
        self.assertIn("display never turns off", km.describe_profile({"displaysleep": 0, "sleep": 0}))


class EndToEndBehavior(unittest.TestCase):
    """Real sessions; each test leaves no session behind."""

    @classmethod
    def setUpClass(cls):
        if km.find_sessions(km.read_ps()):
            raise unittest.SkipTest("a real keep-awake session is running; `on` would replace it")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name) / "keepawake.log"
        self.env = os.environ | {"MAC_KEEPAWAKE_LOG": str(self.log)}
        self.addCleanup(self.run_cli, "off")

    def run_cli(self, *args):
        return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=30)

    def sessions(self):
        return km.find_sessions(km.read_ps())

    def held_by(self, pid):
        return {a.kind for a in km.parse_assertions(km.read_assertions()) if a.pid == pid}

    def test_given_on_when_the_duration_elapses_then_it_turns_itself_off_like_off_would(self):
        result = self.run_cli("on", "3s")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Keep-awake is ON", result.stdout)
        self.assertIn("What changed", result.stdout)
        self.assertIn("What happens next", result.stdout)
        [s] = self.sessions()
        self.assertIn("PreventUserIdleSystemSleep", self.held_by(s.caffeinate_pid))

        time.sleep(5)
        self.assertEqual(self.sessions(), [])
        self.assertEqual(self.held_by(s.caffeinate_pid), set())
        self.assertIn("expired", self.log.read_text().splitlines()[-1])
        status = self.run_cli("status")
        self.assertIn("Keep-awake is OFF", status.stdout)
        self.assertIn("expired", status.stdout)

    def test_given_on_when_turned_off_then_its_assertion_is_released_and_other_caffeinates_survive(self):
        bystander = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-t", "60"])
        self.addCleanup(bystander.wait)
        self.addCleanup(bystander.terminate)
        self.assertEqual(self.run_cli("on", "1m").returncode, 0)
        [s] = self.sessions()

        result = self.run_cli("off")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Keep-awake is OFF", result.stdout)
        self.assertEqual(self.sessions(), [])
        self.assertEqual(self.held_by(s.caffeinate_pid), set())
        self.assertIsNone(bystander.poll())
        self.assertIn("PreventUserIdleSystemSleep", self.held_by(bystander.pid))
        self.assertIn("turned off", self.log.read_text().splitlines()[-1])

    def test_given_a_running_session_when_turned_on_again_then_it_is_replaced_not_stacked(self):
        self.run_cli("on", "1m")
        result = self.run_cli("on", "2m")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Replaced", result.stdout)
        [s] = self.sessions()
        self.assertAlmostEqual(s.until - s.since, 120, delta=1)

    def test_given_nothing_running_when_turned_off_then_it_says_so_and_succeeds(self):
        result = self.run_cli("off")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("was not on", result.stdout)

    def test_given_more_than_24h_when_turning_on_then_it_fails_and_starts_nothing(self):
        result = self.run_cli("on", "25h")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("24h", result.stderr)
        self.assertEqual(self.sessions(), [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Behavior tests: uv run test_window_server_doctor.py.

Per-process GPU time comes from `ioreg -c AGXDeviceUserClient` (no sudo). The parsing
tests use output in the format captured on this machine (macOS 26, Apple Silicon); the
end-to-end test runs the real script with --quick and must work without root.
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('window-server-doctor.py')
LOADER = importlib.machinery.SourceFileLoader('window_server_doctor', str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
wsd = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wsd
LOADER.exec_module(wsd)


def client(reg_id: str, pid: int, name: str, gpu_times: list[int]) -> str:
    usage = ','.join(
        f'{{"API"="Metal","lastSubmittedTime"=2757646165145375,"accumulatedGPUTime"={t}}}' for t in gpu_times
    )
    return (
        f'+-o AGXDeviceUserClient  <class AGXDeviceUserClient, id {reg_id}, !registered, !matched, active, busy 0, retain 5>\n'
        '    {\n'
        f'      "AppUsage" = ({usage})\n'
        f'      "IOUserClientCreator" = "pid {pid}, {name}"\n'
        '      "CommandQueueCount" = 7\n'
        '    }\n'
        '    \n'
    )


SEC = 1_000_000_000  # accumulatedGPUTime is in nanoseconds

# WindowServer holds two clients, one of them with several AppUsage entries;
# runningboardd holds a client that never submitted GPU work.
BEFORE = (
    client('0x100000e47', 623, 'runningboardd', [])
    + client('0x100000eea', 619, 'WindowServer', [])
    + client('0x100000eeb', 619, 'WindowServer', [100 * SEC, 2 * SEC, 0])
    + client('0x100001001', 98098, 'iTerm2', [50 * SEC])
    + client('0x100001002', 38564, 'Google Chrome He', [10 * SEC])
    + client('0x100001003', 777, 'Fury', [5 * SEC])
)

# 2 seconds later:
#   WindowServer  +0.2s on one entry          -> 100 ms/s
#   iTerm2        +0.04s                      -> 20 ms/s
#   Chrome helper closed its old client (which held 10s) and opened a new one with 0.01s
#                                             -> 5 ms/s, not a negative number
#   Fury          no change                   -> omitted
#   new process 4242 started during the window with 0.006s -> 3 ms/s
AFTER = (
    client('0x100000e47', 623, 'runningboardd', [])
    + client('0x100000eea', 619, 'WindowServer', [])
    + client('0x100000eeb', 619, 'WindowServer', [100 * SEC + 200_000_000, 2 * SEC, 0])
    + client('0x100001001', 98098, 'iTerm2', [50 * SEC + 40_000_000])
    + client('0x100001009', 38564, 'Google Chrome He', [10_000_000])
    + client('0x100001003', 777, 'Fury', [5 * SEC])
    + client('0x10000100a', 4242, 'newproc', [6_000_000])
)


class ParseClients(unittest.TestCase):
    def test_each_client_is_keyed_by_registry_id_with_its_summed_gpu_time(self):
        clients = wsd.parse_agx_clients(BEFORE)
        self.assertEqual(clients['0x100000eeb'], {'pid': 619, 'name': 'WindowServer', 'gpu_ns': 102 * SEC})
        self.assertEqual(clients['0x100001001']['gpu_ns'], 50 * SEC)

    def test_a_client_that_never_used_the_gpu_counts_as_zero(self):
        clients = wsd.parse_agx_clients(BEFORE)
        self.assertEqual(clients['0x100000e47'], {'pid': 623, 'name': 'runningboardd', 'gpu_ns': 0})

    def test_no_clients_gives_an_empty_result(self):
        self.assertEqual(wsd.parse_agx_clients(''), {})


class GpuRates(unittest.TestCase):
    def setUp(self):
        self.rows = wsd.gpu_rates(wsd.parse_agx_clients(BEFORE), wsd.parse_agx_clients(AFTER), seconds=2.0)
        self.by_pid = {r['pid']: r for r in self.rows}

    def test_rate_is_gpu_milliseconds_per_second_summed_over_a_process_clients(self):
        self.assertAlmostEqual(self.by_pid[619]['gpu_ms'], 100.0)
        self.assertAlmostEqual(self.by_pid[98098]['gpu_ms'], 20.0)

    def test_a_client_closed_during_the_window_does_not_cancel_out_new_work(self):
        self.assertAlmostEqual(self.by_pid[38564]['gpu_ms'], 5.0)

    def test_a_process_that_appeared_during_the_window_counts_in_full(self):
        self.assertAlmostEqual(self.by_pid[4242]['gpu_ms'], 3.0)

    def test_idle_processes_are_left_out(self):
        self.assertNotIn(777, self.by_pid)
        self.assertNotIn(623, self.by_pid)

    def test_rows_are_sorted_busiest_first(self):
        self.assertEqual([r['pid'] for r in self.rows], [619, 98098, 38564, 4242])


class ProcessNames(unittest.TestCase):
    def test_full_executable_name_from_ps_replaces_the_truncated_ioreg_name(self):
        rows = [{'pid': 38564, 'name': 'Google Chrome He', 'gpu_ms': 5.0}]
        ps_out = (
            '38564 /Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/'
            'Versions/156.0/Helpers/Google Chrome Helper (GPU).app/Contents/MacOS/Google Chrome Helper (GPU)\n'
        )
        wsd.apply_full_names(rows, ps_out)
        self.assertEqual(rows[0]['name'], 'Google Chrome Helper (GPU)')

    def test_a_process_that_already_exited_keeps_the_ioreg_name(self):
        rows = [{'pid': 4242, 'name': 'newproc', 'gpu_ms': 3.0}]
        wsd.apply_full_names(rows, '')
        self.assertEqual(rows[0]['name'], 'newproc')


class Verdict(unittest.TestCase):
    def test_elevated_windowserver_names_the_top_gpu_clients_but_not_itself(self):
        proc = {'cpu_pct': 42.0}
        gpu = {
            'ok': True,
            'tasks': [
                {'pid': 619, 'name': 'WindowServer', 'gpu_ms': 68.8},
                {'pid': 98098, 'name': 'iTerm2', 'gpu_ms': 19.1},
                {'pid': 38564, 'name': 'Google Chrome Helper (GPU)', 'gpu_ms': 5.6},
                {'pid': 51667, 'name': 'Telegram', 'gpu_ms': 1.0},
            ],
        }
        text = '\n'.join(wsd.build_verdict(proc, gpu, {'ok': False}, {'ok': False}))
        self.assertIn('GPU user: iTerm2 (19.1 ms/s)', text)
        self.assertIn('GPU user: Google Chrome Helper (GPU) (5.6 ms/s)', text)
        self.assertNotIn('GPU user: WindowServer', text)
        self.assertNotIn('Telegram', text)


@unittest.skipUnless(sys.platform == 'darwin', 'macOS only')
class EndToEnd(unittest.TestCase):
    def test_quick_mode_without_sudo_still_reports_gpu_by_process(self):
        self.assertNotEqual(os.geteuid(), 0, 'run this test as a normal user')
        r = subprocess.run(
            [sys.executable, str(SCRIPT), '--quick', '--json', '--gpu-seconds', '1'],
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertIn(r.returncode, (0, 1), r.stderr)
        gpu = json.loads(r.stdout)['gpu']
        self.assertTrue(gpu['ok'], gpu)
        self.assertGreaterEqual(gpu['seconds'], 1.0)  # measured window: --gpu-seconds plus one ioreg run
        self.assertLess(gpu['seconds'], 3.0)
        for t in gpu['tasks']:
            self.assertGreater(t['gpu_ms'], 0)
            self.assertIsInstance(t['pid'], int)


if __name__ == '__main__':
    unittest.main(verbosity=2)

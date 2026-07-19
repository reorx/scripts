#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""mac-sleep-schedule: manage the macOS daily wake/sleep schedule via pmset.

Thin, opinionated wrapper around `pmset repeat`. The underlying tool
already enforces a single "wake-like" and a single "sleep-like"
repeating event — this script mirrors that contract:

  - one scheduled wake time
  - one scheduled sleep time
  - shared day-of-week mask

Usage:
    mac-sleep-schedule.py                             # show status
    mac-sleep-schedule.py --wake 06:00 --sleep 23:00  # set both (every day)
    mac-sleep-schedule.py --wake 07:30 --sleep 23:30 --days MTWRF
    mac-sleep-schedule.py --clear                     # remove schedule

Day codes (pmset):
    M=Mon T=Tue W=Wed R=Thu F=Fri S=Sat U=Sun
    MTWRFSU = every day (default)   MTWRF = weekdays   SU = weekend
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys


VALID_DAYS = set('MTWRFSU')
TIME_RE = re.compile(r'^(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?$')

RELEVANT_POWER_KEYS = {
    'sleep',
    'displaysleep',
    'disksleep',
    'standby',
    'powernap',
    'womp',
    'tcpkeepalive',
    'autorestart',
    'lowpowermode',
}


def is_root() -> bool:
    return os.geteuid() == 0


def run_pmset(args: list[str], *, sudo: bool = False) -> subprocess.CompletedProcess[str]:
    cmd: list[str] = []
    if sudo and not is_root():
        cmd.append('sudo')
    cmd += ['pmset', *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def parse_time(s: str) -> str:
    m = TIME_RE.match(s)
    if not m:
        raise argparse.ArgumentTypeError(f'invalid time {s!r}; expected HH:MM or HH:MM:SS')
    h, mi, se = int(m['h']), int(m['m']), int(m['s'] or 0)
    if not (0 <= h < 24 and 0 <= mi < 60 and 0 <= se < 60):
        raise argparse.ArgumentTypeError(f'time out of range: {s}')
    return f'{h:02d}:{mi:02d}:{se:02d}'


def parse_days(s: str) -> str:
    s = s.upper()
    if not s:
        raise argparse.ArgumentTypeError('--days cannot be empty')
    bad = [c for c in s if c not in VALID_DAYS]
    if bad:
        raise argparse.ArgumentTypeError(f'invalid day letter(s) {"".join(bad)!r}; use letters from M T W R F S U')
    if len(set(s)) != len(s):
        raise argparse.ArgumentTypeError(f'duplicate day letters in {s!r}')
    return s


def format_sched_section(stdout: str) -> str:
    text = stdout.rstrip()
    return text if text else '(no scheduled events)'


def print_status() -> int:
    sched = run_pmset(['-g', 'sched'])
    print('── Scheduled events ' + '─' * 46)
    print(format_sched_section(sched.stdout))

    settings = run_pmset(['-g'])
    print()
    print('── Relevant power settings ' + '─' * 39)
    for line in settings.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if parts and parts[0] in RELEVANT_POWER_KEYS:
            print(f'  {line.strip()}')
    return 0


def clear_schedule() -> int:
    r = run_pmset(['repeat', 'cancel'], sudo=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.rstrip() + '\n')
        return r.returncode
    print('Cleared all repeating wake/sleep events.')
    print()
    return print_status()


def set_schedule(wake: str, sleep: str, days: str) -> int:
    if wake == sleep:
        sys.stderr.write(f'error: --wake and --sleep are identical ({wake}); this would be a no-op schedule.\n')
        return 2

    r = run_pmset(
        ['repeat', 'wakeorpoweron', days, wake, 'sleep', days, sleep],
        sudo=True,
    )
    if r.returncode != 0:
        sys.stderr.write(r.stderr.rstrip() + '\n')
        return r.returncode

    print(f'Scheduled: wake {wake} / sleep {sleep} on {days}')
    print()
    return print_status()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description='Manage the macOS daily wake/sleep schedule (pmset repeat).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  %(prog)s                                  # show current schedule\n'
            '  %(prog)s --wake 06:00 --sleep 23:00       # every day\n'
            '  %(prog)s --wake 07:30 --sleep 23:30 --days MTWRF\n'
            '  %(prog)s --clear                          # clear schedule\n'
            '\n'
            'Day codes: M T W R F S U  (R=Thu, U=Sun). Default: MTWRFSU.\n'
            'Requires sudo to modify the schedule; status view does not.\n'
        ),
    )
    p.add_argument('--wake', type=parse_time, metavar='HH:MM[:SS]', help='wake (or power-on) time')
    p.add_argument('--sleep', type=parse_time, metavar='HH:MM[:SS]', help='sleep time')
    p.add_argument(
        '--days',
        type=parse_days,
        default='MTWRFSU',
        metavar='LETTERS',
        help='day-of-week mask (default: MTWRFSU = every day)',
    )
    p.add_argument('--clear', action='store_true', help='remove all repeating wake/sleep events')
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.clear:
        if args.wake or args.sleep:
            parser.error('--clear cannot be combined with --wake/--sleep')
        return clear_schedule()

    if args.wake or args.sleep:
        if not (args.wake and args.sleep):
            parser.error(
                'both --wake and --sleep are required when setting a schedule (pmset repeat stores exactly one of each)'
            )
        return set_schedule(args.wake, args.sleep, args.days)

    return print_status()


if __name__ == '__main__':
    sys.exit(main())

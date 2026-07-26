#!/usr/bin/env python3
"""
launchd-list - show what actually runs on a schedule on this Mac.

Answers "which of my scripts run periodically, and are they really armed?".
System Settings and `launchctl list` each tell half the story: a plist can sit
on disk without being loaded, and a loaded job can be resident rather than
scheduled. This flattens both into one table, classified by cadence, and folds
in crontab (where a leading `#` silently disables an entry).

Sources: ~/Library/LaunchAgents, /Library/LaunchAgents, /Library/LaunchDaemons,
`launchctl list`, and `crontab -l`.

Usage examples:
    launchd-list.py                 # non-Apple jobs, grouped by cadence
    launchd-list.py --periodic      # only things that run on a schedule (+ cron)
    launchd-list.py --all           # include com.apple.* jobs
    launchd-list.py --label grafana # filter by label substring
    launchd-list.py --json          # structured output
    launchd-list.py --selftest      # behaviour checks, no side effects
"""

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import argparse
import json
import plistlib
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

PLIST_DIRS = [
    (Path.home() / 'Library/LaunchAgents', '~/LA'),
    (Path('/Library/LaunchAgents'), '/LA'),
    (Path('/Library/LaunchDaemons'), '/LD'),
]

# Apple ships its own jobs here, and there are hundreds — only scanned under --all.
SYSTEM_PLIST_DIRS = [
    (Path('/System/Library/LaunchAgents'), '/SLA'),
    (Path('/System/Library/LaunchDaemons'), '/SLD'),
]

PERIODIC, TRIGGERED, RESIDENT, ONDEMAND, UNREADABLE = (
    'PERIODIC',
    'TRIGGERED',
    'RESIDENT',
    'ON-DEMAND',
    'UNREADABLE',
)
CATEGORY_ORDER = [PERIODIC, TRIGGERED, RESIDENT, ONDEMAND, UNREADABLE]

# @reboot-style shorthands plus a plain 5-field schedule.
CRON_SPECIAL_RE = re.compile(r'^@(reboot|yearly|annually|monthly|weekly|daily|midnight|hourly)\s+(\S.*)$')
CRON_FIELD = r'[0-9*/,\-]+'
CRON_RE = re.compile(rf'^({CRON_FIELD}\s+{CRON_FIELD}\s+{CRON_FIELD}\s+{CRON_FIELD}\s+{CRON_FIELD})\s+(\S.*)$')


@dataclass
class Job:
    label: str
    category: str
    schedule: str
    program: str
    source: str  # "~/LA", "/LA", "/LD" or "cron"
    loaded: bool | None = None  # None = unknown (system daemons need sudo)
    pid: int | None = None
    last_exit: int | None = None
    enabled: bool = True  # cron entries commented out are disabled


# ── Pure parsing ────────────────────────────────────────────
def describe_interval(seconds: int) -> str:
    """Render a StartInterval as the coarsest exact unit."""
    if seconds and seconds % 3600 == 0:
        return f'every {seconds // 3600}h'
    if seconds and seconds % 60 == 0:
        return f'every {seconds // 60}min'
    return f'every {seconds}s'


def describe_calendar(entries) -> str:
    """Render StartCalendarInterval (a dict or list of dicts) as a human schedule."""
    if isinstance(entries, dict):
        entries = [entries]
    parts = []
    for entry in entries:
        hour, minute = entry.get('Hour'), entry.get('Minute')
        if hour is not None:
            when = f'{hour:02d}:{minute or 0:02d}'
        elif minute is not None:
            when = f':{minute:02d} hourly'
        else:
            parts.append('unspecified')
            continue
        # Weekday/Day narrow an otherwise daily/hourly schedule.
        if entry.get('Weekday') is not None:
            when += f' on weekday {entry["Weekday"]}'
        elif entry.get('Day') is not None:
            when += f' on day {entry["Day"]}'
        elif hour is not None:
            when += ' daily'
        parts.append(when)
    return ', '.join(parts) if parts else 'unspecified'


def classify(d: dict) -> tuple[str, str]:
    """Return (category, human schedule) for a parsed launchd plist."""
    # A schedule beats KeepAlive: a job can declare both, but the schedule is
    # what makes it fire, and that is what this tool is here to surface.
    if 'StartInterval' in d:
        return PERIODIC, describe_interval(d['StartInterval'])
    if 'StartCalendarInterval' in d:
        return PERIODIC, describe_calendar(d['StartCalendarInterval'])
    if d.get('WatchPaths'):
        return TRIGGERED, 'WatchPaths: ' + ', '.join(d['WatchPaths'])[:60]
    if d.get('QueueDirectories'):
        return TRIGGERED, 'QueueDirectories: ' + ', '.join(d['QueueDirectories'])[:60]
    if d.get('StartOnMount'):
        return TRIGGERED, 'StartOnMount'
    if d.get('KeepAlive'):
        return RESIDENT, 'KeepAlive'
    if d.get('RunAtLoad'):
        return RESIDENT, 'RunAtLoad (no KeepAlive)'
    return ONDEMAND, 'socket/xpc or manual'


def describe_program(d: dict) -> str:
    """Flatten Program / ProgramArguments into one command line."""
    args = d.get('ProgramArguments')
    if args:
        return ' '.join(str(a) for a in args)
    return str(d.get('Program', ''))


def parse_launchctl_list(output: str) -> dict[str, tuple[int | None, int | None]]:
    """Parse `launchctl list` into {label: (pid, last_exit_status)}."""
    loaded = {}
    for line in output.splitlines():
        fields = line.split('\t')
        if len(fields) != 3 or fields[0] == 'PID':
            continue
        pid_s, status_s, label = (f.strip() for f in fields)
        pid = int(pid_s) if pid_s.lstrip('-').isdigit() and pid_s != '-' else None
        status = int(status_s) if status_s.lstrip('-').isdigit() else None
        loaded[label] = (pid, status)
    return loaded


def parse_crontab(output: str) -> list[Job]:
    """Parse `crontab -l`, keeping commented-out entries as disabled jobs."""
    jobs = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # A leading '#' silently disables an entry — the single most common way
        # for a cron job to be "installed" yet never run.
        enabled = not stripped.startswith('#')
        candidate = stripped.lstrip('#').strip() if not enabled else stripped

        match = CRON_SPECIAL_RE.match(candidate) or CRON_RE.match(candidate)
        if not match:
            continue  # prose comment, env assignment, or malformed
        schedule = match.group(1) if match.re is CRON_RE else '@' + match.group(1)
        jobs.append(
            Job(
                label=match.group(2).split()[0].rsplit('/', 1)[-1],
                category=PERIODIC,
                schedule=schedule,
                program=match.group(2),
                source='cron',
                enabled=enabled,
            )
        )
    return jobs


# ── Self tests (behaviour spec) ─────────────────────────────
CRONTAB_FIXTURE = """\
# a plain note, not a job
SHELL=/bin/zsh
0 11 * * * /Users/reorx/Code/scripts/sync_cursor_settings.sh save
#30 4 * * 1 /usr/local/bin/weekly-backup.sh
@reboot /Users/reorx/bin/startup.sh
# @daily /Users/reorx/bin/nightly.sh
"""

LAUNCHCTL_FIXTURE = """\
PID\tStatus\tLabel
1234\t0\tcom.reorx.warpway
-\t0\tcom.reorx.mac-dev-cleanup
-\t78\tcom.broken.job
"""

_FAILED = 0


def check(name: str, got, want) -> None:
    global _FAILED
    if got == want:
        print(f'  ✅ {name}')
    else:
        _FAILED += 1
        print(f'  ❌ {name}\n       got:  {got!r}\n       want: {want!r}')


def selftest() -> int:
    print('describe_interval')
    check('hours', describe_interval(3600), 'every 1h')
    check('minutes', describe_interval(900), 'every 15min')
    check('seconds', describe_interval(15), 'every 15s')
    check('non-round falls back to seconds', describe_interval(90), 'every 90s')
    check('24h', describe_interval(86400), 'every 24h')

    print('\ndescribe_calendar')
    check('hour + minute', describe_calendar({'Hour': 6, 'Minute': 0}), '06:00 daily')
    check('hour only defaults minute', describe_calendar({'Hour': 7}), '07:00 daily')
    check('minute only is hourly', describe_calendar({'Minute': 15}), ':15 hourly')
    check('weekday', describe_calendar({'Hour': 4, 'Minute': 30, 'Weekday': 1}), '04:30 on weekday 1')
    check('day of month', describe_calendar({'Hour': 3, 'Minute': 0, 'Day': 1}), '03:00 on day 1')
    check(
        'multiple entries',
        describe_calendar([{'Hour': 6, 'Minute': 0}, {'Hour': 18, 'Minute': 30}]),
        '06:00 daily, 18:30 daily',
    )
    check('empty dict', describe_calendar({}), 'unspecified')

    print('\nclassify')
    check('StartInterval → periodic', classify({'StartInterval': 900}), (PERIODIC, 'every 15min'))
    check(
        'calendar → periodic',
        classify({'StartCalendarInterval': {'Hour': 6, 'Minute': 0}}),
        (PERIODIC, '06:00 daily'),
    )
    check(
        'calendar wins over KeepAlive',
        classify({'StartCalendarInterval': {'Minute': 15}, 'KeepAlive': True})[0],
        PERIODIC,
    )
    check('KeepAlive → resident', classify({'KeepAlive': True}), (RESIDENT, 'KeepAlive'))
    check('KeepAlive dict → resident', classify({'KeepAlive': {'SuccessfulExit': False}})[0], RESIDENT)
    check('RunAtLoad only → resident', classify({'RunAtLoad': True}), (RESIDENT, 'RunAtLoad (no KeepAlive)'))
    check('WatchPaths → triggered', classify({'WatchPaths': ['/tmp/x']}), (TRIGGERED, 'WatchPaths: /tmp/x'))
    check('QueueDirectories → triggered', classify({'QueueDirectories': ['/tmp/q']})[0], TRIGGERED)
    check('bare plist → on-demand', classify({'Label': 'x'}), (ONDEMAND, 'socket/xpc or manual'))
    check('KeepAlive false is not resident', classify({'KeepAlive': False})[0], ONDEMAND)

    print('\ndescribe_program')
    check('ProgramArguments joined', describe_program({'ProgramArguments': ['/bin/ls', '-l']}), '/bin/ls -l')
    check('Program alone', describe_program({'Program': '/bin/ls'}), '/bin/ls')
    check(
        'ProgramArguments wins over Program',
        describe_program({'Program': '/bin/ls', 'ProgramArguments': ['/bin/ls', '-a']}),
        '/bin/ls -a',
    )
    check('neither', describe_program({}), '')

    print('\nparse_launchctl_list')
    loaded = parse_launchctl_list(LAUNCHCTL_FIXTURE)
    check('running job keeps pid', loaded['com.reorx.warpway'], (1234, 0))
    check('scheduled job has no pid', loaded['com.reorx.mac-dev-cleanup'], (None, 0))
    check('failed job keeps exit code', loaded['com.broken.job'], (None, 78))
    check('header skipped', 'Label' in loaded, False)

    print('\nparse_crontab')
    cron = parse_crontab(CRONTAB_FIXTURE)
    check('finds 4 entries', len(cron), 4)
    check('active entry', (cron[0].schedule, cron[0].enabled), ('0 11 * * *', True))
    check('commented entry is disabled', (cron[1].schedule, cron[1].enabled), ('30 4 * * 1', False))
    check('@reboot shorthand', (cron[2].schedule, cron[2].enabled), ('@reboot', True))
    check('commented @daily', (cron[3].schedule, cron[3].enabled), ('@daily', False))
    check('prose comment ignored', [c for c in cron if 'plain note' in c.program], [])
    check('env assignment ignored', [c for c in cron if c.program.startswith('SHELL')], [])
    check('all cron rows are periodic', {c.category for c in cron}, {PERIODIC})

    print()
    if _FAILED:
        print(f'❌ {_FAILED} check(s) failed')
    else:
        print('✅ all checks passed')
    return 1 if _FAILED else 0


# ── Collection ──────────────────────────────────────────────
def load_plist(path: Path) -> dict | None:
    try:
        return plistlib.loads(path.read_bytes())
    except Exception:
        # Root-owned or oddly encoded plists: let plutil normalise them first.
        out = subprocess.run(['plutil', '-convert', 'xml1', '-o', '-', str(path)], capture_output=True)
        if out.returncode != 0:
            return None
        try:
            return plistlib.loads(out.stdout)
        except Exception:
            return None


def launchctl_loaded() -> dict[str, tuple[int | None, int | None]]:
    out = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
    return parse_launchctl_list(out.stdout) if out.returncode == 0 else {}


def crontab_jobs() -> list[Job]:
    out = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    return parse_crontab(out.stdout) if out.returncode == 0 else []


def collect_jobs(include_apple: bool) -> list[Job]:
    loaded = launchctl_loaded()
    jobs: list[Job] = []

    for directory, tag in PLIST_DIRS + (SYSTEM_PLIST_DIRS if include_apple else []):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix != '.plist':
                continue
            d = load_plist(path)
            if d is None:
                jobs.append(Job(path.stem, UNREADABLE, '', '', tag))
                continue
            label = d.get('Label', path.stem)
            if not include_apple and label.startswith('com.apple.'):
                continue
            category, schedule = classify(d)
            pid, last_exit = loaded.get(label, (None, None))
            if label in loaded:
                is_loaded: bool | None = True
            elif tag == '/LD':
                is_loaded = None  # system domain, invisible without sudo
            else:
                is_loaded = False
            jobs.append(Job(label, category, schedule, describe_program(d), tag, is_loaded, pid, last_exit))

    jobs.extend(crontab_jobs())
    return jobs


# ── Rendering ───────────────────────────────────────────────
def state_marker(job: Job) -> str:
    if job.source == 'cron':
        return '[on ]' if job.enabled else '[off]'
    if job.loaded is None:
        return '[ ? ]'
    if not job.loaded:
        return '[off]'
    return '[on ]'


def render(jobs: list[Job]) -> None:
    by_category: dict[str, list[Job]] = {}
    for job in jobs:
        by_category.setdefault(job.category, []).append(job)

    for category in CATEGORY_ORDER:
        group = by_category.get(category)
        if not group:
            continue
        print(f'\n{"=" * 4} {category} ({len(group)}) {"=" * 4}')
        for job in sorted(group, key=lambda j: j.label):
            note = ''
            if job.pid:
                note = f'  pid {job.pid}'
            elif job.last_exit:
                note = f'  exit {job.last_exit}'
            print(f'  {state_marker(job)} {job.source:4} {job.label:<44} {job.schedule}{note}')
            if job.program:
                print(f'        {job.program[:150]}')

    stale = [j for j in jobs if j.source != 'cron' and j.loaded is False]
    disabled_cron = [j for j in jobs if j.source == 'cron' and not j.enabled]
    failing = [j for j in jobs if j.last_exit]
    print()
    if stale:
        print(f'{len(stale)} plist(s) present but NOT loaded: {", ".join(j.label for j in stale)}')
    if disabled_cron:
        print(
            f'{len(disabled_cron)} crontab entry(ies) commented out: {", ".join(j.program[:60] for j in disabled_cron)}'
        )
    if failing:
        print(
            f'{len(failing)} job(s) with a non-zero last exit: {", ".join(f"{j.label}={j.last_exit}" for j in failing)}'
        )


# ── Main ────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description='Show what runs on a schedule on this Mac')
    parser.add_argument('--periodic', action='store_true', help='Only jobs that run on a schedule (plus cron)')
    parser.add_argument(
        '--all', action='store_true', help="Include Apple's own jobs (also scans /System/Library/Launch*)"
    )
    parser.add_argument('--label', metavar='SUBSTR', help='Filter by label substring (case-insensitive)')
    parser.add_argument('--json', action='store_true', help='Structured output')
    parser.add_argument('--selftest', action='store_true', help='Run behaviour checks and exit')
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    if sys.platform != 'darwin':
        print('macOS only', file=sys.stderr)
        return 1

    jobs = collect_jobs(args.all)
    if args.periodic:
        jobs = [j for j in jobs if j.category == PERIODIC]
    if args.label:
        needle = args.label.lower()
        jobs = [j for j in jobs if needle in j.label.lower() or needle in j.program.lower()]

    if args.json:
        print(json.dumps([asdict(j) for j in jobs], indent=2))
    else:
        render(jobs)
    return 0


if __name__ == '__main__':
    sys.exit(main())

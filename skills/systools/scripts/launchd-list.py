#!/usr/bin/env python3
"""
launchd-list - show what actually runs on a schedule on this Mac.

Answers "which of my scripts run periodically, and are they really armed?".
System Settings and `launchctl list` each tell half the story: a plist can sit
on disk without being loaded, and a loaded job can be resident rather than
scheduled. This flattens both into one table, classified by cadence, and folds
in crontab (where a leading `#` silently disables an entry). Each plist also gets
an origin line: symlink target, repo copy (flagging drift), brew, app bundle, or
local file — nothing else on the machine records which repo a plist came from.

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
import glob
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
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

# Where repo-managed plists live. A plist with the same filename in one of these was
# installed from that repo (e.g. copied by macos-monitoring's install-launchd.sh).
# One glob level only: ~/Documents sits in iCloud, so no deep walks there.
REPO_PLIST_GLOBS = [
    '~/Code/*/launchd/*.plist',
    '~/Code/*/skills/*/launchd/*.plist',
    '~/Documents/*/launchd/*.plist',
]
CODE_ROOT = Path.home() / 'Code'
BREW_LABEL_PREFIXES = ('homebrew.mxcl.', 'sh.brew.')
APP_BUNDLE_RE = re.compile(r'/([^/]+\.app)(?:/|$)')
DIFFERS, BROKEN = ' (differs)', ' (broken)'

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
    origin: str = ''  # who owns the plist: symlink target, repo copy, brew, app, or local file


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


def shorten(path: str, home: str = str(Path.home())) -> str:
    """Abbreviate the home directory to ~."""
    if path == home or path.startswith(home + '/'):
        return '~' + path[len(home) :]
    return path


def code_repo_hint(paths: list[str], code_root: Path) -> Path | None:
    """Return the <code_root>/<repo> that the first matching path lives in."""
    for p in paths:
        path = Path(p)
        if path != code_root and path.is_relative_to(code_root):
            return code_root / path.relative_to(code_root).parts[0]
    return None


def index_repo_plists(patterns: list[str]) -> dict[str, Path]:
    """Map plist filename → its copy in a repo; the first match in sorted order wins."""
    index: dict[str, Path] = {}
    for pattern in patterns:
        for match in sorted(glob.glob(os.path.expanduser(pattern))):
            index.setdefault(os.path.basename(match), Path(match))
    return index


def describe_origin(path: Path, d: dict | None, repo_index: dict[str, Path], code_root: Path = CODE_ROOT) -> str:
    """Say who owns a plist: a symlink target, a repo copy, brew, an app bundle, or nobody."""
    if path.is_symlink():
        target = path.parent / os.readlink(path)
        return f'link → {shorten(str(target))}' + ('' if target.exists() else BROKEN)

    d = d or {}
    label = d.get('Label', path.stem)
    for prefix in BREW_LABEL_PREFIXES:
        if label.startswith(prefix):
            return f'brew services: {label.removeprefix(prefix)}'

    repo_copy = repo_index.get(path.name)
    if repo_copy:
        drift = '' if repo_copy.read_bytes() == path.read_bytes() else DIFFERS
        return f'copy of {shorten(str(repo_copy))}{drift}'

    # launchd execs Program when set; ProgramArguments[0] is then only argv[0].
    program = str(d.get('Program') or (d.get('ProgramArguments') or [''])[0])
    app = APP_BUNDLE_RE.search(program)
    if app:
        return f'app: {app.group(1)}'

    # Self-installing tools (cc-renewer, warpway, …) write their own plist; the repo
    # they come from shows up in the program path, its symlink target, or the cwd.
    candidates = [program, os.path.realpath(program)] if program else []
    candidates.append(d.get('WorkingDirectory', ''))
    repo = code_repo_hint([c for c in candidates if c], code_root)
    return f'local file, program in {shorten(str(repo))}' if repo else 'local file'


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


def selftest_origin(root: Path) -> None:
    """index_repo_plists / describe_origin against a throwaway tree under `root`."""
    code = root / 'Code'
    repo_launchd = code / 'monitoring' / 'launchd'
    skill_launchd = code / 'scripts' / 'skills' / 'tool' / 'launchd'
    agents = root / 'LaunchAgents'
    for directory in (repo_launchd, skill_launchd, agents, root / 'bin', code / 'clash' / 'bin'):
        directory.mkdir(parents=True)
    (repo_launchd / 'com.local.same.plist').write_bytes(b'same')
    (repo_launchd / 'com.local.drift.plist').write_bytes(b'repo version')
    (skill_launchd / 'com.reorx.linked.plist').write_bytes(b'linked')
    (agents / 'com.local.same.plist').write_bytes(b'same')
    (agents / 'com.local.drift.plist').write_bytes(b'hand edited')
    (agents / 'com.reorx.linked.plist').symlink_to(skill_launchd / 'com.reorx.linked.plist')
    (agents / 'com.gone.plist').symlink_to(root / 'nowhere.plist')
    (agents / 'local.plist').write_bytes(b'x')
    (code / 'clash' / 'bin' / 'tool').write_bytes(b'')
    (root / 'bin' / 'tool').symlink_to(code / 'clash' / 'bin' / 'tool')

    print('\nindex_repo_plists')
    index = index_repo_plists([f'{code}/*/launchd/*.plist', f'{code}/*/skills/*/launchd/*.plist'])
    check(
        'finds repo launchd dirs',
        sorted(index),
        ['com.local.drift.plist', 'com.local.same.plist', 'com.reorx.linked.plist'],
    )
    check('maps name to repo path', index['com.local.same.plist'], repo_launchd / 'com.local.same.plist')
    check('missing dirs are fine', index_repo_plists([f'{root}/nope/*/launchd/*.plist']), {})

    def origin(name: str, d: dict | None = None) -> str:
        return describe_origin(agents / name, d, index, code)

    print('\ndescribe_origin')
    check(
        'symlink → its target, even with a repo copy',
        origin('com.reorx.linked.plist'),
        f'link → {skill_launchd / "com.reorx.linked.plist"}',
    )
    check('dangling symlink flagged', origin('com.gone.plist'), f'link → {root / "nowhere.plist"} (broken)')
    check('identical repo copy', origin('com.local.same.plist'), f'copy of {repo_launchd / "com.local.same.plist"}')
    check(
        'drifted repo copy flagged',
        origin('com.local.drift.plist'),
        f'copy of {repo_launchd / "com.local.drift.plist"} (differs)',
    )
    check('homebrew.mxcl → brew', origin('local.plist', {'Label': 'homebrew.mxcl.redis'}), 'brew services: redis')
    check('sh.brew → brew', origin('local.plist', {'Label': 'sh.brew.mysql@9.7'}), 'brew services: mysql@9.7')
    check(
        'outermost app bundle owns it',
        origin('local.plist', {'ProgramArguments': ['/Applications/OneDrive.app/Contents/U.app/Contents/MacOS/u']}),
        'app: OneDrive.app',
    )
    check(
        'program in a ~/Code repo',
        origin('local.plist', {'ProgramArguments': [f'{code}/warpway/warpway', 'serve']}),
        f'local file, program in {code / "warpway"}',
    )
    check(
        'WorkingDirectory in a ~/Code repo',
        origin(
            'local.plist', {'ProgramArguments': ['/usr/local/bin/uv', 'run'], 'WorkingDirectory': f'{code}/condenser'}
        ),
        f'local file, program in {code / "condenser"}',
    )
    check(
        'symlinked program resolved into its repo',
        origin('local.plist', {'ProgramArguments': [str(root / 'bin' / 'tool'), 'run']}),
        f'local file, program in {code / "clash"}',
    )
    check(
        'Program wins over ProgramArguments',
        origin('local.plist', {'Program': f'{code}/x/bin', 'ProgramArguments': ['/bin/sh']}),
        f'local file, program in {code / "x"}',
    )
    check('plain local file', origin('local.plist', {'ProgramArguments': ['/opt/homebrew/bin/x']}), 'local file')
    check('unparseable plist still gets an origin', origin('local.plist'), 'local file')


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

    print('\nshorten')
    check('home abbreviated', shorten('/Users/x/Code/a', home='/Users/x'), '~/Code/a')
    check('home itself', shorten('/Users/x', home='/Users/x'), '~')
    check('sibling prefix untouched', shorten('/Users/xy/a', home='/Users/x'), '/Users/xy/a')
    check('outside home untouched', shorten('/opt/homebrew/bin/x', home='/Users/x'), '/opt/homebrew/bin/x')

    print('\ncode_repo_hint')
    code = Path('/Users/x/Code')
    check('program inside a repo', code_repo_hint(['/Users/x/Code/warpway/warpway'], code), code / 'warpway')
    check('outside ~/Code → none', code_repo_hint(['/Users/x/go/bin/pinchtab'], code), None)
    check(
        'later candidate used',
        code_repo_hint(['/Users/x/.local/bin/uv', '/Users/x/Code/condenser/probe'], code),
        code / 'condenser',
    )
    check('~/Code itself is not a repo', code_repo_hint(['/Users/x/Code'], code), None)

    with tempfile.TemporaryDirectory() as tmp:
        # resolve(): /var/folders is a symlink to /private/var, and realpath() sees through it.
        selftest_origin(Path(tmp).resolve())

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
    repo_index = index_repo_plists(REPO_PLIST_GLOBS)
    jobs: list[Job] = []

    for directory, tag in PLIST_DIRS + (SYSTEM_PLIST_DIRS if include_apple else []):
        if not directory.is_dir():
            continue
        # Apple's own directories need no attribution.
        is_system = (directory, tag) in SYSTEM_PLIST_DIRS
        for path in sorted(directory.iterdir()):
            if path.suffix != '.plist':
                continue
            d = load_plist(path)
            if d is None:
                jobs.append(Job(path.stem, UNREADABLE, '', '', tag, origin=describe_origin(path, None, repo_index)))
                continue
            label = d.get('Label', path.stem)
            if not include_apple and label.startswith('com.apple.'):
                continue
            origin = '' if is_system else describe_origin(path, d, repo_index)
            category, schedule = classify(d)
            pid, last_exit = loaded.get(label, (None, None))
            if label in loaded:
                is_loaded: bool | None = True
            elif tag == '/LD':
                is_loaded = None  # system domain, invisible without sudo
            else:
                is_loaded = False
            jobs.append(
                Job(label, category, schedule, describe_program(d), tag, is_loaded, pid, last_exit, origin=origin)
            )

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
            if job.origin:
                print(f'        ↳ {job.origin}')

    stale = [j for j in jobs if j.source != 'cron' and j.loaded is False]
    disabled_cron = [j for j in jobs if j.source == 'cron' and not j.enabled]
    failing = [j for j in jobs if j.last_exit]
    drifted = [j for j in jobs if j.origin.endswith(DIFFERS)]
    broken = [j for j in jobs if j.origin.endswith(BROKEN)]
    print()
    if drifted:
        print(
            f"{len(drifted)} installed plist(s) differ from their repo copy (re-run that repo's installer): "
            f'{", ".join(j.label for j in drifted)}'
        )
    if broken:
        print(f'{len(broken)} plist symlink(s) point at nothing: {", ".join(j.label for j in broken)}')
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
    parser.add_argument(
        '--label', metavar='SUBSTR', help='Filter by substring of label, command or origin (case-insensitive)'
    )
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
        jobs = [j for j in jobs if needle in f'{j.label} {j.program} {j.origin}'.lower()]

    if args.json:
        print(json.dumps([asdict(j) for j in jobs], indent=2))
    else:
        render(jobs)
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Open URLs, sending Claude's domains to a running fingerprint browser.

Usage:
  open-browser.py <url>...

Meant to be Claude Code's BROWSER command: Claude Code runs `$BROWSER <url>` whenever it
opens a page (login, artifact links, clicked links). A URL whose host is one of
OPEN_BROWSER_DOMAINS (comma-separated, default claude.ai,claude.com) or a subdomain of one
opens as a new tab in the browser picked by OPEN_BROWSER_TARGET; any other URL goes to
macOS `open`, the default browser.

OPEN_BROWSER_TARGET:
  stickyfingers  (default) a browser opened by the StickyFingers app. The URL is handed to
                 it through Chromium's SingletonSocket in the profile's user-data dir, the
                 path Chromium itself uses to pass a URL to a running browser. Profiles are
                 read from $STICKYFINGERS_HOME (default ~/Library/Application Support/
                 StickyFingers). OPEN_BROWSER_PROFILE picks one by name or id prefix.
  sunbrowser     the AdsPower Sun Browser, through its DevTools HTTP endpoint (AdsPower
                 starts it with --remote-debugging-port=0, so the port is read from
                 DevToolsActivePort). OPEN_BROWSER_PROFILE is an AdsPower profile id.

Without OPEN_BROWSER_PROFILE the one running profile is used; with several running it is an
error. The target browser is never started here: launched outside its manager it would run
without the profile's proxy and fingerprint. When it is not running the URL is not opened.
"""

import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

DEFAULT_DOMAINS = 'claude.ai,claude.com'
DEFAULT_TARGET = 'stickyfingers'


class BrowserError(Exception):
    pass


def bring_to_front(pid):
    # Opening a tab does not raise the window. Activating by pid reaches this exact process;
    # `open -a` could start a second, bare browser outside its manager. Best effort.
    script = (
        "ObjC.import('AppKit'); "
        f'$.NSRunningApplication.runningApplicationWithProcessIdentifier({pid})'
        '.activateWithOptions($.NSApplicationActivateAllWindows)'
    )
    subprocess.run(['osascript', '-l', 'JavaScript', '-e', script], capture_output=True)


# --- StickyFingers ---------------------------------------------------------------------------

LOCK_RE = re.compile(r'^(.+)-(\d+)$')


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    user_data_dir: Path
    pid: int | None  # the browser's main process when it is running on this host

    def matches(self, choice):
        choice = choice.casefold()
        return self.name.casefold() == choice or self.id.casefold().startswith(choice)


def stickyfingers_root():
    # Same rule as the app's DataPaths.resolve
    home = os.environ.get('STICKYFINGERS_HOME')
    if home:
        return Path(home).expanduser()
    return Path.home() / 'Library/Application Support/StickyFingers'


def live_pids():
    ps = subprocess.run(['ps', '-axo', 'pid='], capture_output=True, text=True, check=True)
    return {int(pid) for pid in ps.stdout.split()}


def lock_owner(user_data_dir, host, pids):
    # Chromium's SingletonLock is a symlink to "<hostname>-<pid>"
    lock = user_data_dir / 'SingletonLock'
    if not lock.is_symlink():
        return None
    match = LOCK_RE.match(os.readlink(lock))
    if not match or match.group(1) != host or int(match.group(2)) not in pids:
        return None
    return int(match.group(2))


def find_profiles(root, host, pids):
    profiles_dir = Path(root) / 'profiles'
    if not profiles_dir.is_dir():
        return []
    profiles = []
    for directory in sorted(profiles_dir.iterdir()):
        config = directory / 'profile.json'
        if directory.name.startswith('.') or not config.is_file():
            continue
        name = json.loads(config.read_text())['name']
        udd = directory / 'user-data'
        profiles.append(Profile(directory.name, name, udd, lock_owner(udd, host, pids)))
    return profiles


def pick_profile(profiles, choice=None):
    if choice:
        chosen = [p for p in profiles if p.matches(choice)]
        if not chosen:
            names = ', '.join(p.name for p in profiles) or 'none'
            raise BrowserError(f'No StickyFingers profile matches OPEN_BROWSER_PROFILE={choice}. Profiles: {names}')
        if len(chosen) > 1:
            ids = ', '.join(f'{p.name} ({p.id})' for p in chosen)
            raise BrowserError(f'OPEN_BROWSER_PROFILE={choice} matches several profiles: {ids}')
        if chosen[0].pid is None:
            raise BrowserError(
                f"StickyFingers profile '{chosen[0].name}' is not running. Open it in StickyFingers first."
            )
        return chosen[0]
    running = [p for p in profiles if p.pid is not None]
    if not running:
        raise BrowserError('No StickyFingers profile is running. Open one in StickyFingers first.')
    if len(running) > 1:
        names = ', '.join(p.name for p in running)
        raise BrowserError(f'Several StickyFingers profiles are open; set OPEN_BROWSER_PROFILE to one of: {names}')
    return running[0]


def send_to_singleton(user_data_dir, url):
    # Chromium's ProcessSingleton protocol: START\0<cwd>\0<argv...>, write side closed, reply ACK.
    # SingletonSocket links to a short temp path; the user-data path can exceed AF_UNIX's 104 bytes.
    path = os.path.realpath(Path(user_data_dir) / 'SingletonSocket')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10)
        sock.connect(path)
        sock.sendall('\0'.join(['START', '/', 'open-browser', url]).encode())
        sock.shutdown(socket.SHUT_WR)
        reply = sock.recv(64)
    if not reply.startswith(b'ACK'):
        raise BrowserError(f'StickyFingers browser did not take the URL (reply {reply!r}).')


def current_profile(choice):
    return pick_profile(find_profiles(stickyfingers_root(), socket.gethostname(), live_pids()), choice)


def open_all_in_stickyfingers(urls, choice):
    profile = current_profile(choice)
    for url in urls:
        send_to_singleton(profile.user_data_dir, url)
    bring_to_front(profile.pid)


# --- Sun Browser -----------------------------------------------------------------------------

MAIN_PROCESS_RE = re.compile(r'^\s*(\d+)\s+.*/SunBrowser\.app/Contents/MacOS/SunBrowser\s(.*)$')
USER_DATA_DIR_RE = re.compile(r'--user-data-dir=(.+?)(?=\s--|$)')


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


def pick_instance(instances, profile=None):
    if not instances:
        raise BrowserError('Sun Browser is not running. Open the profile in AdsPower first.')
    if profile:
        instances = [i for i in instances if profile in (i.profile, Path(i.user_data_dir).name)]
        if not instances:
            raise BrowserError(f'No running Sun Browser profile matches OPEN_BROWSER_PROFILE={profile}.')
    if len(instances) > 1:
        ids = ', '.join(i.profile for i in instances)
        raise BrowserError(f'Several Sun Browser profiles are open; set OPEN_BROWSER_PROFILE to one of: {ids}')
    return instances[0]


def devtools_port(instance):
    port_file = Path(instance.user_data_dir) / 'DevToolsActivePort'
    if not port_file.exists():
        raise BrowserError(f'{port_file} is missing; Sun Browser was started without remote debugging.')
    return int(port_file.read_text().split()[0])


def open_in_sun_browser(port, url):
    base = f'http://127.0.0.1:{port}/json'
    with urlopen(Request(f'{base}/new?{quote(url, safe="")}', method='PUT'), timeout=5) as resp:
        target = json.load(resp)
    urlopen(f'{base}/activate/{target["id"]}', timeout=5).close()


def current_instance(profile):
    ps = subprocess.run(['ps', '-axww', '-o', 'pid=,command='], capture_output=True, text=True, check=True)
    return pick_instance(find_instances(ps.stdout), profile)


def open_all_in_sun_browser(urls, profile):
    instance = current_instance(profile)
    port = devtools_port(instance)
    for url in urls:
        open_in_sun_browser(port, url)
    bring_to_front(instance.pid)


# --- Routing ---------------------------------------------------------------------------------


def parse_domains(value):
    if value is None:
        value = DEFAULT_DOMAINS
    return [d for d in (part.strip().lstrip('.').lower() for part in value.split(',')) if d]


def matches(url, domains):
    split = urlsplit(url)
    if split.scheme not in ('http', 'https'):
        return False
    host = split.hostname or ''
    return any(host == d or host.endswith('.' + d) for d in domains)


def open_in_target(target, urls, profile):
    if target == 'stickyfingers':
        open_all_in_stickyfingers(urls, profile)
    elif target == 'sunbrowser':
        open_all_in_sun_browser(urls, profile)
    else:
        raise BrowserError(f'Unknown OPEN_BROWSER_TARGET={target}; use stickyfingers or sunbrowser.')


def main(argv):
    if argv[:1] in (['-h'], ['--help']):
        print(__doc__.strip())
        return 0
    if not argv or any(a.startswith('-') for a in argv):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    target = (os.environ.get('OPEN_BROWSER_TARGET') or DEFAULT_TARGET).strip().lower()
    domains = parse_domains(os.environ.get('OPEN_BROWSER_DOMAINS'))
    routed = [url for url in argv if matches(url, domains)]
    code = 0
    if routed:
        try:
            open_in_target(target, routed, os.environ.get('OPEN_BROWSER_PROFILE'))
        except (BrowserError, OSError, ValueError, KeyError) as e:
            print(f'open-browser: {e}', file=sys.stderr)
            code = 1
    for url in argv:
        if url not in routed:
            code = subprocess.run(['open', url]).returncode or code
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

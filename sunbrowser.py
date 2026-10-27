#!/usr/bin/env python3
"""Open URLs, sending Claude's domains to the running AdsPower Sun Browser.

Usage:
  sunbrowser.py <url>...

Meant to be Claude Code's BROWSER command: Claude Code runs `$BROWSER <url>` whenever it
opens a page (login, artifact links, clicked links). A URL whose host is one of
SUN_BROWSER_DOMAINS (comma-separated, default claude.ai,claude.com) or a subdomain of one
opens as a new tab in Sun Browser; any other URL goes to macOS `open`, the default browser.

Sun Browser is reached through its DevTools HTTP endpoint. AdsPower starts it with
--remote-debugging-port=0, so the port is read from DevToolsActivePort in the profile's
user-data-dir. When Sun Browser is not running the URL is not opened at all: launching
SunBrowser.app directly would skip AdsPower's proxy and fingerprint. Set
SUN_BROWSER_PROFILE to an AdsPower profile id when several profiles are open.
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

MAIN_PROCESS_RE = re.compile(r'^\s*(\d+)\s+.*/SunBrowser\.app/Contents/MacOS/SunBrowser\s(.*)$')
USER_DATA_DIR_RE = re.compile(r'--user-data-dir=(.+?)(?=\s--|$)')
DEFAULT_DOMAINS = 'claude.ai,claude.com'


class SunBrowserError(Exception):
    pass


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
        raise SunBrowserError('Sun Browser is not running. Open the profile in AdsPower first.')
    if profile:
        instances = [i for i in instances if profile in (i.profile, Path(i.user_data_dir).name)]
        if not instances:
            raise SunBrowserError(f'No running Sun Browser profile matches SUN_BROWSER_PROFILE={profile}.')
    if len(instances) > 1:
        ids = ', '.join(i.profile for i in instances)
        raise SunBrowserError(f'Several Sun Browser profiles are open; set SUN_BROWSER_PROFILE to one of: {ids}')
    return instances[0]


def devtools_port(instance):
    port_file = Path(instance.user_data_dir) / 'DevToolsActivePort'
    if not port_file.exists():
        raise SunBrowserError(f'{port_file} is missing; Sun Browser was started without remote debugging.')
    return int(port_file.read_text().split()[0])


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


def open_in_sun_browser(port, url):
    base = f'http://127.0.0.1:{port}/json'
    with urlopen(Request(f'{base}/new?{quote(url, safe="")}', method='PUT'), timeout=5) as resp:
        target = json.load(resp)
    urlopen(f'{base}/activate/{target["id"]}', timeout=5).close()


def bring_to_front(pid):
    # /json/activate only selects the tab. Activating by pid reaches this exact process;
    # `open -a` could start a second, bare SunBrowser outside AdsPower. Best effort.
    script = (
        "ObjC.import('AppKit'); "
        f'$.NSRunningApplication.runningApplicationWithProcessIdentifier({pid})'
        '.activateWithOptions($.NSApplicationActivateAllWindows)'
    )
    subprocess.run(['osascript', '-l', 'JavaScript', '-e', script], capture_output=True)


def current_instance():
    ps = subprocess.run(['ps', '-axww', '-o', 'pid=,command='], capture_output=True, text=True, check=True)
    return pick_instance(find_instances(ps.stdout), os.environ.get('SUN_BROWSER_PROFILE'))


def open_all_in_sun_browser(urls):
    instance = current_instance()
    port = devtools_port(instance)
    for url in urls:
        open_in_sun_browser(port, url)
    bring_to_front(instance.pid)


def main(argv):
    if argv[:1] in (['-h'], ['--help']):
        print(__doc__.strip())
        return 0
    if not argv or any(a.startswith('-') for a in argv):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    domains = parse_domains(os.environ.get('SUN_BROWSER_DOMAINS'))
    sun_urls = [url for url in argv if matches(url, domains)]
    code = 0
    if sun_urls:
        try:
            open_all_in_sun_browser(sun_urls)
        except (SunBrowserError, OSError) as e:
            print(f'sunbrowser: {e}', file=sys.stderr)
            code = 1
    for url in argv:
        if url not in sun_urls:
            code = subprocess.run(['open', url]).returncode or code
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

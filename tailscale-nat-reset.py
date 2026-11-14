#!/usr/bin/env python3
"""Rebuild a Tailscale direct path that a stale NAT session keeps on DERP.

Symptom: `tailscale netcheck` says `UDP: true` on both ends, yet the peer stays
"relay"/"via DERP" (hundreds of ms, packet loss). After a network blip the NAT
here can keep the flow to the peer pinned to an old external port while STUN
advertises a new one, so each side drops the other's packets. Restarting
Tailscale does not help: the local port stays 41641, and Tailscale's own pings
keep the stale session alive.

The fix is to go silent until the NAT forgets that session:
  1. `tailscale down`
  2. delete this host's Tailscale UPnP mappings on the gateway
  3. stay down for --wait seconds, counted on the wall clock, so time the Mac
     spends asleep counts too (caffeinate keeps it awake meanwhile)
  4. bare `tailscale up`, which only sets WantRunning and keeps every other pref
  5. report netcheck and, with --ping, whether the path to the peer is direct

`tailscale down` cuts SSH sessions that ride on Tailscale, so the work runs in
a detached process: dropping the terminal does not stop it. Output is appended
to the log file and followed on screen until it finishes.

  tailscale-nat-reset.py --ping genji        # reset, then check the path to genji
  tailscale-nat-reset.py --dry-run           # show prefs and UPnP mappings, change nothing
  tailscale-nat-reset.py --no-follow         # start it and return at once

Exit status: 0 done (and every --ping peer direct), 1 error, 2 a peer is still
relayed (rerun with a longer --wait). $TAILSCALE points at another CLI.
"""

import argparse
import fcntl
import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

DEFAULT_LOG = os.path.expanduser('~/Library/Logs/tailscale-nat-reset.log')
DEFAULT_WAIT = 600
CLI_CANDIDATES = (
    '/usr/local/bin/tailscale',
    '/opt/homebrew/bin/tailscale',
    '/Applications/Tailscale.app/Contents/MacOS/Tailscale',
)
NOT_LOGGED_IN = ('NeedsLogin', 'NeedsMachineAuth', 'NoState')
SHOWN_PREFS = (
    'RouteAll',
    'CorpDNS',
    'ExitNodeID',
    'ExitNodeIP',
    'ExitNodeAllowLANAccess',
    'AdvertiseRoutes',
    'AdvertiseTags',
    'ShieldsUp',
    'RunSSH',
    'Hostname',
)
NETCHECK_KEYS = ('UDP', 'IPv4', 'IPv6', 'MappingVariesByDestIP', 'PortMapping', 'Nearest DERP')
SSDP_ADDR = ('239.255.255.250', 1900)
IGD_TYPES = (
    'urn:schemas-upnp-org:device:InternetGatewayDevice:1',
    'urn:schemas-upnp-org:device:InternetGatewayDevice:2',
)
WAN_SERVICES = ('WANIPConnection', 'WANPPPConnection')


class ResetError(Exception):
    pass


class KeepHTTPErrors(urllib.request.HTTPErrorProcessor):
    """Hand back 4xx/5xx responses: a SOAP fault is an ordinary answer, e.g. the end of a list."""

    def http_response(self, request, response):
        return response

    https_response = http_response


# No proxies: Clash may register a system proxy, and the gateway is on the LAN.
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}), KeepHTTPErrors)


def log(msg):
    print(f'{datetime.now():%Y-%m-%d %H:%M:%S} {msg}', flush=True)


def find_cli():
    path = os.environ.get('TAILSCALE') or shutil.which('tailscale')
    if path:
        return path
    for candidate in CLI_CANDIDATES:
        if os.access(candidate, os.X_OK):
            return candidate
    raise ResetError('tailscale CLI not found; set TAILSCALE=/path/to/tailscale')


def ts(cli, *args):
    return subprocess.run([cli, *args], capture_output=True, text=True)


def ts_json(cli, *args):
    r = ts(cli, *args)
    if r.returncode != 0:
        raise ResetError(f'`tailscale {" ".join(args)}` failed: {r.stderr.strip()}')
    return json.loads(r.stdout)


def backend_state(cli):
    return ts_json(cli, 'status', '--json').get('BackendState')


def shown_prefs(cli):
    prefs = ts_json(cli, 'debug', 'prefs')
    return {k: prefs[k] for k in SHOWN_PREFS if k in prefs}


def endpoints(cli):
    return ts_json(cli, 'status', '--json').get('Self', {}).get('Addrs')


def lock_path(log_path):
    return log_path + '.lock'


def acquire_lock(path):
    """Hold an exclusive lock for as long as the returned file stays open."""
    f = open(path, 'w')
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return f


def discover_igd(timeout=3.0):
    """Return the LOCATION of the first gateway answering an SSDP search, or None."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for st in IGD_TYPES:
            msg = f'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: {st}\r\n\r\n'
            sock.sendto(msg.encode(), SSDP_ADDR)
        deadline = time.time() + timeout
        while (left := deadline - time.time()) > 0:
            ready, _, _ = select.select([sock], [], [], left)
            if not ready:
                return None
            found = re.search(r'^location:\s*(\S+)', sock.recv(4096).decode(errors='replace'), re.I | re.M)
            if found:
                return found.group(1)
    return None


def wan_service(location):
    """Return (control URL, service type) of the gateway's WAN connection service."""
    with HTTP.open(location, timeout=5) as r:
        root = ET.fromstring(r.read())
    base = root.findtext('{*}URLBase') or location
    for svc in root.iterfind('.//{*}service'):
        stype = svc.findtext('{*}serviceType') or ''
        if any(name in stype for name in WAN_SERVICES):
            return urllib.parse.urljoin(base, svc.findtext('{*}controlURL')), stype
    raise ResetError(f'no WAN connection service in {location}')


def soap(control, service, action, **args):
    body = ''.join(f'<{k}>{v}</{k}>' for k, v in args.items())
    envelope = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{service}">{body}</u:{action}></s:Body></s:Envelope>'
    )
    req = urllib.request.Request(
        control,
        data=envelope.encode(),
        headers={'Content-Type': 'text/xml; charset="utf-8"', 'SOAPAction': f'"{service}#{action}"'},
    )
    with HTTP.open(req, timeout=5) as r:
        return r.status, dict(re.findall(r'<(New\w+)>([^<]*)</\1>', r.read().decode(errors='replace')))


def port_mappings(control, service):
    mappings = []
    for index in range(256):
        status, fields = soap(control, service, 'GetGenericPortMappingEntry', NewPortMappingIndex=index)
        if status != 200:
            break
        mappings.append(fields)
    return mappings


def local_ip_toward(host):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, 1900))
        return s.getsockname()[0]


def tailscale_mappings(mappings, client):
    return [
        m
        for m in mappings
        if 'tailscale' in m.get('NewPortMappingDescription', '').lower()
        and m.get('NewProtocol') == 'UDP'
        and m.get('NewInternalClient') == client
    ]


def clean_upnp(igd, dry_run):
    location = igd or discover_igd()
    if not location:
        log('UPnP: no gateway answered SSDP, nothing to clean')
        return
    control, service = wan_service(location)
    client = local_ip_toward(urllib.parse.urlparse(control).hostname)
    ours = tailscale_mappings(port_mappings(control, service), client)
    log(f'UPnP: {location} holds {len(ours)} Tailscale mapping(s) for {client}: {[m["NewExternalPort"] for m in ours]}')
    for m in ours:
        port = m['NewExternalPort']
        if dry_run:
            log(f'UPnP: dry run, would delete {port}/UDP')
            continue
        status, _ = soap(
            control, service, 'DeletePortMapping', NewRemoteHost='', NewExternalPort=port, NewProtocol='UDP'
        )
        log(f'UPnP: delete {port}/UDP -> HTTP {status}')


def wait_wall_clock(seconds):
    """Sleep in short steps against the wall clock, so time asleep counts: the NAT keeps ticking."""
    deadline = time.time() + seconds
    while (left := deadline - time.time()) > 0:
        time.sleep(min(left, 60))
        if deadline - time.time() > 0:
            log(f'still down, {int(deadline - time.time())}s to go')


def wait_running(cli, timeout=60):
    deadline = time.time() + timeout
    state = None
    while time.time() < deadline:
        state = backend_state(cli)
        if state == 'Running':
            return
        time.sleep(1)
    raise ResetError(f'Tailscale did not reach Running within {timeout}s (state {state})')


def netcheck_summary(cli):
    lines = (line.strip(' \t*') for line in ts(cli, 'netcheck').stdout.splitlines())
    return [line for line in lines if line.startswith(NETCHECK_KEYS)]


def ping_peer(cli, peer):
    """Return (direct?, the most telling output line) for `tailscale ping`, which stops at the first direct pong."""
    r = ts(cli, 'ping', '-c', '10', '--timeout', '3s', peer)
    lines = (r.stdout + r.stderr).strip().splitlines()
    pongs = [line for line in lines if line.startswith('pong from')]
    direct = any(' via DERP' not in line for line in pongs)
    return direct, (pongs[-1] if pongs else (lines[-1] if lines else 'no output'))


def worker(args):
    """Do the reset. Runs detached, writing to the log file through stdout."""
    lock = acquire_lock(lock_path(args.log))
    cli = find_cli()
    log(f'=== tailscale-nat-reset (wait {args.wait}s, cli {cli}{", dry run" if args.dry_run else ""})')
    state = backend_state(cli)
    log(f'backend state: {state}')
    if state in NOT_LOGGED_IN:
        raise ResetError(f'Tailscale is {state}; log in first, a bare `tailscale up` cannot restore it')
    prefs = shown_prefs(cli)
    log(f'prefs to keep: {prefs}')
    log(f'advertised endpoints: {endpoints(cli)}')

    if not args.dry_run and shutil.which('caffeinate'):
        subprocess.Popen(['caffeinate', '-i', '-s', '-w', str(os.getpid())])
    if args.dry_run:
        log('dry run: would run `tailscale down`')
    else:
        r = ts(cli, 'down')
        if r.returncode != 0:
            raise ResetError(f'`tailscale down` failed, nothing changed: {r.stderr.strip()}')
        log('tailscale down')

    if args.no_upnp:
        log('UPnP: skipped (--no-upnp)')
    else:
        try:
            clean_upnp(args.igd, args.dry_run)
        except (OSError, ET.ParseError, ResetError) as e:
            log(f'UPnP: cleanup failed, carrying on without it: {e}')

    if args.dry_run:
        log(f'dry run: would stay down for {args.wait}s, then run a bare `tailscale up`')
        log('RESULT: dry run finished, nothing changed')
        lock.close()
        return 0

    log(f'staying down for {args.wait}s so the NAT forgets the old session')
    wait_wall_clock(args.wait)
    r = ts(cli, 'up')
    if r.returncode != 0:
        raise ResetError(
            f'`tailscale up` failed, TAILSCALE IS STILL DOWN: {(r.stdout + r.stderr).strip()}\n'
            f'  run `tailscale up` by hand or toggle it in the Tailscale app; prefs before the reset: {prefs}'
        )
    wait_running(cli)
    log('tailscale up, backend Running')
    after = shown_prefs(cli)
    if after != prefs:
        log(f'WARNING prefs differ from before: {after}')

    time.sleep(args.settle)
    log(f'advertised endpoints: {endpoints(cli)}')
    for line in netcheck_summary(cli):
        log(f'netcheck: {line}')
    relayed = []
    for peer in args.ping:
        direct, line = ping_peer(cli, peer)
        log(f'ping {peer}: {line}')
        if not direct:
            relayed.append(peer)
    lock.close()

    if relayed:
        log(
            f'RESULT: still relayed to {", ".join(relayed)}. Rerun with a longer wait '
            f'(e.g. --wait {max(args.wait * 3, 1800)}), or check the other side.'
        )
        return 2
    if args.ping:
        log(f'RESULT: direct path to {", ".join(args.ping)}')
    else:
        log('RESULT: Tailscale is back up. Check a peer with `tailscale ping <peer>`, or rerun with --ping <peer>.')
    return 0


def follow(proc, path, offset):
    """Print what the worker appends to the log until it exits; return its exit status."""
    with open(path) as f:
        f.seek(offset)
        while True:
            line = f.readline()
            if line:
                print(line, end='', flush=True)
            elif proc.poll() is not None:
                print(f.read(), end='', flush=True)
                return proc.returncode
            else:
                time.sleep(0.5)


def launch(args):
    """Start the worker in its own session, so a dropped SSH connection cannot stop it halfway."""
    os.makedirs(os.path.dirname(args.log) or '.', exist_ok=True)
    acquire_lock(lock_path(args.log)).close()
    offset = os.path.getsize(args.log) if os.path.exists(args.log) else 0
    with open(args.log, 'a') as out:
        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), '--worker', *sys.argv[1:]],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    print(f'reset running in the background (pid {proc.pid}), log: {args.log}')
    if not args.dry_run:
        print('SSH sessions riding on Tailscale will drop; the reset carries on regardless.')
    if args.no_follow:
        print(f'  tail -f {args.log}')
        return 0
    return follow(proc, args.log, offset)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--wait', type=int, default=DEFAULT_WAIT, help=f'seconds to stay down (default {DEFAULT_WAIT})')
    p.add_argument('--ping', action='append', default=[], metavar='PEER', help='peer to check afterwards, repeatable')
    p.add_argument('--no-upnp', action='store_true', help="leave the gateway's UPnP mappings alone")
    p.add_argument('--igd', metavar='URL', help='gateway description URL, skips SSDP discovery')
    p.add_argument('--dry-run', action='store_true', help='show what would happen, change nothing')
    p.add_argument('--no-follow', action='store_true', help='start the reset and return at once')
    p.add_argument('--log', default=DEFAULT_LOG, help=f'log file (default {DEFAULT_LOG})')
    p.add_argument('--settle', type=int, default=15, help=argparse.SUPPRESS)
    p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    return p.parse_args()


def main():
    args = parse_args()
    try:
        return worker(args) if args.worker else launch(args)
    except BlockingIOError:
        # A worker's stderr is the log file too, so this lands where its caller looks.
        print(f'another reset is already running, see {args.log}', file=sys.stderr)
        return 1
    except ResetError as e:
        log(f'ERROR: {e}')
        return 1
    except KeyboardInterrupt:
        print(f'\nstopped following; the reset carries on in the background, log: {args.log}')
        return 130


if __name__ == '__main__':
    sys.exit(main())

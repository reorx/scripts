#!/usr/bin/env python3
"""Behavior tests for tailscale-nat-reset.py.

Runs the script end to end against a stub `tailscale` (via $TAILSCALE) and a
fake UPnP IGD on 127.0.0.1, so the real tailnet and router are never touched.

  python3 test_tailscale_nat_reset.py
"""

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'tailscale-nat-reset.py')

STUB = r"""#!{python}
import json, os, sys, time
d = os.environ['STUB_DIR']
args = sys.argv[1:]
with open(os.path.join(d, 'calls.log'), 'a') as f:
    f.write('%.3f %s\n' % (time.time(), ' '.join(args)))
state_file = os.path.join(d, 'state')
state = open(state_file).read() if os.path.exists(state_file) else os.environ.get('STUB_STATE', 'Running')
if args == ['status', '--json']:
    print(json.dumps({{'BackendState': state, 'Self': {{'Addrs': ['1.2.3.4:41641']}}}}))
elif args == ['debug', 'prefs']:
    print(json.dumps({{'WantRunning': state == 'Running', 'RouteAll': True, 'CorpDNS': False}}))
elif args == ['down']:
    open(state_file, 'w').write('Stopped')
elif args == ['up']:
    open(state_file, 'w').write('Running')
elif args[:1] == ['netcheck']:
    print('Report:\n\t* UDP: true\n\t* IPv4: yes, 1.2.3.4:5678\n\t* MappingVariesByDestIP: false')
elif args[:1] == ['ping']:
    print(os.environ.get('STUB_PING', 'pong from genji (100.1.1.1) via 5.6.7.8:41641 in 20ms'))
else:
    sys.exit('stub: unexpected %r' % (args,))
"""

IGD_XML = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
 <device>
  <deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType>
  <deviceList><device><deviceList><device>
   <serviceList><service>
    <serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
    <controlURL>/ipc</controlURL>
   </service></serviceList>
  </device></deviceList></device></deviceList>
 </device>
</root>"""


def initial_mappings():
    return [
        {
            'NewExternalPort': '11432',
            'NewProtocol': 'UDP',
            'NewInternalPort': '41641',
            'NewInternalClient': '127.0.0.1',
            'NewPortMappingDescription': 'tailscale-portmap',
        },
        {
            'NewExternalPort': '8080',
            'NewProtocol': 'TCP',
            'NewInternalPort': '80',
            'NewInternalClient': '127.0.0.1',
            'NewPortMappingDescription': 'nas-web',
        },
        {
            'NewExternalPort': '5458',
            'NewProtocol': 'UDP',
            'NewInternalPort': '41641',
            'NewInternalClient': '127.0.0.1',
            'NewPortMappingDescription': 'tailscale-portmap',
        },
        {
            'NewExternalPort': '12000',
            'NewProtocol': 'UDP',
            'NewInternalPort': '41641',
            'NewInternalClient': '192.168.0.200',
            'NewPortMappingDescription': 'tailscale-portmap',
        },
    ]


class FakeIGD:
    """WANIPConnection:1 with GetGenericPortMappingEntry and DeletePortMapping."""

    def __init__(self):
        self.mappings = initial_mappings()
        igd = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, body):
                data = body.encode()
                self.send_response(code)
                self.send_header('Content-Type', 'text/xml')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self.reply(200, IGD_XML) if self.path == '/igd.xml' else self.reply(404, '')

            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length'])).decode()
                action = self.headers['SOAPAction'].strip('"').split('#')[1]
                args = dict(re.findall(r'<(New\w+)>([^<]*)</\1>', body))
                if action == 'GetGenericPortMappingEntry':
                    i = int(args['NewPortMappingIndex'])
                    if i >= len(igd.mappings):
                        return self.reply(500, '<errorCode>713</errorCode>')
                    fields = ''.join(f'<{k}>{v}</{k}>' for k, v in igd.mappings[i].items())
                    return self.reply(200, f'<u:Resp>{fields}</u:Resp>')
                if action == 'DeletePortMapping':
                    before = len(igd.mappings)
                    igd.mappings = [
                        m
                        for m in igd.mappings
                        if (m['NewExternalPort'], m['NewProtocol']) != (args['NewExternalPort'], args['NewProtocol'])
                    ]
                    return self.reply(200 if len(igd.mappings) < before else 500, '')
                self.reply(500, '<errorCode>401</errorCode>')

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}/igd.xml'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def ports(self):
        return sorted(m['NewExternalPort'] for m in self.mappings)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class ResetBehavior(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        stub = os.path.join(self.dir, 'tailscale')
        with open(stub, 'w') as f:
            f.write(STUB.format(python=sys.executable))
        os.chmod(stub, 0o755)
        self.log = os.path.join(self.dir, 'reset.log')
        self.env = dict(os.environ, TAILSCALE=stub, STUB_DIR=self.dir)
        self.igd = FakeIGD()

    def tearDown(self):
        self.igd.close()
        self.tmp.cleanup()

    def run_script(self, *args, env=None, timeout=60):
        cmd = [sys.executable, SCRIPT, '--log', self.log, '--settle', '0', *args]
        return subprocess.run(cmd, env=dict(self.env, **(env or {})), capture_output=True, text=True, timeout=timeout)

    def calls(self):
        path = os.path.join(self.dir, 'calls.log')
        if not os.path.exists(path):
            return []
        with open(path) as f:
            lines = f.read().splitlines()
        return [(float(t), cmd) for t, cmd in (line.split(' ', 1) for line in lines)]

    def commands(self):
        return [cmd for _, cmd in self.calls()]

    def read_log(self):
        with open(self.log) as f:
            return f.read()

    def test_down_then_upnp_cleanup_then_wait_then_bare_up(self):
        r = self.run_script('--wait', '2', '--igd', self.igd.url)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cmds = self.commands()
        self.assertIn('down', cmds)
        self.assertIn('up', cmds, 'restores with a bare `tailscale up`, which keeps every other pref')
        self.assertLess(cmds.index('down'), cmds.index('up'))
        times = dict((cmd, t) for t, cmd in self.calls() if cmd in ('down', 'up'))
        self.assertGreaterEqual(times['up'] - times['down'], 2, 'stays down for --wait seconds')
        self.assertIn('RESULT', r.stdout)

    def test_only_this_hosts_tailscale_udp_mappings_are_deleted(self):
        r = self.run_script('--wait', '0', '--igd', self.igd.url)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.igd.ports(), ['12000', '8080'])

    def test_prefs_before_reset_are_logged_for_manual_recovery(self):
        r = self.run_script('--wait', '0', '--no-upnp')
        self.assertRegex(r.stdout, r'RouteAll.*True')
        self.assertRegex(r.stdout, r'CorpDNS.*False')
        with open(self.log) as f:
            self.assertIn('RESULT', f.read(), 'the same output lands in the log file')

    def test_dry_run_changes_nothing(self):
        r = self.run_script('--wait', '300', '--igd', self.igd.url, '--dry-run', timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('down', self.commands())
        self.assertNotIn('up', self.commands())
        self.assertEqual(len(self.igd.mappings), 4)
        self.assertIn('11432', r.stdout)
        self.assertIn('5458', r.stdout)

    def test_refuses_when_not_logged_in(self):
        r = self.run_script('--wait', '0', '--no-upnp', env={'STUB_STATE': 'NeedsLogin'})
        self.assertEqual(r.returncode, 1)
        self.assertNotIn('down', self.commands())

    def test_unreachable_gateway_does_not_block_the_reset(self):
        r = self.run_script('--wait', '0', '--igd', 'http://127.0.0.1:9/igd.xml')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('up', self.commands())
        self.assertIn('UPnP', r.stdout)

    def test_direct_ping_reports_success(self):
        r = self.run_script('--wait', '0', '--no-upnp', '--ping', 'genji')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any(c.startswith('ping') and c.endswith('genji') for c in self.commands()))
        self.assertRegex(r.stdout, r'RESULT.*direct')

    def test_still_relayed_exits_2_and_suggests_longer_wait(self):
        relayed = 'pong from genji (100.1.1.1) via DERP(hkg) in 300ms'
        r = self.run_script('--wait', '0', '--no-upnp', '--ping', 'genji', env={'STUB_PING': relayed})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('--wait', r.stdout.split('RESULT', 1)[1])

    def test_no_follow_returns_at_once_and_a_second_run_is_refused(self):
        start = time.time()
        first = self.run_script('--wait', '3', '--no-upnp', '--no-follow')
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertLess(time.time() - start, 2.5)
        self.assertIn(self.log, first.stdout)
        time.sleep(0.5)
        second = self.run_script('--wait', '0', '--no-upnp')
        self.assertEqual(second.returncode, 1)
        self.assertIn('already running', second.stdout + second.stderr)
        deadline = time.time() + 30
        while 'RESULT' not in self.read_log() and time.time() < deadline:
            time.sleep(0.5)
        self.assertEqual(self.commands().count('down'), 1)
        self.assertEqual(self.commands().count('up'), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)

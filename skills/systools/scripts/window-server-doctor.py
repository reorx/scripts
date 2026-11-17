#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""WindowServer Doctor: diagnose macOS WindowServer CPU/GPU pressure.

Runs a battery of non-destructive diagnostics to identify *why*
WindowServer is consuming too much CPU. Points at likely culprits so you
can fix the problem without logging out or quitting apps.

Checks performed:
  1. WindowServer process stats (ps)
  2. Thread count / live CPU (top)
  3. Windows per foreground app (osascript -- needs Automation access)
  4. Connected displays + resolution/refresh (system_profiler)
  5. GPU ms/s by process (ioreg AGXDeviceUserClient, no sudo)
  6. WindowServer hot frames (sample -- needs sudo)
  7. WindowServer log warnings (log show)
  8. GPU utilization counters (ioreg)

Only the hot-frames check needs root; it auto-skips otherwise. Rerun with
`sudo -E window-server-doctor.py` to include it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time


CPU_WARN_PCT = 20.0
CPU_HIGH_PCT = 50.0
WINDOW_COUNT_WARN = 60
LOG_WINDOW_MIN = 2
GPU_SAMPLE_SECS = 3.0
GPU_SUSPECT_MS = 5.0  # GPU ms/s above which a client app is named in the verdict

SECTION_LINE = '─' * 66


# ── Subprocess helpers ──────────────────────────────────────
def run(cmd: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def is_root() -> bool:
    return os.geteuid() == 0


def has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


# ── Individual checks ───────────────────────────────────────
def check_process() -> dict:
    r = run(['ps', '-Ao', 'pid,pcpu,pmem,rss,etime,user,comm'], timeout=5)
    for line in r.stdout.splitlines():
        if line.strip().endswith('WindowServer'):
            parts = line.split(None, 6)
            if len(parts) < 7:
                continue
            return {
                'ok': True,
                'pid': int(parts[0]),
                'cpu_pct': float(parts[1]),
                'mem_pct': float(parts[2]),
                'rss_mb': int(parts[3]) / 1024,
                'etime': parts[4],
                'user': parts[5],
            }
    return {'ok': False, 'error': 'WindowServer not found'}


def check_top_threads(pid: int) -> dict:
    r = run(
        ['top', '-l', '2', '-pid', str(pid), '-stats', 'command,cpu,threads,boosts'],
        timeout=6,
    )
    rows = []
    for line in r.stdout.splitlines():
        if 'WindowServer' in line:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    rows.append(
                        {
                            'command': parts[0],
                            'cpu': float(parts[1]),
                            'threads': int(parts[2]),
                        }
                    )
                except ValueError:
                    continue
    # last row is the live sample, not the cumulative one
    return {'ok': bool(rows), 'row': rows[-1] if rows else None}


def check_foreground_apps() -> dict:
    """List foreground (Dock-visible) apps via lsappinfo — fast, no permissions.

    Window counts per app would require Screen Recording permission
    (CGWindowListCopyWindowInfo) or Automation permission (System Events).
    Both are slow or gated; app count is a good-enough proxy for WS load.
    """
    r = run(['lsappinfo', 'list'], timeout=6)
    if r.returncode != 0:
        return {'ok': False, 'error': r.stderr.strip()[:200] or 'lsappinfo failed'}
    apps: list[dict] = []
    current: dict = {}
    for line in r.stdout.splitlines():
        m = re.match(r'\s*\d+\)\s*"([^"]+)"', line)
        if m:
            if current.get('type') == 'Foreground':
                apps.append(current)
            current = {'name': m.group(1), 'type': None, 'pid': None}
            continue
        if 'type="' in line:
            tm = re.search(r'type="([^"]+)"', line)
            if tm:
                current['type'] = tm.group(1)
        pm = re.search(r'\bpid\s*=\s*(\d+)', line)
        if pm and current.get('pid') is None:
            current['pid'] = int(pm.group(1))
    if current.get('type') == 'Foreground':
        apps.append(current)
    return {'ok': True, 'apps': apps, 'count': len(apps)}


def check_windows_per_app_slow() -> dict:
    """Exact per-app window counts via System Events. Requires Automation permission
    and can take 15-25s on a busy system. Opt-in."""
    script = (
        'tell application "System Events"\n'
        '  set output to ""\n'
        '  repeat with p in (every process whose visible is true)\n'
        '    try\n'
        '      set output to output & (name of p) & "|" & (count of windows of p) & linefeed\n'
        '    end try\n'
        '  end repeat\n'
        '  return output\n'
        'end tell'
    )
    r = run(['osascript', '-e', script], timeout=30)
    if r.returncode != 0:
        return {
            'ok': False,
            'error': (r.stderr.strip() or 'osascript failed')
            + ' (grant Automation → System Events permission in Privacy settings)',
        }
    apps, total = [], 0
    for line in r.stdout.splitlines():
        if '|' not in line:
            continue
        name, _, count = line.partition('|')
        try:
            c = int(count.strip())
        except ValueError:
            continue
        if not name.strip():
            continue
        apps.append({'app': name.strip(), 'windows': c})
        total += c
    apps.sort(key=lambda x: x['windows'], reverse=True)
    return {'ok': True, 'apps': apps, 'total': total}


def check_displays() -> dict:
    r = run(['system_profiler', 'SPDisplaysDataType', '-detailLevel', 'mini'], timeout=10)
    if r.returncode != 0:
        return {'ok': False, 'error': r.stderr.strip()}
    keys = ('Resolution', 'UI Looks like', 'Refresh Rate', 'Main Display', 'Mirror')
    keep = []
    for line in r.stdout.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(k + ':') for k in keys):
            keep.append(stripped)
    return {'ok': True, 'lines': keep}


AGX_CLIENTS_CMD = ['ioreg', '-l', '-w0', '-r', '-c', 'AGXDeviceUserClient']
AGX_CLIENT_ID_RE = re.compile(r'<class AGXDeviceUserClient, id (0x[0-9a-fA-F]+)')
AGX_CREATOR_RE = re.compile(r'"IOUserClientCreator" = "pid (\d+), ([^"]*)"')
AGX_GPU_TIME_RE = re.compile(r'"accumulatedGPUTime"=(\d+)')


def check_gpu_by_process(seconds: float = GPU_SAMPLE_SECS, limit: int = 15) -> dict:
    """GPU ms/s per process from two ioreg snapshots `seconds` apart. No sudo needed."""
    before = parse_agx_clients(run(AGX_CLIENTS_CMD, timeout=10).stdout)
    t0 = time.monotonic()
    if not before:
        return {'ok': False, 'error': 'no AGXDeviceUserClient in ioreg (Apple Silicon only)'}
    time.sleep(seconds)
    after = parse_agx_clients(run(AGX_CLIENTS_CMD, timeout=10).stdout)
    elapsed = time.monotonic() - t0
    rows = gpu_rates(before, after, elapsed)[:limit]
    if rows:
        ps = run(['ps', '-o', 'pid=,comm=', '-p', ','.join(str(r['pid']) for r in rows)], timeout=5)
        apply_full_names(rows, ps.stdout)
    return {'ok': True, 'tasks': rows, 'seconds': round(elapsed, 2)}


def parse_agx_clients(output: str) -> dict[str, dict]:
    """GPU time of every AGXDeviceUserClient, keyed by its registry id.

    Each process that uses the GPU holds one or more clients; a client's AppUsage lists
    accumulatedGPUTime (nanoseconds) per command queue. This is the counter behind
    Activity Monitor's GPU Time column, readable without root.
    """
    clients: dict[str, dict] = {}
    for block in output.split('+-o ')[1:]:
        reg_id = AGX_CLIENT_ID_RE.search(block)
        creator = AGX_CREATOR_RE.search(block)
        if not reg_id or not creator:
            continue
        clients[reg_id.group(1)] = {
            'pid': int(creator.group(1)),
            'name': creator.group(2),
            'gpu_ns': sum(int(t) for t in AGX_GPU_TIME_RE.findall(block)),
        }
    return clients


def gpu_rates(before: dict[str, dict], after: dict[str, dict], seconds: float) -> list[dict]:
    """Per-process GPU ms/s, busiest first; processes without new GPU work are left out.

    Diffed per client, not per process: a process that closes a client and opens another
    would otherwise show its old client's whole lifetime as a negative rate. A client
    absent from `before` was opened during the window, so all of its time counts.
    """
    per_pid: dict[int, dict] = {}
    for reg_id, c in after.items():
        prev = before.get(reg_id)
        delta = c['gpu_ns'] - (prev['gpu_ns'] if prev else 0)
        if delta <= 0:
            continue
        row = per_pid.setdefault(c['pid'], {'pid': c['pid'], 'name': c['name'], 'gpu_ns': 0})
        row['gpu_ns'] += delta
    rows = [{'pid': r['pid'], 'name': r['name'], 'gpu_ms': r['gpu_ns'] / 1e6 / seconds} for r in per_pid.values()]
    rows.sort(key=lambda r: r['gpu_ms'], reverse=True)
    return rows


def apply_full_names(rows: list[dict], ps_output: str) -> None:
    """Replace ioreg's 16-char process names with the executable name from `ps -o pid=,comm=`."""
    names = {}
    for line in ps_output.splitlines():
        pid, _, comm = line.strip().partition(' ')
        if pid.isdigit() and comm.strip():
            names[int(pid)] = os.path.basename(comm.strip())
    for r in rows:
        r['name'] = names.get(r['pid'], r['name'])


def check_sample(pid: int, duration: int = 3) -> dict:
    if not has('sample'):
        return {'ok': False, 'error': 'sample tool not found'}
    r = run(['sample', str(pid), str(duration), '-mayDie'], timeout=duration + 15)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or '').strip()
        if 'requires root' in msg.lower() or 'permission' in msg.lower() or not is_root():
            return {'ok': False, 'skipped': True, 'reason': 'sampling WindowServer requires sudo'}
        return {'ok': False, 'error': msg[:300] or 'sample failed'}
    return {'ok': True, 'hot_frames': parse_sample_top_of_stack(r.stdout, top_n=10)}


def parse_sample_top_of_stack(output: str, top_n: int = 10) -> list[dict]:
    results = []
    in_section = False
    for line in output.splitlines():
        if 'Sort by top of stack' in line:
            in_section = True
            continue
        if not in_section:
            continue
        if not line.strip():
            if results:
                break
            continue
        m = re.match(r'\s+(.+?)\s+(\d+)\s*$', line)
        if m:
            results.append({'frame': m.group(1).strip(), 'samples': int(m.group(2))})
        if len(results) >= top_n:
            break
    return results


def check_log_warnings() -> dict:
    r = run(
        [
            'log',
            'show',
            '--predicate',
            'process == "WindowServer"',
            '--last',
            f'{LOG_WINDOW_MIN}m',
            '--info',
            '--style',
            'compact',
        ],
        timeout=20,
    )
    if r.returncode != 0:
        return {'ok': False, 'error': (r.stderr or 'log show failed').strip()[:200]}
    warnings, errors = [], []
    for line in r.stdout.splitlines():
        low = line.lower()
        if '<error>' in low or ' error ' in low or 'failed' in low:
            errors.append(line)
        elif '<warn' in low or 'warning' in low or 'throttl' in low or 'timeout' in low:
            warnings.append(line)
    return {
        'ok': True,
        'warnings_count': len(warnings),
        'errors_count': len(errors),
        'samples': (errors + warnings)[:6],
    }


def check_ioreg_gpu() -> dict:
    r = run(['ioreg', '-r', '-c', 'IOAccelerator', '-d', '1', '-l'], timeout=6)
    if r.returncode != 0 or not r.stdout.strip():
        r = run(['ioreg', '-r', '-c', 'AGXAccelerator', '-d', '1', '-l'], timeout=6)
    m = re.search(r'"PerformanceStatistics"\s*=\s*\{([^}]*)\}', r.stdout, re.DOTALL)
    if not m:
        return {'ok': False, 'error': 'PerformanceStatistics not found in ioreg'}
    stats = {kv.group(1): int(kv.group(2)) for kv in re.finditer(r'"([^"]+)"\s*=\s*(\d+)', m.group(1))}
    interesting = {k: v for k, v in stats.items() if 'Utilization' in k or 'Busy' in k or 'Active' in k}
    return {'ok': True, 'stats': interesting or stats}


# ── Presentation ────────────────────────────────────────────
def status_label(cpu: float) -> str:
    if cpu >= CPU_HIGH_PCT:
        return '⚠️  HIGH'
    if cpu >= CPU_WARN_PCT:
        return '⚠️  elevated'
    return '✅ normal'


def fmt_kv(pairs: list[tuple[str, str]], indent: int = 2) -> str:
    if not pairs:
        return ''
    width = max(len(k) for k, _ in pairs)
    pad = ' ' * indent
    return '\n'.join(f'{pad}{k:<{width}}  {v}' for k, v in pairs)


def section(title: str, body: str) -> None:
    print()
    print(f'[{title}]')
    print(body if body else '  (empty)')


def banner(title: str) -> None:
    print()
    print(SECTION_LINE)
    print(f'  {title}')
    print(SECTION_LINE)


def format_apps(apps: list[dict], limit: int = 10) -> str:
    if not apps:
        return '  (no apps found)'
    top = apps[:limit]
    width = max(len(a['app']) for a in top)
    return '\n'.join(f'  {a["app"]:<{width}}  {a["windows"]:>3}' for a in top)


def format_gpu_tasks(tasks: list[dict], limit: int = 12) -> str:
    if not tasks:
        return '  (no process used the GPU during the sample)'
    top = tasks[:limit]
    width = max(len(t['name']) for t in top)
    out = [f'  {"NAME":<{width}}  {"PID":>6}  {"GPU ms/s":>9}']
    for t in top:
        out.append(f'  {t["name"]:<{width}}  {t["pid"]:>6}  {t["gpu_ms"]:>9.1f}')
    return '\n'.join(out)


def format_frames(frames: list[dict]) -> str:
    if not frames:
        return '  (no hot frames)'
    width = min(max(len(f['frame']) for f in frames), 70)
    return '\n'.join(f'  {f["frame"][:70]:<{width}}  {f["samples"]:>5}' for f in frames)


def build_verdict(proc: dict, gpu: dict, windows: dict, displays: dict) -> list[str]:
    lines = []
    cpu = proc.get('cpu_pct', 0.0)
    lines.append(f'WindowServer CPU: {cpu:.1f}%  {status_label(cpu)}')

    if cpu < CPU_WARN_PCT:
        lines.append('Reading looks normal. If WS was spiking earlier, rerun during the spike.')
        return lines

    suspects = []
    if gpu.get('ok'):
        for t in gpu.get('tasks', []):
            if t['name'] == 'WindowServer' or t['gpu_ms'] <= GPU_SUSPECT_MS:
                continue
            suspects.append(f'GPU user: {t["name"]} ({t["gpu_ms"]:.1f} ms/s)')
            if len(suspects) >= 3:
                break

    if windows.get('ok'):
        if windows.get('mode') == 'slow':
            total = windows.get('total', 0)
            if total >= WINDOW_COUNT_WARN and windows.get('apps'):
                top = windows['apps'][0]
                suspects.append(f'Many visible windows: {total} total; {top["app"]} alone has {top["windows"]}')
        else:
            fg = windows.get('count', 0)
            if fg >= 25:
                suspects.append(f'{fg} foreground apps running — many compositing surfaces')

    if displays.get('ok'):
        high_refresh = [ln for ln in displays.get('lines', []) if '120.00Hz' in ln or '120 Hz' in ln]
        if len(high_refresh) >= 2:
            suspects.append('Multiple 120Hz displays — compositing cost is ~2× 60Hz')

    if suspects:
        lines.append('Likely contributors:')
        for s in suspects:
            lines.append(f'  • {s}')
    else:
        lines.append('Heuristics could not pin a clear cause — check log samples and hot frames above.')

    lines.append('')
    lines.append('Non-disruptive next steps:')
    lines.append("  • Cmd+H the top GPU user's app to stop compositing (it keeps running).")
    lines.append("  • If it's a browser, find the animated tab via its built-in task manager.")
    lines.append('  • System Settings → Accessibility → Display: Reduce transparency + Reduce motion.')
    lines.append('  • Switch video/dynamic wallpaper to a static image.')
    lines.append('  • Unplug unused external displays or drop them to 60Hz.')
    return lines


def render_text(r: dict) -> None:
    banner('WindowServer Doctor')

    p = r['process']
    section(
        '1. WindowServer process',
        fmt_kv(
            [
                ('PID', str(p['pid'])),
                ('CPU%', f'{p["cpu_pct"]:.1f}   {status_label(p["cpu_pct"])}'),
                ('RSS', f'{p["rss_mb"]:.0f} MB'),
                ('Uptime', p['etime']),
                ('User', p['user']),
            ]
        ),
    )

    tt = r['top_threads']
    row = tt.get('row') if tt.get('ok') else None
    if row:
        section(
            '2. Live thread stats (top)',
            fmt_kv(
                [
                    ('Threads', str(row.get('threads', '?'))),
                    ('CPU (live)', f'{row.get("cpu", 0.0):.1f}%'),
                ]
            ),
        )

    w = r['windows']
    if w.get('mode') == 'slow':
        if w.get('ok'):
            body = f'  total visible windows: {w["total"]}\n' + format_apps(w['apps'])
            section('3. Windows per visible app (top 10)', body)
        else:
            section('3. Windows per visible app', f'  skipped: {w.get("error")}')
    else:
        if w.get('ok'):
            top = w['apps'][:15]
            lines = [f'  foreground apps: {w["count"]}']
            if top:
                width = max(len(a['name']) for a in top)
                for a in top:
                    lines.append(f'  {a["name"]:<{width}}  pid={a["pid"]}')
            lines.append('  (rerun with --slow-windows for exact window counts per app)')
            section('3. Foreground apps (lsappinfo)', '\n'.join(lines))
        else:
            section('3. Foreground apps', f'  skipped: {w.get("error")}')

    d = r['displays']
    if d.get('ok'):
        if d['lines']:
            section('4. Displays', '\n'.join(f'  {ln}' for ln in d['lines']))
        else:
            section('4. Displays', '  (no details available)')
    else:
        section('4. Displays', f'  skipped: {d.get("error")}')

    pm = r['gpu']
    if pm.get('ok'):
        section(
            f'5. GPU ms/s by process (ioreg, over {pm["seconds"]:.1f}s; 1000 = GPU fully busy)',
            format_gpu_tasks(pm['tasks']),
        )
    else:
        section('5. GPU ms/s by process', f'  skipped: {pm.get("error")}')

    s = r['sample']
    if s.get('ok'):
        section('6. WindowServer hot frames (sample)', format_frames(s['hot_frames']))
    else:
        section('6. WindowServer hot frames', f'  skipped: {s.get("reason") or s.get("error")}')

    lg = r['log']
    if lg.get('ok'):
        body = fmt_kv(
            [
                (f'Warnings (last {LOG_WINDOW_MIN}m)', str(lg['warnings_count'])),
                (f'Errors   (last {LOG_WINDOW_MIN}m)', str(lg['errors_count'])),
            ]
        )
        if lg.get('samples'):
            body += '\n  samples:\n' + '\n'.join(f'    {ln[:160]}' for ln in lg['samples'])
        section('7. WindowServer log', body)
    else:
        section('7. WindowServer log', f'  skipped: {lg.get("error")}')

    ig = r['ioreg_gpu']
    if ig.get('ok'):
        pairs = [(k, str(v)) for k, v in ig['stats'].items()]
        section('8. GPU utilization (ioreg)', fmt_kv(pairs) or '  (empty)')
    else:
        section('8. GPU utilization (ioreg)', f'  skipped: {ig.get("error")}')

    banner('Verdict')
    for line in build_verdict(p, pm, w, d):
        print(line)


# ── Main ────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description='Diagnose macOS WindowServer CPU/GPU pressure without logging out or quitting apps.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Everything but the WindowServer hot frames works without sudo.\n'
            'Run with `sudo -E` to add them (sample).\n'
            'Use --quick to skip that sample even when root.\n'
        ),
    )
    parser.add_argument('--quick', action='store_true', help='Skip the sudo-only WindowServer sample.')
    parser.add_argument(
        '--gpu-seconds',
        type=float,
        default=GPU_SAMPLE_SECS,
        help=f'Window over which per-process GPU time is measured (default {GPU_SAMPLE_SECS:g}).',
    )
    parser.add_argument(
        '-d', '--sample-duration', type=int, default=3, help='Duration of WindowServer sample in seconds (default 3).'
    )
    parser.add_argument(
        '--slow-windows',
        action='store_true',
        help='Enumerate exact window counts per app via System Events (15-25s, needs Automation permission).',
    )
    parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON instead of human output.')
    args = parser.parse_args()

    if sys.platform != 'darwin':
        print('window-server-doctor: macOS only.', file=sys.stderr)
        return 2

    results: dict[str, dict] = {}
    results['process'] = check_process()
    if not results['process'].get('ok'):
        print(f'Could not find WindowServer: {results["process"].get("error")}', file=sys.stderr)
        return 2
    pid = results['process']['pid']

    results['top_threads'] = check_top_threads(pid)
    if args.slow_windows:
        r = check_windows_per_app_slow()
        r['mode'] = 'slow'
        results['windows'] = r
    else:
        r = check_foreground_apps()
        r['mode'] = 'fast'
        results['windows'] = r
    results['displays'] = check_displays()
    results['log'] = check_log_warnings()
    results['ioreg_gpu'] = check_ioreg_gpu()
    results['gpu'] = check_gpu_by_process(args.gpu_seconds)

    if args.quick:
        results['sample'] = {'ok': False, 'skipped': True, 'reason': '--quick'}
    else:
        results['sample'] = check_sample(pid, duration=args.sample_duration)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        render_text(results)

    cpu = results['process']['cpu_pct']
    return 1 if cpu >= CPU_WARN_PCT else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.TimeoutExpired as exc:
        print(f'Timed out running: {" ".join(exc.cmd)}', file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)

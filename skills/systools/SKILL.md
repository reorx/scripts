---
name: systools
description: "System ops toolkit for ports and macOS diagnostics. Use for: inspecting or killing processes on a port (\"what's on 3000\", \"port 8080 is taken\"); macOS health snapshots — CPU temp, load, memory, swap, disk, network (\"how's my mac\", \"is it overheating\"); live memory I/O pressure — pageouts, swap churn, compressor activity (\"why is my mac slow\", \"is it swapping\"); WindowServer CPU/GPU diagnostics (\"WindowServer is hot\", \"UI feels laggy\"); and listing/managing macOS Background Task Management items shown in System Settings. macOS-only except port management."
---

# systools

A collection of tools and best practices for common system operations during local development and debugging.

## Port Management

### Check / kill process on a port

**Script:** `scripts/portcheck.sh`

Use this when a user wants to inspect what's running on a port, get detailed process info, or free up a port.

**How to use:**

```bash
# Check what's on a port (info only, no killing)
bash <skill-path>/scripts/portcheck.sh <port>

# Check and kill
bash <skill-path>/scripts/portcheck.sh -k <port>
bash <skill-path>/scripts/portcheck.sh --kill <port>
```

The script displays a key-value report for each process on the port:
- COMMAND, PID, PPID, USER, STAT, %CPU, %MEM, START — from `ps`
- TYPE, NAME — from `lsof` (connection type and address)
- CWD — the process's working directory

With `-k`/`--kill`, the processes are killed after displaying info.

**Typical scenarios:**
- "What's running on port 3000?" → run without `-k`
- "Port 8080 is taken" / "address already in use" → run without `-k` first to show the user, then with `-k` if they confirm
- "Kill whatever is on port 5173" → run with `-k` directly

## macOS Health Check

### System health overview

**Script:** `scripts/mac-health`

**Prerequisites:** macOS only. The script uses `uv run --script` and depends on `psutil`. For CPU temperature, `smctemp` must be installed (`brew tap narugit/tap && brew install smctemp`).

A single command that checks CPU temperature, network throughput, CPU load, memory, swap, and disk usage — all with configurable thresholds. Each metric shows a ✅ or ⚠️ status. The script exits with code 1 if any threshold is exceeded.

**How to use:**

```bash
# Run the health check with default thresholds
<skill-path>/scripts/mac-health

# Override specific thresholds via -t flags
<skill-path>/scripts/mac-health -t cpu_temp_c=60 -t swap_used_gb=0

# Use a custom config file
<skill-path>/scripts/mac-health -c /path/to/config.json

# Generate a config file with defaults at ~/.config/machealth.json
<skill-path>/scripts/mac-health --init-config
```

**What it checks:**

| Metric | Key | Default Threshold |
|--------|-----|-------------------|
| CPU Temperature | `cpu_temp_c` | 80 °C |
| Network RX | `net_rx_mbps` | 50 Mbps |
| Network TX | `net_tx_mbps` | 50 Mbps |
| CPU Load (% of cores) | `cpu_load_pct` | 80% |
| Memory Used | `mem_used_pct` | 85% |
| Swap Used | `swap_used_gb` | 4 GB |
| Disk Used | `disk_used_pct` | 90% |

**Typical scenarios:**
- "How's my system doing?" / "check my mac health" → run `mac-health` and summarize the output
- "Is my CPU overheating?" → run `mac-health` and focus on the CPU Temp line
- "My mac feels slow" → run `mac-health` to check CPU load, memory, and swap — high swap or memory pressure often explains perceived slowness
- "How much disk space do I have?" → run `mac-health` and highlight the Disk lines (it auto-detects external volumes under /Volumes)
- "Swap is too high" → run `mac-health -t swap_used_gb=0` to flag any swap usage

## macOS Memory I/O Analytics

### Monitor memory paging and swap activity

**Script:** `scripts/mac-mem-io`

**Prerequisites:** macOS only. Uses `uv run --script` with Python ≥3.11 (no third-party deps). Calls `vm_stat`, `sysctl vm.swapusage`, and `memory_pressure` under the hood.

This script samples virtual-memory counters at regular intervals and reports real-time I/O rates — page-ins/outs, swap-ins/outs, and compressor activity. It answers the question: "Is my Mac *actively* under memory pressure right now?" as opposed to `mac-health` which gives a point-in-time snapshot of total usage.

**How to use:**

```bash
# Default: 5 samples at 1-second intervals
<skill-path>/scripts/mac-mem-io

# Custom: 10 samples at 2-second intervals
<skill-path>/scripts/mac-mem-io -i 2 -n 10
```

**Output columns:**

| Column | Meaning |
|--------|---------|
| `swap_used` | Current swap in use (GB). High alone doesn't mean trouble — can be historical residue. |
| `swap_free` | Free swap remaining (GB). |
| `mem_free` | System-wide memory free % from `memory_pressure`. |
| `pageins` | Rate of VM pages read into memory (MiB/s). Small non-zero values are common. |
| `pageouts` | Rate of VM pages written out (MiB/s). Sustained non-zero = pressure. |
| `swapins` | Rate of pages read back from swap (MiB/s). Sustained non-zero = swap churn. |
| `swapouts` | Rate of pages written to swap (MiB/s). Sustained non-zero = swap churn. |
| `compress` | Pages compressed per second. High sustained values = tightening memory. |
| `decompress` | Pages decompressed per second. Some activity is normal. |

**Exit code:** 0 if no pageouts/swapins/swapouts detected across all samples, 1 if any were observed. This makes it composable in scripts or health checks.

**How to interpret results:**

- High `swap_used` alone does NOT mean current performance trouble — it may be left over from earlier.
- If `pageouts`, `swapins`, and `swapouts` stay near zero, current memory I/O pressure is low regardless of swap_used.
- If `pageouts` or swap traffic keep rising every sample and the machine feels slow, memory pressure is real.
- Use `mac-health` first for a quick snapshot; reach for `mac-mem-io` when you need to see whether pressure is *active and ongoing*.

**Typical scenarios:**
- "Is my mac swapping right now?" / "memory pressure?" → run `mac-mem-io` and check if pageouts/swapins/swapouts are non-zero
- "My mac feels slow, is it memory?" → run `mac-health` first for overview, then `mac-mem-io` to see if there's active paging
- "Watch memory for the next 30 seconds" → run `mac-mem-io -i 2 -n 15`
- "Is the compressor working hard?" → run `mac-mem-io` and look at compress/decompress columns
- After closing heavy apps: "Did that help?" → run `mac-mem-io -n 3` to confirm pressure dropped

## macOS WindowServer Diagnostics

### Find out why WindowServer is hot

**Script:** `scripts/window-server-doctor.py`

**Prerequisites:** macOS only. Uses `uv run --script` with Python ≥3.11 (no third-party deps). Wraps `ps`, `top`, `lsappinfo`, `system_profiler`, `log show`, `ioreg`, optionally `powermetrics` and `sample` (those two need sudo).

When WindowServer is burning CPU, the goal is to find which *other* app is driving its rendering work — so the user can fix it without logging out or quitting apps. This script runs 8 checks and emits a verdict that names likely contributors.

**How to use:**

```bash
# Fast partial run (no sudo): process stats, foreground apps, displays, log, ioreg
<skill-path>/scripts/window-server-doctor.py --quick

# Full diagnostic with sudo (enables powermetrics GPU-by-process + sample hot frames)
sudo -E <skill-path>/scripts/window-server-doctor.py

# Opt in to exact window counts per app (15-25s, needs Automation permission)
<skill-path>/scripts/window-server-doctor.py --slow-windows

# Machine-readable output
<skill-path>/scripts/window-server-doctor.py --json
```

**What it checks:**

| # | Check | Needs sudo? |
|---|-------|-------------|
| 1 | WindowServer PID/CPU/RSS/uptime (`ps`) | No |
| 2 | Live thread count + CPU (`top`) | No |
| 3 | Foreground apps (`lsappinfo`) — or exact windows/app with `--slow-windows` (System Events) | No |
| 4 | Connected displays, resolution, refresh rate (`system_profiler`) | No |
| 5 | Per-process GPU ms/s (`powermetrics --show-process-gpu`) | **Yes** |
| 6 | WindowServer hot call stacks, top-of-stack aggregation (`sample`) | **Yes** |
| 7 | Recent WindowServer warnings/errors (`log show`) | No |
| 8 | GPU utilization counters (`ioreg` / `PerformanceStatistics`) | No |

**Exit code:** 0 if WindowServer CPU < 20%, 1 if elevated (≥20%), 2 on hard errors. Composable in scripts.

**How to interpret results:**

- WindowServer itself is almost never the root cause — it reflects compositing work driven by *other* apps. Check #5 (GPU ms/s by process) names the real culprit.
- High CPU + multiple 120Hz displays + many foreground apps is a common "death by a thousand cuts" pattern, not a single rogue process.
- Hot frame `CGXComposeSurfaces` / `CARenderServer*` means compositing load (too many surfaces updating). `mach_msg_trap` on top usually means WS is mostly idle.
- Log errors like "pid X failed to act on a ping" point at a specific misbehaving client process — resolve PID X with `ps -p X` to see who.

**Typical scenarios:**
- "WindowServer is using 60% CPU, what's wrong?" → run with `sudo -E` for full coverage, focus on section 5 + verdict
- "My Mac UI is laggy but Activity Monitor doesn't show a CPU hog" → run `--quick` first; if WS is the top, rerun with sudo for GPU breakdown
- "Which app is burning the GPU?" → `sudo -E window-server-doctor.py --quick` then look at section 5 isn't available under `--quick`; drop `--quick` instead
- "Do I have too many windows open?" → run with `--slow-windows` to see per-app window counts
- Non-disruptive fixes: Cmd+H the top GPU consumer, reduce transparency/motion in Accessibility, switch dynamic wallpaper to static, unplug unused external displays

## macOS Background Task Management (Login Items & Extensions)

### List, search, and locate background items

**Script:** `scripts/btmlist.py`

**Prerequisites:** macOS only. Pure stdlib Python ≥3.10 — no `uv`, no third-party deps. Wraps `sfltool dumpbtm` (built into macOS).

System Settings > General > Login Items & Extensions is backed by the Background Task Management (BTM) database. The UI is awkward: developer-account names (e.g. "won fen", "Bjango Pty Ltd") appear as parent group headers without a "Show in Finder" option, so users often can't tell what a mystery entry actually points to. This script parses `sfltool dumpbtm` and exposes every item as a flat, filterable, locatable list.

**How to use:**

```bash
# Default: table of every real item (skips developer group headers)
<skill-path>/scripts/btmlist.py

# Include developer-account group headers (rows like "won fen" with no path)
<skill-path>/scripts/btmlist.py --all

# Find a mystery entry by name (case-insensitive substring; --all so groups are included)
<skill-path>/scripts/btmlist.py --name 'won fen' --all

# All items signed by a given developer
<skill-path>/scripts/btmlist.py --developer 'won fen'

# Status / type filters
<skill-path>/scripts/btmlist.py --enabled
<skill-path>/scripts/btmlist.py --disabled
<skill-path>/scripts/btmlist.py --type 'legacy agent'

# Other output formats
<skill-path>/scripts/btmlist.py --json     # structured, includes URL + identifier + parent
<skill-path>/scripts/btmlist.py --paths    # one path per line, scriptable

# Open the matching item's executable in Finder (useful for the mystery-entry case)
<skill-path>/scripts/btmlist.py --reveal --name 'Clash Verge'

# Offline analysis: feed in a saved dump
sfltool dumpbtm > /tmp/btm.txt
<skill-path>/scripts/btmlist.py --input /tmp/btm.txt
```

**Output columns (table mode):**

| Column | Meaning |
|--------|---------|
| `STATUS` | `on` (enabled), `off` (disabled), `?` (unknown disposition) |
| `TYPE` | `app`, `login item`, `agent`, `legacy agent`, `daemon`, `legacy daemon`, `dock tile`, `quicklook`, `spotlight`, `developer` (group header) |
| `NAME` | Item name as registered with BTM |
| `DEVELOPER` | Apple developer-account name (the parent grouping in System Settings) |
| `PATH` | Resolved filesystem path — `Executable Path` if present, otherwise the decoded `URL` |

**How to interpret results:**

- "Developer" rows are not real background items — they are the parent group header that shows up in System Settings (e.g. the spooky "won fen" or "Serhiy Mytrovtsiy" entries). They contain other items as children.
- `legacy agent` / `legacy daemon` items come from old-style `LaunchAgents`/`LaunchDaemons` plists. The `URL:` field in `--json` output points at the actual `.plist`, and `PATH`/`Executable Path` points at the binary — both are what you'd remove for full uninstall.
- `app` and `login item` types correspond to the SMAppService-registered entries used by modern apps to autostart.
- A mystery name in System Settings is almost always either (a) a developer-account name styled differently from the app's marketing name, or (b) a privileged helper bundled inside an app's `Contents/Library/...`. `--name <x> --all` finds (a); `--developer <x>` lists all the children behind it.

**Typical scenarios:**

- "What is this WONFEN / unknown entry in Login Items?" → `btmlist.py --name '<entry>' --all` to see the developer row, then `btmlist.py --developer '<entry>'` to list the actual apps/helpers underneath
- "List everything autostarting on my Mac" → `btmlist.py --enabled` for a clean overview
- "Where is this login item actually located? System Settings won't tell me." → `btmlist.py --name '<name>' --reveal` opens Finder at the binary
- "Show me all launch daemons" → `btmlist.py --type daemon` (or `--type 'legacy daemon'`)
- "Audit disabled-but-still-installed background items" → `btmlist.py --disabled`
- "Diff what's registered before/after installing an app" → save `btmlist.py --json` snapshots and compare
- Removal workflow: disable in System Settings (or `launchctl bootout`), then delete the `.plist` shown in the `URL` field and the `Executable Path` binary; `sudo sfltool resetbtm` rebuilds the BTM list if it gets corrupt (re-prompts for everything, use sparingly)

---
name: systools
description: "System ops toolkit for ports and macOS diagnostics. Use for: inspecting or killing processes on a port (\"what's on 3000\", \"port 8080 is taken\"); macOS health snapshots — CPU temp, load, memory, swap, disk, network (\"how's my mac\", \"is it overheating\"); live memory I/O pressure — pageouts, swap churn, compressor activity (\"why is my mac slow\", \"is it swapping\"); releasing leaked dev test resources — booted iOS simulators and agent-browser headless Chrome (\"clean up simulators\", \"close all agent-browser\", \"清理模拟器\", teardown after browser/iOS testing); WindowServer CPU/GPU diagnostics (\"WindowServer is hot\", \"UI feels laggy\"); managing the daily wake/sleep schedule via pmset (\"schedule my mac to sleep at 1am\", \"change the auto sleep time\", \"自动休眠计划\"); auditing launchd + cron scheduled jobs and whether they are actually loaded (\"what runs periodically\", \"why isn't my launch agent running\", \"定时任务\", \"launchd 有哪些\"); and listing/managing macOS Background Task Management items shown in System Settings. macOS-only except port management."
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

## macOS Dev Resource Cleanup

### Release leaked iOS simulators and agent-browser sessions

**Script:** `scripts/mac-dev-cleanup`

**Prerequisites:** macOS only. Uses `uv run --script` with Python ≥3.11 (no third-party deps). Wraps `ps`, `xcrun simctl`, `agent-browser close`, `osascript`, `memory_pressure`.

The two biggest recurring causes of a degraded `mac-health` reading, and neither cleans up after itself:

- **Booted iOS simulators** — each booted device keeps a full `launchd_sim` tree alive: SpringBoard plus dozens of iOS widget extensions at 200–330 MB each. One booted device measured **~196 processes**.
- **Leaked `agent-browser` sessions** — the CLI spawns a detached daemon (PPID 1) plus a ~10-process headless Chrome tree that survives the session that created it. Observed running for **days**, with renderers pinned at ~100% CPU each, ~5 of 10 cores gone.

**How to use:**

```bash
# See what would be cleaned, change nothing (exit 1 = there is work to do)
mac-dev-cleanup --dry-run

# Clean both
mac-dev-cleanup

# Only one side
mac-dev-cleanup --only sim
mac-dev-cleanup --only browser

# Safe to run mid-session: spare agent-browser sessions younger than 2h
mac-dev-cleanup --min-age 2

# Behaviour checks (29 assertions, no side effects)
mac-dev-cleanup --selftest
```

**What it does:**

| Step | Action |
|------|--------|
| agent-browser | Groups Chrome processes into sessions by `--user-data-dir=…/agent-browser-chrome-<uuid>`, links each to its spawning daemon via the root process's PPID, then `agent-browser close --all`, then SIGTERM→SIGKILL any survivor |
| simulators | `xcrun simctl shutdown all`, then quit Simulator.app via AppleScript, falling back to signals when it refuses |
| report | Free-memory % and swap before/after |

**Exit code:** 0 on success. Under `--dry-run`, 1 means there is something to clean — composable as a check like `mac-health`.

**Notes / gotchas:**

- **The user's own Chrome is never touched.** Session membership is decided solely by the `agent-browser-chrome-<uuid>` user-data-dir; a plain `/Applications/Google Chrome.app/…/Google Chrome` has no such flag. This is covered by explicit safety assertions in `--selftest`.
- `ps` truncates the command column to terminal width unless `-ww` is passed, which silently hides processes whose `--user-data-dir` sits past the cutoff — the script always uses `ps -Awwo`. Any ad-hoc `ps | grep` for these processes needs the same flag or it will undercount.
- `agent-browser close --all` is all-or-nothing, so `--min-age` switches to selective signalling instead of calling it.
- `simctl shutdown all` preserves device data; only running-app state is lost, and devices re-boot on demand.
- Simulator.app routinely ignores `quit app "Simulator"`; the signal fallback is the normal path, not an error.
- Counting these processes by hand with `ps -A | grep -c <pattern>` self-matches the grep and the parent shell. Use a bracket pattern (`'[s]imruntime'`) or the script's own report.

**Scheduled run:** a launchd agent runs the full cleanup **daily at 06:00** (30min after the 5:30AM `pmset repeat wakepoweron`; system sleep is disabled so the machine is reliably awake). Plist lives in the repo at `launchd/com.reorx.mac-dev-cleanup.plist`, symlinked to `~/Library/LaunchAgents/`. Log: `~/Library/Logs/mac-dev-cleanup.log` (each run is stamped — the script prints a timestamp header whenever stdout is not a TTY).

```bash
launchctl print gui/$(id -u)/com.reorx.mac-dev-cleanup   # status, run count, calendar trigger
launchctl kickstart -p gui/$(id -u)/com.reorx.mac-dev-cleanup   # force a run now
launchctl bootout gui/$(id -u)/com.reorx.mac-dev-cleanup        # unload
```

It deliberately has **no `RunAtLoad`** — the job kills browsers and simulators, so it must only fire on schedule, never on login or reload.

**Typical scenarios:**
- "Why is my mac hot / loud / slow?" → run `mac-health`; if load or temp is high, run `mac-dev-cleanup --dry-run` **before** investigating anything else — this has been the top cause
- After finishing browser automation or iOS testing → run `mac-dev-cleanup` as the verification teardown step
- Periodic hygiene while other sessions may be working → `mac-dev-cleanup --min-age 2`

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

## macOS Sleep/Wake Schedule

### View, set, or clear the daily wake/sleep schedule

**Script:** `scripts/mac-sleep-schedule.py`

**Prerequisites:** macOS only. Uses `uv run --script` with Python ≥3.11 (no third-party deps). Wraps `pmset repeat` / `pmset -g sched`. Modifying the schedule requires sudo (the script prepends `sudo` itself); viewing status does not.

Thin, opinionated wrapper around `pmset repeat`, which stores exactly one repeating wake-like event and one sleep-like event with a shared day-of-week mask. The script mirrors that contract: set both times together, or clear both.

**How to use:**

```bash
# Show current schedule + relevant power settings (no sudo)
<skill-path>/scripts/mac-sleep-schedule.py

# Set schedule for every day (requires sudo password if not root)
<skill-path>/scripts/mac-sleep-schedule.py --wake 06:00 --sleep 23:00

# Weekdays only
<skill-path>/scripts/mac-sleep-schedule.py --wake 07:30 --sleep 23:30 --days MTWRF

# Remove all repeating wake/sleep events
<skill-path>/scripts/mac-sleep-schedule.py --clear
```

Day codes (pmset): `M`=Mon `T`=Tue `W`=Wed `R`=Thu `F`=Fri `S`=Sat `U`=Sun. Default `MTWRFSU` = every day; `MTWRF` = weekdays; `SU` = weekend.

**Notes:**

- `--wake` and `--sleep` must be given together (pmset stores exactly one of each); to change only one time, pass the current value for the other.
- Status view also prints relevant `pmset -g` settings (sleep, standby, powernap, womp, etc.) for context.
- One-off system wake events (calendar alarms, DND timers) shown under "Scheduled power events" are macOS-managed and not touched by this script.
- Sudo caveat for agents: if sudo cannot prompt for a password in the session, ask the user to run the set/clear command themselves (e.g. via the `!` prefix in Claude Code).

**Typical scenarios:**
- "What's my mac's sleep schedule?" → run with no args
- "Make my mac sleep at 1:30am and wake at 5:30am" → `--wake 05:30 --sleep 01:30`
- "Change the auto-sleep time, keep wake as is" → run with no args first to read the current wake time, then set both
- "Stop the scheduled sleep/wake" → `--clear`

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

## macOS Scheduled Jobs (launchd + cron)

### What actually runs on a schedule, and is it really armed?

**Script:** `scripts/launchd-list.py`

**Prerequisites:** macOS only. Pure stdlib Python ≥3.10 — no `uv`, no third-party deps. Wraps `launchctl list`, `crontab -l`, and `plutil` (fallback for root-owned plists).

`launchctl list` and the plist directories each tell half the story: **a plist can sit on disk without ever being loaded**, and a loaded job can be resident rather than scheduled. This script joins both, classifies every job by cadence, and folds in crontab — where a leading `#` silently disables an entry.

**How to use:**

```bash
launchd-list.py                 # non-Apple jobs, grouped by cadence
launchd-list.py --periodic      # only things that run on a schedule (+ cron)
launchd-list.py --all           # include Apple's own (also scans /System/Library/Launch*)
launchd-list.py --label grafana # filter by label or command substring
launchd-list.py --json          # structured output
launchd-list.py --selftest      # 39 behaviour checks, no side effects
```

**Categories:**

| Category | Meaning |
|----------|---------|
| `PERIODIC` | `StartInterval` or `StartCalendarInterval` — plus every crontab entry |
| `TRIGGERED` | `WatchPaths`, `QueueDirectories`, `StartOnMount` |
| `RESIDENT` | `KeepAlive` (or `RunAtLoad` without it) — a daemon, not a schedule |
| `ON-DEMAND` | socket/XPC activated, or run manually |
| `UNREADABLE` | plist could not be parsed even via `plutil` |

**State column:** `[on ]` loaded, `[off]` plist present but **not** loaded, `[ ? ]` unknown. A running job also shows its `pid`; a job whose last run failed shows `exit N`.

**How to interpret results:**

- **`[off]` is the finding worth chasing.** It means the plist exists — so it looks installed, and `ls ~/Library/LaunchAgents` suggests it is — but launchd has no record of it, so it never fires. The trailing summary lists these explicitly.
- `[ ? ]` is normal for `/Library/LaunchDaemons`: those live in the system domain, which a non-root `launchctl list` cannot see. Re-run under `sudo` to resolve them.
- A schedule beats `KeepAlive` in the classification: a job declaring both is reported as `PERIODIC`, because the schedule is what makes it fire.
- Crontab entries commented out with `#` are still listed, marked `[off]` — they are easy to forget and invisible to `launchctl` entirely.

**Typical scenarios:**
- "What runs periodically on this Mac?" → `launchd-list.py --periodic`
- "I installed a launch agent, why isn't it running?" → `launchd-list.py --label <name>`; if it shows `[off]`, `launchctl bootstrap gui/$(id -u) <plist>` it
- "Is my scheduled cleanup/backup actually armed?" → `launchd-list.py --label cleanup` and check the state marker and schedule
- "Which of my jobs are failing?" → run it and read the "non-zero last exit" summary line
- Auditing a new machine, or diffing before/after an install → `launchd-list.py --json` snapshots

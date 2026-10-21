---
name: systools
description: "System ops toolkit for ports and macOS diagnostics. Use for: inspecting or killing what's on a port (\"what's on 3000\", \"port 8080 is taken\"); macOS health snapshots and live memory pressure — CPU temp, load, memory, swap, pageouts (\"how's my mac\", \"why is my mac slow\"); releasing leaked test resources — booted iOS simulators, agent-browser Chrome, the shared cargo target dir (\"clean up simulators\", \"清理模拟器\", \"清理 cargo 缓存\"); WindowServer CPU/GPU (\"WindowServer is hot\", \"UI feels laggy\"); the daily pmset wake/sleep schedule (\"sleep my mac at 1am\", \"自动休眠计划\"); auditing launchd + cron jobs and Background Task Management items (\"定时任务\", \"why isn't my launch agent running\"); repairing PostgreSQL that won't start under brew services (\"lock file postmaster.pid already exists\", \"数据库起不来\"); and tuning the local monitoring stack's per-process CPU alerts (\"prl_vm_app alert is noisy\", \"调 CPU 告警阈值\"). macOS-only except port management."
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

### Release leaked iOS simulators, agent-browser sessions, and stale cargo artifacts

**Script:** `scripts/mac-dev-cleanup`

**Prerequisites:** macOS only. Uses `uv run --script` with Python ≥3.11 (no third-party deps). Wraps `ps`, `xcrun simctl`, `agent-browser close`, `osascript`, `memory_pressure`, and for the cargo step `cargo` + [`cargo-sweep`](https://github.com/holmgr/cargo-sweep) (`cargo install cargo-sweep`; the step is skipped if either is missing).

The two biggest recurring causes of a degraded `mac-health` reading, and neither cleans up after itself:

- **Booted iOS simulators** — each booted device keeps a full `launchd_sim` tree alive: SpringBoard plus dozens of iOS widget extensions at 200–330 MB each. One booted device measured **~196 processes**.
- **Leaked `agent-browser` sessions** — the CLI spawns a detached daemon (PPID 1) plus a ~10-process headless Chrome tree that survives the session that created it. Observed running for **days**, with renderers pinned at ~100% CPU each, ~5 of 10 cores gone.

Plus one that eats disk instead: **the shared cargo target dir** (`build.target-dir` in `~/.cargo/config.toml`, here `~/Library/Caches/cargo-target`) that every Rust project builds into. It only grows — each dependency version, feature set and toolchain leaves its own artifacts — and reached 24 GB before this step existed.

**How to use:**

```bash
# See what would be cleaned, change nothing (exit 1 = there is work to do)
mac-dev-cleanup --dry-run

# Clean everything
mac-dev-cleanup

# Only one part
mac-dev-cleanup --only sim
mac-dev-cleanup --only browser
mac-dev-cleanup --only cargo

# Safe to run mid-session: spare agent-browser sessions younger than 2h
mac-dev-cleanup --min-age 2

# One-off deeper cargo cleanup: drop what no build used for a week, cap at 15 GiB
mac-dev-cleanup --only cargo --cargo-days 7 --cargo-max-size 15GiB

# Behaviour checks (50 assertions, no side effects)
mac-dev-cleanup --selftest
```

**What it does:**

| Step | Action |
|------|--------|
| agent-browser | Groups Chrome processes into sessions by `--user-data-dir=…/agent-browser-chrome-<uuid>`, links each to its spawning daemon via the root process's PPID, then `agent-browser close --all`, then SIGTERM→SIGKILL any survivor |
| simulators | `xcrun simctl shutdown all`, then quit Simulator.app via AppleScript, falling back to signals when it refuses |
| cargo target | Finds the shared target via `cargo metadata` on a throwaway stub project, takes cargo's build locks, then `cargo sweep --time 21` (artifacts no build touched in 21 days) and `cargo sweep --maxsize 20GiB` (least recently used first) |
| report | Free-memory % and swap before/after (process steps); target size before/after (cargo step) |

**Exit code:** 0 on success. Under `--dry-run`, 1 means there is something to clean — composable as a check like `mac-health`.

**Notes / gotchas:**

- **The user's own Chrome is never touched.** Session membership is decided solely by the `agent-browser-chrome-<uuid>` user-data-dir; a plain `/Applications/Google Chrome.app/…/Google Chrome` has no such flag. This is covered by explicit safety assertions in `--selftest`.
- `ps` truncates the command column to terminal width unless `-ww` is passed, which silently hides processes whose `--user-data-dir` sits past the cutoff — the script always uses `ps -Awwo`. Any ad-hoc `ps | grep` for these processes needs the same flag or it will undercount.
- `agent-browser close --all` is all-or-nothing, so `--min-age` switches to selective signalling instead of calling it.
- `simctl shutdown all` preserves device data; only running-app state is lost, and devices re-boot on demand.
- Simulator.app routinely ignores `quit app "Simulator"`; the signal fallback is the normal path, not an error.
- Counting these processes by hand with `ps -A | grep -c <pattern>` self-matches the grep and the parent shell. Use a bracket pattern (`'[s]imruntime'`) or the script's own report.

**Cargo step: why it doesn't cause rebuild churn, and its traps:**

- "Last used" is the atime of the files in `.fingerprint/<unit>-<hash>/`: cargo reads the hash file there on every build, fresh or not, to decide whether to recompile. So anything a project still builds keeps a fresh atime and survives; only units that no project has touched in N days go. The price is that a project left alone for 3+ weeks rebuilds its dependencies once.
- **`cargo sweep --installed` / `--toolchains` poison that signal** — they read every fingerprint `.json` (even with `--dry-run`), stamping the whole target "used today", after which `--time` finds nothing for weeks. The script only uses `--time` / `--maxsize` (stat-only), and before each sweep resets any fingerprint `.json` whose atime is newer than its mtime back to its mtime. Cargo itself reads the `.json` only right before rewriting it, so this loses nothing. Old-toolchain artifacts need no `--installed`: after a `rustup update` nobody uses them, and `--time` collects them.
- cargo-sweep takes only a project path and resolves the target via `cargo metadata`; pointing it at the target dir itself fails. The stub project in a temp dir keeps the job independent of any real project.
- If a build holds any of `.cargo-lock` / `.cargo-build-lock` / `.cargo-artifact-lock` (all flock(2)), the step skips the run. While sweeping it holds them itself, so a build that starts meanwhile prints `Blocking waiting for file lock on build directory` and waits (both verified against cargo 1.98).
- **Size units:** cargo-sweep reads `GB` as 10⁹ and sums apparent file sizes, counting the hardlinks between `incremental/` and `deps/` twice, so its total runs ~5% above `du`. Pass `GiB`.
- `~/.cargo/registry` needs none of this: cargo ≥1.88 garbage-collects it on its own.

**Scheduled run:** a launchd agent runs the full cleanup **daily at 06:00** (30min after the 5:30AM `pmset repeat wakepoweron`; system sleep is disabled so the machine is reliably awake). Plist lives in the repo at `launchd/com.reorx.mac-dev-cleanup.plist`, symlinked to `~/Library/LaunchAgents/`. Log: `~/Library/Logs/mac-dev-cleanup.log` (each run is stamped — the script prints a timestamp header whenever stdout is not a TTY).

```bash
launchctl print gui/$(id -u)/com.reorx.mac-dev-cleanup   # status, run count, calendar trigger
launchctl kickstart -p gui/$(id -u)/com.reorx.mac-dev-cleanup   # force a run now
launchctl bootout gui/$(id -u)/com.reorx.mac-dev-cleanup        # unload
```

It deliberately has **no `RunAtLoad`** — the job kills browsers and simulators, so it must only fire on schedule, never on login or reload. For the same reason, don't `kickstart` it just to test the cargo step; run `mac-dev-cleanup --only cargo` instead. The plist's `PATH` includes `~/.cargo/bin` for that step; after editing the plist, `bootout` + `bootstrap` it, because launchd reads it only at load.

**Typical scenarios:**
- "Why is my mac hot / loud / slow?" → run `mac-health`; if load or temp is high, run `mac-dev-cleanup --dry-run` **before** investigating anything else — this has been the top cause
- After finishing browser automation or iOS testing → run `mac-dev-cleanup` as the verification teardown step
- Periodic hygiene while other sessions may be working → `mac-dev-cleanup --min-age 2`
- "The cargo target / Rust cache is huge" → `mac-dev-cleanup --only cargo --dry-run`, then run it; lower `--cargo-days` or `--cargo-max-size` for a one-off deeper cut

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

`launchctl list` and the plist directories each tell half the story: **a plist can sit on disk without ever being loaded**, and a loaded job can be resident rather than scheduled. This script joins both, classifies every job by cadence, and folds in crontab — where a leading `#` silently disables an entry. It also says **who owns each plist** (the `↳` line), since the jobs on this machine are installed four different ways and nothing else records which repo a plist came from.

**How to use:**

```bash
launchd-list.py                 # non-Apple jobs, grouped by cadence
launchd-list.py --periodic      # only things that run on a schedule (+ cron)
launchd-list.py --all           # include Apple's own (also scans /System/Library/Launch*)
launchd-list.py --label grafana # filter by label, command or origin substring
launchd-list.py --label macos-monitoring  # everything installed from one repo
launchd-list.py --json          # structured output (`source` = plist dir, `origin` = owner)
launchd-list.py --selftest      # 62 behaviour checks, no side effects
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

**Origin (`↳` line), first rule that matches wins:**

| Origin | Meaning |
|--------|---------|
| `link → <path>` | The plist is a symlink; edit the target. `(broken)` = it points at nothing |
| `copy of <repo path>` | A plist with the same filename exists in a repo's `launchd/` dir (`~/Code/*/launchd`, `~/Code/*/skills/*/launchd`, `~/Documents/*/launchd` — one glob level, no deep walk into iCloud). `(differs)` = the installed copy has drifted; re-run that repo's installer |
| `brew services: <formula>` | `homebrew.mxcl.*` / `sh.brew.*`, managed by `brew services` |
| `app: <Name>.app` | The program lives inside that app bundle (outermost bundle wins) |
| `local file, program in ~/Code/<repo>` | A plain file, most likely written by the tool's own `install` command; the repo comes from the program path, its symlink target, or `WorkingDirectory` |
| `local file` | Nothing above matched — hand-placed or third-party |

Crontab rows need no origin line; Apple's `/System` jobs (under `--all`) get none either.

**How to interpret results:**

- **`[off]` is the finding worth chasing.** It means the plist exists — so it looks installed, and `ls ~/Library/LaunchAgents` suggests it is — but launchd has no record of it, so it never fires. The trailing summary lists these explicitly.
- `[ ? ]` is normal for `/Library/LaunchDaemons`: those live in the system domain, which a non-root `launchctl list` cannot see. Re-run under `sudo` to resolve them.
- A schedule beats `KeepAlive` in the classification: a job declaring both is reported as `PERIODIC`, because the schedule is what makes it fire.
- Crontab entries commented out with `#` are still listed, marked `[off]` — they are easy to forget and invisible to `launchctl` entirely.
- **A `copy of … (differs)` origin is the other finding worth chasing**: the repo was edited but never reinstalled, so the running job still uses the old plist. The trailing summary lists these, and any broken symlinks, explicitly.

**Typical scenarios:**
- "What runs periodically on this Mac?" → `launchd-list.py --periodic`
- "I installed a launch agent, why isn't it running?" → `launchd-list.py --label <name>`; if it shows `[off]`, `launchctl bootstrap gui/$(id -u) <plist>` it
- "Is my scheduled cleanup/backup actually armed?" → `launchd-list.py --label cleanup` and check the state marker and schedule
- "Which of my jobs are failing?" → run it and read the "non-zero last exit" summary line
- Auditing a new machine, or diffing before/after an install → `launchd-list.py --json` snapshots
- "Where does this job's plist come from / which file do I edit?" → `launchd-list.py --label <name>` and read the `↳` line

## PostgreSQL Service Recovery

### `brew services` shows postgresql as `error`

**Script:** `scripts/pg-doctor`

**Prerequisites:** macOS + Homebrew. Uses `uv run --script` with Python ≥3.11 (no third-party deps). Wraps `ps`, `brew services list --json`, `plutil`-free `plistlib`, `pg_isready`.

The failure this exists for, in order:

1. An unclean shutdown (power loss, forced reboot, panic) kills the postmaster before it can remove `postmaster.pid` from the data directory.
2. On the next boot the PID recorded in that file gets **recycled by an unrelated system process** — low PIDs go to Apple daemons early in boot.
3. PostgreSQL's stale-lock detection does `kill(pid, 0)`, sees a live process, and concludes another postmaster owns the directory:
   ```
   FATAL:  lock file "postmaster.pid" already exists
   HINT:  Is another postmaster (PID 589) running in data directory "..."?
   ```
4. Homebrew's plist has `KeepAlive=true`, so launchd retries **every 10 seconds, forever**. `brew services list` shows `error 1`, the log grows by megabytes, and the database is simply down until someone notices.

Normally PostgreSQL cleans up a stale lock by itself — that only works when the recorded PID no longer exists. PID reuse is what defeats it, which is why this needs a tool rather than a retry.

**How to use:**

```bash
# Diagnose every brew-managed instance (read-only; exit 1 = something is wrong)
pg-doctor

# Repair: clear the stale lock, restart the service, wait for it to accept connections
pg-doctor --fix

# Narrow to one formula, or check a data directory brew knows nothing about
pg-doctor --name postgresql@18 --fix
pg-doctor --datadir /path/to/pgdata

# Behaviour checks (45 assertions, no side effects)
pg-doctor --selftest
```

**Verdicts:**

| Verdict | Meaning | `--fix` acts? |
|---------|---------|---------------|
| `healthy` | The PID in the lock file is a live postmaster for this data directory | no |
| `no-lock` | No `postmaster.pid` — normal for a stopped instance | no |
| `stale-reused` | The PID is alive but belongs to an unrelated process (**the classic case**) | yes |
| `stale-dead` | The PID no longer exists at all | yes |
| `corrupt` | `postmaster.pid` has no readable PID on line 1 | yes |
| `ambiguous` | The PID is a postgres, but serving a *different* data directory | no — resolve by hand |

**Safety.** Two postmasters on one data directory corrupt it, so the tool never deletes a lock file on a guess:

- Anything that is or *might* be a postmaster for that directory is classified non-fixable.
- Before deleting, `--fix` re-scans `ps` for a live postmaster serving that exact `-D` path and aborts if one appeared since the diagnosis.
- The removed file is backed up (`/tmp/postmaster.pid.<instance>.<timestamp>` by default, `--backup-dir` to change).
- `--selftest` asserts `healthy` and `ambiguous` are not in the fixable set; `test-pg-doctor.sh` in the scripts repo root additionally builds synthetic data directories for every verdict and runs `--fix` against the *live* data directory, asserting the lock file's inode/mtime/size are unchanged.

**Notes / gotchas:**

- After the repair PostgreSQL runs crash recovery (`database system was not properly shut down; automatic recovery in progress`) before accepting connections — `--fix` polls `pg_isready` for up to 40s. Committed data is not lost; the WAL is replayed.
- The stale-lock FATALs stay in the log after the fix. `pg-doctor` only flags them as urgent while the instance is still broken; on a healthy instance it reports them as history.
- When an instance is broken for some *other* reason, the lock file explains nothing — the report then prints the last real `FATAL`/`PANIC` lines from the log instead (disk full, bad WAL, failed config reload).
- `brew services list --json` is the source of truth for which formulae exist; the data directory comes from `-D` in the launchd plist, not from a guess about `/opt/homebrew/var/<name>`.
- This has recurred at least twice on this machine (2026-05-13, 2026-07-27) — after any hard reboot, `pg-doctor` is worth a run before debugging an app that "can't connect to the database".

**Typical scenarios:**
- `brew services list` shows postgresql as `error` → `pg-doctor`, then `pg-doctor --fix`
- An app suddenly cannot reach postgres on 5432 after a reboot → `pg-doctor`
- The postgres log is exploding in size → `pg-doctor` reports the FATAL count and log size directly
- Checking a non-brew or second cluster → `pg-doctor --datadir <path>`

## Local Monitoring: Process CPU Alerts

### Tune a noisy or missing per-process CPU alert

**Reference:** `references/process-alert-policies.md`

The user's self-hosted monitoring stack (Telegraf + proc-top → VictoriaMetrics → Grafana → Telegram, with Hermes AI triage) lives in `~/Documents/macos-monitoring`. Per-process CPU thresholds come from its `process-rules.yaml` through a generator. Before changing a rule, read the reference: it lists the project documents that hold the mechanics and current values, and the order of work.

- Read process CPU in its units and context before calling it runaway: 100% is one core, so a VM or compiler can legitimately use several. Check the executable's identity and what the user is doing; don't turn one expected workload into a permanent exemption.
- Change the policy only through the project's policy file and generator — no hardcoded exceptions, no AI-only suppression. Host-wide alerts, existing pauses and the AI triage budgets stay as they are.
- A remembered threshold is not proof of what is deployed; read the current configuration and the live rules first.
- Report local tests, historical replay, deployed configuration and real notification delivery as separate acceptance levels.

**Typical scenarios:**
- "The prl_vm_app CPU alert keeps firing while my VM is busy" → confirm the process and workload, then follow the reference
- "Add a CPU threshold for <process>" → add an exact-name entry to `process-rules.yaml`, preview, replay, deploy after approval

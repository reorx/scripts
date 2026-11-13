---
name: systools
description: "System ops toolkit for ports and macOS diagnostics. Use for: inspecting or killing what's on a port (\"what's on 3000\", \"port 8080 is taken\"); macOS health snapshots and live memory pressure — CPU temp, load, memory, swap, pageouts (\"how's my mac\", \"why is my mac slow\"); releasing leaked test resources — booted iOS simulators, agent-browser Chrome, the shared cargo target dir, the uv / go / pnpm / npm caches, expired codex sessions, browser code-sign clones under /var/folders (\"clean up simulators\", \"清理模拟器\", \"清理 cargo 缓存\", \"清理 uv 缓存\", \"清理 pnpm/npm/go 缓存\", \"codex 会话太大\", \"~/.cache/uv is huge\", \"/var/folders is huge\", \"code_sign_clone\"); per-project cleanup rules, archiving to the LaCie drive and disk monitoring with dev-space (\"磁盘满了\", \"项目目录太大\", \"归档到 LaCie\", \"dev-space\"), and the 23:00 job that closes Hearthstone/Battle.net (\"关掉游戏\", \"炉石没关\"); WindowServer CPU/GPU (\"WindowServer is hot\", \"UI feels laggy\"); keeping the Mac awake up to 24h (\"keep my mac awake\", \"防止休眠\"); the daily pmset wake/sleep schedule (\"sleep my mac at 1am\", \"自动休眠计划\"); auditing launchd + cron jobs and Background Task Management items (\"定时任务\", \"why isn't my launch agent running\"); repairing PostgreSQL that won't start under brew services (\"lock file postmaster.pid already exists\", \"数据库起不来\"); and tuning the local monitoring stack's per-process CPU alerts (\"prl_vm_app alert is noisy\", \"调 CPU 告警阈值\"). macOS-only except port management."
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

### Release leaked iOS simulators, agent-browser sessions, unused dev cache entries (cargo, uv, go, pnpm, npm), expired codex sessions and orphaned browser code-sign clones

**Script:** `scripts/mac-dev-cleanup`

**Prerequisites:** macOS only. Uses `uv run --script` with Python ≥3.11 (no third-party deps). Wraps `ps`, `xcrun simctl`, `agent-browser close`, `osascript`, `memory_pressure`, for the cargo step `cargo` + [`cargo-sweep`](https://github.com/holmgr/cargo-sweep) (`cargo install cargo-sweep`; the step is skipped if either is missing), for the uv step `uv` + `lsof`, for the go / pnpm / npm steps the tool itself (each is skipped if missing), for the codex step `codex` (deletion) + `zstd` (compression) + `lsof`, and for the clones step `getconf`. The `projects` and `watch` steps run `dev-space`, which must sit next to this script (see the dev-space section).

The two biggest recurring causes of a degraded `mac-health` reading, and neither cleans up after itself:

- **Booted iOS simulators** — each booted device keeps a full `launchd_sim` tree alive: SpringBoard plus dozens of iOS widget extensions at 200–330 MB each. One booted device measured **~196 processes**.
- **Leaked `agent-browser` sessions** — the CLI spawns a detached daemon (PPID 1) plus a ~10-process headless Chrome tree that survives the session that created it. Observed running for **days**, with renderers pinned at ~100% CPU each, ~5 of 10 cores gone.

Plus two that eat disk instead: **the shared cargo target dir** (`build.target-dir` in `~/.cargo/config.toml`, here `~/Library/Caches/cargo-target`) that every Rust project builds into. It only grows — each dependency version, feature set and toolchain leaves its own artifacts — and reached 24 GB before this step existed. And **the uv cache** (`~/.cache/uv`), which keeps every wheel uv ever downloaded and every environment `uv run --script` / `uv run --with` / `uvx` ever built. It showed 13 GB on 2026-10-27; the first run took `du` to 5.6 GB but freed only 3.3 GB of real disk, because the rest was shared with installed venvs (see the uv notes below). And **browser code-sign clones** under `/var/folders/…/X/`: every Chrome that is killed rather than quit leaves a copy of its app bundle there. 35 of them, mostly from agent-browser sessions, made `/private/var/folders` show 81 GB on 2026-10-27, though they held only 0.7 GiB of real disk (see the clones notes below).

Since 2026-11-13 (data volume at 99%, 7 GiB free), four more caches and the agents' sessions: **the go module cache** (`~/go/pkg/mod`, 7.3 GiB: every module version any build ever downloaded, extracted read-only, plus every toolchain `GOTOOLCHAIN=auto` fetched), **pnpm** (store 13 GiB plus `~/Library/Caches/pnpm` 4.8 GiB, of which `dlx` 3.5 GiB never shrinks: pnpm keeps every `pnpm dlx` run), **npm** (`~/.npm`, 3.4 GiB: `_cacache` and `_npx`, one dir per `npx` package, never removed) and **codex sessions** (`~/.codex`, 5.6 GiB of rollouts). Each step keeps what an *active project* references (a dir under `~/Code` committed to, or whose lock/manifest changed, within 30 days) plus anything used in the last 7 days, and reports `du` next to **real**: the bytes no surviving file shares (`getattrlist` `ATTR_CMNEXT_CLONE_REFCNT` / `PRIVATESIZE`), since uv and pnpm files are APFS clones of the projects' copies. And two hand-offs to `dev-space`: `projects` (per-project rules, before the cache steps, so `node_modules` / `.venv` it removes stop pinning cache entries) and `watch` (the disk monitor, last).

And one opt-in step that is **never part of the default run**: `--only games` closes Hearthstone and Battle.net in the evening. Left open, Hearthstone keeps the display awake for hours (it holds a display-sleep assertion *and* injects input events, so the system thinks someone is at the keyboard), and Battle.net's helpers keep competing for CPU with agents during the night's dark wakes.

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
mac-dev-cleanup --only uv
mac-dev-cleanup --only go
mac-dev-cleanup --only pnpm
mac-dev-cleanup --only npm
mac-dev-cleanup --only codex
mac-dev-cleanup --only clones
mac-dev-cleanup --only projects    # = dev-space clean --scheduled
mac-dev-cleanup --only watch       # = dev-space watch --agent (--dry-run: --no-record --no-notify)

# Safe to run mid-session: spare agent-browser sessions younger than 2h
mac-dev-cleanup --min-age 2

# One-off deeper cargo cleanup: drop what no build used for 3 days, cap at 15 GiB
mac-dev-cleanup --only cargo --cargo-days 3 --cargo-max-size 15GiB

# Every cache step takes its own age (default 7 days); codex has two
mac-dev-cleanup --only uv --uv-days 3
mac-dev-cleanup --only codex --codex-compress-days 3 --codex-delete-days 14

# Close games and their launchers (only ever runs when asked for explicitly)
mac-dev-cleanup --only games --dry-run
mac-dev-cleanup --only games

# Behaviour checks (~195 assertions, no side effects)
mac-dev-cleanup --selftest
```

**What it does:**

| Step | Action |
|------|--------|
| agent-browser | Groups Chrome processes into sessions by `--user-data-dir=…/agent-browser-chrome-<uuid>`, links each to its spawning daemon via the root process's PPID, then `agent-browser close --all`, then SIGTERM→SIGKILL any survivor |
| simulators | `xcrun simctl shutdown all`, then quit Simulator.app via AppleScript, falling back to signals when it refuses |
| projects | `dev-space clean --scheduled` (`-n` under `--dry-run`): every project's daily rules, plus the pressure tier when free space is low. dev-space exit 2 fails the step |
| cargo target | Finds the shared target via `cargo metadata` on a throwaway stub project, takes cargo's build locks, stamps every fingerprint unit's files with its **real last use** (see the cargo notes), then `cargo sweep --time 7` and `cargo sweep --maxsize 20GiB` (least recently used first). Afterwards re-arms the survivors and records their last use in `~/.local/state/mac-dev-cleanup/cargo-lastuse.json`; a dry run puts the atimes back |
| uv cache | Skips unless the `uv` binary contains every cache bucket name the script knows, and skips the day if a uv that holds the cache lock started < 10min ago. Then deletes: top-level entries that are not a current bucket and archives nothing links to, both if created > 1 day ago; downloaded wheels and cached environments created > `--uv-days` (7) ago, **except** wheels an active project's `uv.lock` / `pylock.toml` / `.venv` pins and, for 30 days, the env of a PEP 723 script that still exists under `~/Code`; `simple-v18` index metadata older than 7 days. Never touches wheels built from source, or anything a running process's command line points into |
| go | `go env -json`; skips the day if a `go build/test/run/get/mod/…` started < 10min ago. Collects what active projects' `go.sum` (lines without `/go.mod`) and `go`/`toolchain` lines need, then per module version unreferenced and extracted > `--go-days` (7) ago: renames the extracted tree to a trash dir under a non-blocking flock of its `<ver>.lock` (busy → skipped), and drops its `.zip`/`.ziphash`; the small `.mod`/`.info` stay for graph resolution. Keeps the newest toolchain. Warns if `GOCACHE/trim.txt` is > 3 days old (go trims its build cache itself) |
| pnpm | Skips unless `pnpm store path` ends in `/v10`, and the day if a store-writing pnpm (`install`/`add`/`dlx`/bare `pnpm`…; not `exec`/`run`) started < 10min ago. Store: an index json is kept if any `node_modules/.pnpm` under `~/Code`, the global dir or a kept dlx run names its package, or it is < 7 days old; files no kept index (or its `sideEffects`) points to and > 7 days old go. `dlx`: a command whose `pkg` link is > 7 days old goes whole, superseded runs of the others go. Metadata files > 7 days old go |
| npm | `_cacache`: a key expires 7 days after its last index line; content no live key points to (and > 1 day old) goes, buckets are dropped or rewritten to their live lines (skipped if changed meanwhile). `_npx` (npm ≥ 11 only): dirs untouched for 7 days and not running, each taken under its own `concurrency.lock` before removal. Skips the day if an `npm install/ci/update/…` started < 10min ago. `npm run`/`start`/`test` don't count, nor `npx`/`npm exec` (every agent session starts its MCP servers that way): their `_npx` dir's lock and the 1-day grace already cover them |
| codex | Reads `state_5.sqlite` read-only (skips the step on any other layout). A session's last use = newest of `threads.updated_at`, the rollout's mtime, its last `history.jsonl` entry, over its whole spawn family. Unused > 7 days: rollout replaced by `.jsonl.zst` with codex's own publication protocol. Unused > 30 days and not pinned: `codex delete --force <uuid>` (≤ 200 per run, ≤ 10 min). Skips rollouts open in a process (`lsof`) or whose writer lock is held. Also drops standalone releases neither `current` nor any process runs from |
| watch | `dev-space watch --agent`: measure, record history, notify, dispatch proposal agents. Runs last |
| clones | Lists `X/*.code_sign_clone/code_sign_clone.*` next to the user temp dir, reads each clone's `CFBundleExecutable`, then keeps every clone made within 30s before / 300s after a running browser of that app started (matched by executable, `--type=` helpers excluded) and every clone whose app it can't read. The rest are renamed into a trash dir and deleted |
| games (`--only games`) | Matches Hearthstone (+ its BlizzardBrowser), Battle.net (+ its Helpers) and the Blizzard update Agent by executable path, asks the apps to quit via AppleScript by bundle id, waits 20s, then SIGTERM→SIGKILL whatever is left |
| report | Free-memory % and swap before/after (process steps); target size before/after (cargo step); per kind of entry, its count, `du` and real size, then the volume's real free-space gain (uv, go, pnpm, npm, codex); clones removed, their `du` size and the volume's real free-space gain (clones step) |

**Exit code:** 0 on success, 2 if a step crashed (the remaining steps still run). Under `--dry-run`, 1 means there is something to clean — composable as a check like `mac-health`.

**Notes / gotchas:**

- **The user's own Chrome is never touched.** Session membership is decided solely by the `agent-browser-chrome-<uuid>` user-data-dir; a plain `/Applications/Google Chrome.app/…/Google Chrome` has no such flag. This is covered by explicit safety assertions in `--selftest`.
- `ps` truncates the command column to terminal width unless `-ww` is passed, which silently hides processes whose `--user-data-dir` sits past the cutoff — the script always uses `ps -Awwo`. Any ad-hoc `ps | grep` for these processes needs the same flag or it will undercount.
- `agent-browser close --all` is all-or-nothing, so `--min-age` switches to selective signalling instead of calling it.
- `simctl shutdown all` preserves device data; only running-app state is lost, and devices re-boot on demand.
- Simulator.app routinely ignores `quit app "Simulator"`; the signal fallback is the normal path, not an error.
- Counting these processes by hand with `ps -A | grep -c <pattern>` self-matches the grep and the parent shell. Use a bracket pattern (`'[s]imruntime'`) or the script's own report.
- Each step runs isolated: on 2026-10-23 `xcrun simctl list` hung for 60s right after the 05:30 wake (0.2s when retried later), and the traceback used to take the cargo step down with it. Now the step is reported as failed, the rest still run, and the exit code is 2.
- **Games step:** Battle.net's Helper processes run from `~/Library/Application Support/Battle.net/Versions/…/battle.net-core.framework`, *not* from inside `Battle.net.app` — match on both. Quit by bundle id (`net.battle.app`, `unity.Blizzard Entertainment.Hearthstone`): Launch Services does not resolve the name "Battle.net" (`open -a Battle.net` fails). The AppleScript is guarded with `is running` (a bare `tell application` would *launch* the app) and wrapped in `ignoring application responses` (a quit confirmation dialog would otherwise hang osascript). The Blizzard Agent has no app to quit and always takes the signal path after the 20s grace. Steam is deliberately not on the list; add a `Game(...)` entry to `GAMES` to extend it.

**Cargo step: why it doesn't cause rebuild churn, and its traps:**

- cargo-sweep's "last used" is the newest atime among the files in `.fingerprint/<unit>-<hash>/`: cargo reads the hash file, dep-info and `invoked.timestamp` there on every build, fresh or not. **But this Mac updates atime on a read only while atime < mtime** (measured 2026-10-27 and again 2026-11-13; no 24h rule, ctime irrelevant): after the first build following a rebuild, reads leave atime alone, so it said "first build after the last rebuild" and daily-used dependencies were swept and rebuilt every 21 days.
- **Re-arming fixes it.** After each real sweep the script sets every surviving unit's file atimes to 1s *before* their mtime (mtime untouched: cargo's freshness check uses it), so the next build's read moves atime to now. Re-arming erases the last use, so each unit's is recorded in `~/.local/state/mac-dev-cleanup/cargo-lastuse.json`. Next run, a unit's real last use = the newest of: the recorded one, and the atime of any non-`.json` file no longer armed (read or rewritten since). A unit with neither (all files armed, no record) falls back to its newest mtime. Spotlight did not read re-armed files in `~/Library/Caches` within 180s of watching. Verified with a real fresh build of a test crate after re-arming.
- **`cargo sweep --installed` / `--toolchains` read every fingerprint `.json`** (even with `--dry-run`). The real-last-use computation ignores `.json` files, and the stamping overwrites their atime before each sweep, so this no longer poisons anything; the script still uses only `--time` / `--maxsize`. Old-toolchain artifacts need no `--installed`: after a `rustup update` nobody uses them, and `--time` collects them.
- cargo-sweep takes only a project path and resolves the target via `cargo metadata`; pointing it at the target dir itself fails. The stub project in a temp dir keeps the job independent of any real project.
- If a build holds any of `.cargo-lock` / `.cargo-build-lock` / `.cargo-artifact-lock` (all flock(2)), the step skips the run. While sweeping it holds them itself, so a build that starts meanwhile prints `Blocking waiting for file lock on build directory` and waits (both verified against cargo 1.98).
- **Size units:** cargo-sweep reads `GB` as 10⁹ and sums apparent file sizes, counting the hardlinks between `incremental/` and `deps/` twice, so its total runs ~5% above `du`. Pass `GiB`.
- `~/.cargo/registry` needs none of this: cargo ≥1.88 garbage-collects it on its own.

**uv step: why not `uv cache prune`, and its traps** (all verified against uv 0.9.17 source and this cache):

- **`uv cache prune` cannot run unattended here.** Every `uv` process holds a shared flock on `~/.cache/uv/.lock` for its whole life, and the resident `uv run` jobs (proc-top, condenser-probe) live for weeks, so prune waits forever for its exclusive lock. With `--force` it goes ahead, and its step two **deletes every cached environment unconditionally**, including `environments-v2/proc-top-*`, which the monitoring job is running from. The step does the same garbage collection by hand and skips entries in use.
- **Cache layout** (0.9.17): downloads are unpacked into `archive-v0/<id>/`. The only references prune counts are symlinks: `wheels-v5/<index>/<pkg>/<ver>-<tag>` (downloaded wheels) and `sdists-v9/…` (wheels built from source). `environments-v2/` holds two kinds of entry: `<script>-<hash>/` real venvs from `uv run --script`, and `<interpreter-hash>/<hash>` symlinks into `archive-v0` for `uv run --with` / `uvx` environments. The step counts all three link sources, plus any archive id named inside a `.http`/`.rev` pointer file, before calling an archive unreferenced.
- **Deleting a wheel's archive is safe.** The step removes the archive and its symlink but keeps the `.http` pointer: uv reads it, sees the archive is missing (`CachedWheel::from_http_pointer`: "Ignore stale pointers"), and downloads again. Verified by deleting the archive of `requests==2.32.3` and installing it again.
- **Age is creation time, references override it.** uv keeps no last-use time, and atime doesn't help either: this Mac updates atime on a read only while atime < mtime (`cat`/Python read of a file whose atime is already past its mtime leaves it unchanged; proc-top's `pyvenv.cfg`, read at every start, still shows its June birth atime). So the step keeps, at any age, the wheels whose (name, version) an active project's `uv.lock` / `pylock*.toml` or installed `.venv` (`*.dist-info`) pins, and for 30 days the env whose `pyvenv.cfg` `prompt` names a PEP 723 script that exists under `~/Code`. Everything else past 7 days goes: a wheel is re-downloaded and an environment rebuilt from the archives, both in seconds. Wheels built from source never age out: rebuilding needs a toolchain and can take minutes.
- **`du` overstates the cache.** uv installs by APFS clone (`link-mode` default on macOS), so a cached file and every installed copy share blocks. `du` counts each in full, but deleting the cache copy frees nothing while a venv still holds the blocks. On 2026-10-27, `du` showed archive-v0 at 10.1 GiB, but only 2.55 GiB of it was not shared with a clone (`getattrlist` `ATTR_CMNEXT_PRIVATESIZE`). The step therefore reports the volume's real free-space gain next to `du`. To free the rest, delete venvs you no longer use.
- **In use** = some process's command line contains the entry's path. `uv run` execs `<env>/bin/python3` by full path, so that covers resident jobs and this script's own environment. Entries are renamed into a trash dir before deletion, so a uv that looks at the same moment sees each one whole or not at all.
- **Layout guard:** uv bumps a bucket's version whenever its format changes (e.g. `wheels-v6` / `simple-v21` from a newer uv). The step reads the uv binary and requires all the names in `UV_BUCKETS` as literal bytes. If any is missing, it logs a `⚠️` and skips: check `CacheBucket::to_str` in `crates/uv-cache/src/lib.rs` for the new version and update the constants and this note.

**go / pnpm / npm steps: why not the tools' own commands, and their traps** (verified 2026-11-13 against go 1.25.7, pnpm 10.15.0, npm 11.20.0):

- **`go clean -modcache` is all or nothing**, and every inactive project would re-download everything. go guards a version's download and extraction with `flock(cache/download/<mod>/@v/<ver>.lock)` but reads extracted sources without any lock, which is why referenced versions are never touched. The module cache is all `0555`; the step `chmod`s a tree's top dir to move it and the trash before deleting. `~/Code/go` is an abandoned GOPATH and is not indexed. Module paths in the cache are case-escaped (`!`+lower); `go.sum` keys are escaped the same way before matching.
- **`pnpm store prune` would empty this store.** It deletes every store file with `nlink == 1`, assuming installs hard-link; on APFS pnpm installs by `clonefile`, so every file here has `nlink` 1. It also wipes all metadata and takes no lock. Index file names and `.pnpm/` dir names both spell scoped packages `@scope+name`. Index jsons go before files, so an interrupted run leaves only orphans, which the next run finds.
- **npm keeps no last-access time.** A `_cacache` key's last index line (its `time`) is when it was last *written*; a package npm reads from cache daily but never re-fetches expires after 7 days and is downloaded once more. `npm cache clean` is all or nothing, and `npm cache verify` only drops unreachable content.
- **`du` vs real:** pnpm `dlx` runs and store files are clones of each other and of projects' `node_modules`; the step reports both. go and npm files are not cloned, so their `du` is real.

**codex step: how sessions are stored, and its traps** (verified 2026-11-13 against codex 0.167.1 source and `~/.codex`):

- `codex resume` and the app list sessions from `state_5.sqlite` `threads` (`rollout_path` → `sessions/YYYY/MM/DD/rollout-*.jsonl`). Deleting a rollout by hand leaves a row that can't be opened, so deletion goes through `codex delete --force <uuid>` (removes rollout, state rows and name index; without `--force` it refuses when there's no terminal). It refuses threads with attached children or external references; refusals are printed and the session stays.
- **Compressed rollouts are read transparently** whatever codex's compression feature flag says (`open_rollout_line_reader` checks for `<path>.zst`; the flag only gates codex's own background worker). The step publishes like codex does: encode to `rollout-compress-*.jsonl.zst.tmp` beside the source, verify by sha256 of the decompressed stream, then under `thread-writer-locks/.coordination.lock` and with the thread's own lock free and the source unchanged, link the `.zst` in place and remove the `.jsonl`. mtime is kept, so the age signal survives. Rollouts hold base64 images: `zstd -3` saved only 46% on a sample; the dry run measures the exact compressed size.
- **A state db named anything but `state_5.sqlite`** (a codex migration) or a `threads` table missing a column skips the step with `⚠️`. Check the new schema in codex's `state` crate before updating `CODEX_STATE_DB` / `CODEX_THREAD_COLUMNS`.
- Releases: codex prunes old standalone releases only for its daemon; TUI processes keep running from the version they started with, which the step detects from `ps` and keeps.

**Clones step: what the clones are, and its traps** (verified 2026-10-27 against Chrome 156 and SunBrowser 152):

- At launch, Chromium browsers copy their app bundle to `<DARWIN_USER_TEMP_DIR>/../X/<bundle id>.code_sign_clone/code_sign_clone.XXXXXX/<App>.app.bundle`, so that an update replacing the app on disk can't break the running browser's code signature. The kernel records the clone as the process's executable path (`codesign -dv <pid>` prints it), so deleting a running browser's clone would break keychain/TCC checks of that browser. A browser that quits normally deletes its own clone (observed when an agent-browser Chrome closed); `kill -9` leaves it behind (reproduced with a throwaway `--headless` Chrome).
- **`du` overstates them by orders of magnitude.** The main executable is a hard link and everything else an APFS clone, so every clone shares blocks with the installed app and with the other clones of its version. On 2026-10-27, 37 clones were 78 GiB by `du` but 4.2 GiB of physical extents together with the app itself (`fcntl(F_LOG2PHYS_EXT)`). A clone costs real disk only once the app updates and it is left holding the old version, ~0.7 GiB per Chrome version however many clones share it. Deleting a clone of the current version frees almost nothing; the step reports the volume's real gain.
- **Which browser owns a clone can't come from `lsof` or `codesign -dv <pid>`:** every clone of one version hard-links the same executable inode, so both name an arbitrary sibling. Launch time does: the clone's birth time is 0–1s after the browser's start in every case seen. The window is 30s before to 300s after, erring towards keeping.
- The step runs after the agent-browser step, so it also takes the clones of sessions that step had to SIGKILL. Clones are renamed into a trash dir before deletion, so a browser deleting its own clone at the same moment can't make the step fail. Trash a crashed run left behind is deleted after an hour.

**Scheduled run:** a launchd agent runs the full cleanup **daily at 06:00** (30min after the 5:30AM `pmset repeat wakepoweron`; system sleep is disabled so the machine is reliably awake). Plist lives in the repo at `launchd/com.reorx.mac-dev-cleanup.plist`, symlinked to `~/Library/LaunchAgents/`. Log: `~/Library/Logs/mac-dev-cleanup.log` (each run is stamped — the script prints a timestamp header whenever stdout is not a TTY).

```bash
launchctl print gui/$(id -u)/com.reorx.mac-dev-cleanup   # status, run count, calendar trigger
launchctl kickstart -p gui/$(id -u)/com.reorx.mac-dev-cleanup   # force a run now
launchctl bootout gui/$(id -u)/com.reorx.mac-dev-cleanup        # unload
```

It deliberately has **no `RunAtLoad`** — the job kills browsers and simulators, so it must only fire on schedule, never on login or reload. For the same reason, don't `kickstart` it just to test the cargo step; run `mac-dev-cleanup --only cargo` instead. The plist's `PATH` includes `~/.cargo/bin` for that step; after editing the plist, `bootout` + `bootstrap` it, because launchd reads it only at load.

A second agent, `com.reorx.mac-dev-cleanup-games` (`launchd/com.reorx.mac-dev-cleanup-games.plist`, also symlinked), runs `mac-dev-cleanup --only games` **daily at 23:00**, ahead of the 01:30 scheduled sleep, and logs to the same file. It is a separate job because a plist has only one `ProgramArguments`, and games must stay out of the 06:00 default run. Same rules apply: no `RunAtLoad`, and `kickstart` it only when no game is running or when you mean to close them.

**Typical scenarios:**
- "Why is my mac hot / loud / slow?" → run `mac-health`; if load or temp is high, run `mac-dev-cleanup --dry-run` **before** investigating anything else — this has been the top cause
- After finishing browser automation or iOS testing → run `mac-dev-cleanup` as the verification teardown step
- Periodic hygiene while other sessions may be working → `mac-dev-cleanup --min-age 2`
- "The cargo target / Rust cache is huge" → `mac-dev-cleanup --only cargo --dry-run`, then run it; lower `--cargo-days` or `--cargo-max-size` for a one-off deeper cut
- "`~/.cache/uv` is huge" / "清理 uv 缓存" → `mac-dev-cleanup --only uv --dry-run`, then run it; `--uv-days 3` for a deeper cut. **Never `uv cache prune --force` / `uv cache clean --force`** on this Mac: they delete the environment proc-top runs from
- "pnpm / npm / go cache is huge" → `mac-dev-cleanup --only pnpm --dry-run` (or `npm`, `go`), then run it. **Never `pnpm store prune`** on this Mac (see the pnpm notes)
- "`~/.codex` is huge" → `mac-dev-cleanup --only codex --dry-run`, then run it. Never delete rollout files by hand: the session index keeps pointing at them
- "`/private/var/folders` is huge" / a disk analyzer shows tens of GB of `code_sign_clone` → `mac-dev-cleanup --only clones --dry-run`, then run it. Expect a small real gain (see the clones notes)
- "The screen never turned off" / "something is busy at night" and a game was left open → `mac-dev-cleanup --only games`

### Per-project cleanup rules, archiving to LaCie, disk monitoring (dev-space)

**Script:** `scripts/dev-space` (linked as `dev-space`). **Rules:** `config/dev-space.toml`. **Agent brief:** `references/dev-space-analysis.md`. **State:** `~/.local/state/dev-space/` (`actions.jsonl` audit log, `history.jsonl`, `alerts.json`, `proposals/`, `trash/`). Design and decisions: `kb/plans/2026-11-13-dev-disk-cleanup.md` in the scripts repo.

What `mac-dev-cleanup` does for global caches, dev-space does inside `~/Code`. The config has defaults for every git project there (build trees and DB copies in `tmp/` after 7 days, SwiftPM index-build and `.next/cache` after 7 days, dependency dirs of projects idle for 30 days, `tmp/<date>-<task>/` evidence moved to LaCie after 14 days) plus rules per project. Each rule deletes, archives (to `/Volumes/LaCie/DevArchive/<project>/<path under ~>`, symlink left behind) or backs up a SQLite DB (vibench-live's production DB, daily, 7 daily + 8 weekly copies). Tiers: `daily` (06:00), `pressure` (also runs, with shorter ages, when free space < 15 GiB), `manual` (only by hand).

```bash
dev-space clean -n -v                 # what the daily tier would do, every path with its size and age
dev-space clean -n --tier manual      # include manual-only rules
dev-space clean -p vibench -r dev-migration-backups   # one rule of one project, for real
dev-space rules vibench               # rules that apply to a project (defaults included)
dev-space restore ~/Code/x/tmp/2026-10-01-task        # copy an archived dir back from LaCie
dev-space scan                        # sizes of every project and cache, 7-day growth, limits
dev-space watch --no-record --no-notify               # alerts, without touching state
dev-space proposals                   # rule proposals codex wrote
uv run scripts/test_dev_space.py      # behaviour tests
```

**Guards no rule can switch off:** a path git tracks, or that sits in a git worktree without being ignored, is never touched (untracked-not-ignored may be someone's work in progress); nor is anything a process has open, runs from or uses as cwd (one `lsof` snapshot per run); nor symlinks, paths outside the project's root/related dirs, or `protect` globs. Relative rule paths resolve against the project root only — reach a related dir (e.g. vibench-live) with a `~` path. Archive refuses `.git`, symlinks, `.app` bundles, secrets (`.env`, keys, `.gnupg`) and exFAT-illegal names, and skips when the volume isn't mounted (a `/Volumes/X` path must be a mount point, so an unplugged drive never means writing into an empty folder on the system disk). Copies are read back and compared by hash before the local copy goes; mtimes are kept. AppleDouble `._x` files exFAT creates beside `x` are not copied back on restore.

**Monitoring:** `watch` (06:00, after the cleanup) records sizes, alerts by macOS notification on low free space (< 40 GiB warn, < 15 GiB critical), projects over `alert_size` (3 GiB for projects without rules), 7-day growth > 3 GiB, caches over budget, and an offsite backup older than 3 days; the same alert repeats only after 3 days or when it escalates. With `--agent` it runs `codex exec --ephemeral -s read-only` on up to 2 flagged projects (14-day cooldown each) and saves its final message as a proposal; nothing is applied until a human merges it into the config. The read-only sandbox blocks `ps`, so proposals see processes only through `lsof`.

**Adding a project:** run `dev-space scan`, give an agent `references/dev-space-analysis.md`, review its TOML, add it under `[projects.<name>]`, then `dev-space clean -n -v -p <name> --tier manual` and read every path before the first real run.

**When to use:**
- "Disk is full" / "磁盘满了" → `dev-space scan` and `mac-dev-cleanup --dry-run` side by side; the `projects` section of the latter is dev-space
- "这个项目目录太大" / a project shows up in a watch alert → `dev-space clean -n -v -p <name> --tier manual`, then rules or a proposal
- "归档到 LaCie" / "恢复归档" → archive rules / `dev-space restore`

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

## macOS Keep-Awake

### Keep the Mac from sleeping for a long job, display still sleeps, max 24h

**Script:** `scripts/mac-keepawake` (linked to `~/.local/bin/mac-keepawake`)

**Prerequisites:** macOS only. Uses `uv run --script` with Python ≥3.11 (no third-party deps). Wraps `caffeinate`, `pmset -g`, `ps`, `system_profiler`. No sudo.

```bash
mac-keepawake on                 # 24h (default and maximum)
mac-keepawake on 8h --screen-off # 8h, and turn the display off right away
mac-keepawake off                # stop early
mac-keepawake                    # status: time left, who holds what, last log entry
uv run test_mac_keepawake.py     # 20 behaviour tests (e2e part skips while a real session runs)
```

**How it works:** `on` spawns a detached watcher (`setsid`, survives the terminal/SSH session) that runs `caffeinate -i -s -w <watcher> -t <duration+60s>` and checks the **wall clock** every 30s; at the deadline it terminates caffeinate and logs `OFF expired` — the same thing `off` does. No `-d`, so `displaysleep` still applies (this also keeps monitoring alert #15 "screen never slept for 6h" quiet). `pmset` is **never modified**, so there is nothing to restore: when the assertion goes away the normal timers apply again, and a crash, `kill` or reboot can't leave the Mac stuck awake.

**Notes / gotchas:**

- Sessions are found by scanning `ps` for `mac-keepawake _watch --since <epoch> --until <epoch>`; there is no state file. `off` signals only that watcher and its own caffeinate child — other caffeinates (Claude Code holds `caffeinate -i -t 300` while working) are listed as "not ours" and left alone. Covered by an e2e test with a real bystander caffeinate.
- `on` while a session runs **replaces** it (new 24h window from now), never stacks. Durations need a unit (`8h`, `90m`, `1h30m`, `45s`); over 24h is rejected, not clamped.
- The deadline is enforced by the watcher, not by caffeinate's `-t`, because `-t` isn't guaranteed to count time spent asleep (lid closed, Apple menu › Sleep); `-t` is only a backstop if the watcher hangs, `-w` kills caffeinate if the watcher dies.
- The watcher is started with `realpath(sys.executable)`: `uv run --script` executes from a temp env under `~/.cache/uv/builds-v0/` that uv deletes as soon as `on` exits.
- Still sleeps on: closing the lid **without** an external display (closed-display mode needs display + power), Apple menu › Sleep, critically low battery. `-s` only has effect on AC; `-i` covers battery.
- Log: `~/Library/Logs/mac-keepawake.log` (`ON` / `OFF <reason>` lines; `MAC_KEEPAWAKE_LOG` overrides it, used by the tests).

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

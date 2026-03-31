---
name: systools
description: "System operations toolkit for local development and debugging. Use when the user needs to: (1) check what's running on a port, kill a process on a port, free up a port, or deal with 'address already in use' errors — even casual phrases like 'what's on port 3000' or 'kill whatever is on 8080'; (2) check macOS system health — CPU temperature, memory/swap usage, disk space, CPU load, network traffic — triggered by phrases like 'how's my system', 'check health', 'is my mac overheating', 'memory usage', 'disk space', 'swap is high', 'cpu temp', 'system stats', or any question about the machine's overall condition; (3) monitor memory I/O pressure — page-in/out rates, swap churn, compression activity — triggered by phrases like 'memory pressure', 'is my mac swapping', 'paging activity', 'why is my mac slow', 'swap thrashing', 'pageouts', 'memory I/O', 'vm_stat', 'compressor pressure', or any question about whether the system is actively under memory pressure right now. Only use health/memory tools on macOS."
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

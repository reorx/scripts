#!/usr/bin/env bash
# portcheck.sh - Show detailed info for process(es) on a given port, optionally kill them

set -euo pipefail

kill_mode=false
port=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -k|--kill)
            kill_mode=true
            shift
            ;;
        -h|--help)
            echo "Usage: portcheck.sh [-k|--kill] <port>"
            echo
            echo "Show detailed info for process(es) listening on a given port."
            echo "With -k/--kill, kill the process(es) after displaying info."
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            echo "Usage: portcheck.sh [-k|--kill] <port>" >&2
            exit 1
            ;;
        *)
            port="$1"
            shift
            ;;
    esac
done

if [[ -z "$port" ]]; then
    echo "Usage: portcheck.sh [-k|--kill] <port>" >&2
    exit 1
fi

# Find PIDs listening on the port
pids=$(lsof -ti "tcp:$port" 2>/dev/null || true)

if [[ -z "$pids" ]]; then
    echo "No process found on port $port"
    exit 0
fi

echo "=== Port $port ==="

# Show detailed info for each unique PID
seen_pids=()
while IFS= read -r pid; do
    # skip duplicates
    for seen in "${seen_pids[@]+"${seen_pids[@]}"}"; do
        [[ "$seen" == "$pid" ]] && continue 2
    done
    seen_pids+=("$pid")

    echo

    # lsof fields for this pid on the port
    lsof_type=$(lsof -a -p "$pid" -i "tcp:$port" -Ft -P -n 2>/dev/null | grep '^t' | cut -c2- | head -1)
    lsof_name=$(lsof -a -p "$pid" -i "tcp:$port" -Fn -P -n 2>/dev/null | grep '^n' | cut -c2- | head -1)

    # ps fields (fetch each separately to avoid field-splitting issues with command)
    if ! ps -p "$pid" -o pid= >/dev/null 2>&1; then
        echo "(process $pid no longer exists)"
        continue
    fi
    p_pid=$(ps -p "$pid" -o pid= 2>/dev/null | xargs)
    p_ppid=$(ps -p "$pid" -o ppid= 2>/dev/null | xargs)
    p_user=$(ps -p "$pid" -o user= 2>/dev/null | xargs)
    p_stat=$(ps -p "$pid" -o stat= 2>/dev/null | xargs)
    p_cpu=$(ps -p "$pid" -o %cpu= 2>/dev/null | xargs)
    p_mem=$(ps -p "$pid" -o %mem= 2>/dev/null | xargs)
    p_start=$(ps -p "$pid" -o start= 2>/dev/null | xargs)
    p_cmd=$(ps -p "$pid" -o command= 2>/dev/null)

    # cwd (-a is critical: AND the filters, otherwise lsof ORs -p and -d)
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | grep '^n' | cut -c2-)

    # print aligned key-value pairs
    printf "COMMAND: %s\n"  "$p_cmd"
    printf "    PID: %s\n"  "$p_pid"
    printf "   PPID: %s\n"  "$p_ppid"
    printf "   USER: %s\n"  "$p_user"
    printf "   STAT: %s\n"  "$p_stat"
    printf "   %%CPU: %s\n" "$p_cpu"
    printf "   %%MEM: %s\n" "$p_mem"
    printf "  START: %s\n"  "$p_start"
    printf "   TYPE: %s\n"  "$lsof_type"
    printf "   NAME: %s\n"  "$lsof_name"
    [[ -n "$cwd" ]] && printf "    CWD: %s\n" "$cwd"
done <<< "$pids"

if $kill_mode; then
    echo "$pids" | xargs kill
    echo "Killed."
fi

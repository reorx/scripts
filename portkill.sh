#!/usr/bin/env bash
# portkill.sh - Show and kill process(es) listening on a given port

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: portkill.sh <port>" >&2
    exit 1
fi

port="$1"

# Find PIDs listening on the port
pids=$(lsof -ti "tcp:$port" 2>/dev/null || true)

if [[ -z "$pids" ]]; then
    echo "No process found on port $port"
    exit 0
fi

echo "Processes on port $port:"
echo
lsof -i "tcp:$port" -P -n
echo

read -rp "Kill these processes? [y/N] " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
    echo "$pids" | xargs kill
    echo "Killed."
else
    echo "Aborted."
fi

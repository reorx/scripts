#!/bin/bash

# @raycast.schemaVersion 1
# @raycast.title Show Env
# @raycast.mode fullOutput
# @raycast.packageName Debug

echo "=== PATH ==="
echo "$PATH"
echo ""
echo "=== which uv ==="
which uv 2>&1 || echo "uv not found"
echo ""
echo "=== Full Environment ==="
env | sort

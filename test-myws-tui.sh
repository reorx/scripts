#!/bin/bash

# Test script for myws-tui.py
# This script will cd to parent directory and run the TUI using uv

set -e

echo "Testing myws-tui.py..."
echo "Current directory: $(pwd)"

# Go to parent directory to test the TUI
cd ..
echo "Changed to directory: $(pwd)"

# Run the TUI application using uv
echo "Starting myws-tui.py with uv..."
uv run scripts/myws-tui.py
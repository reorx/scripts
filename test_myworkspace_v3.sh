#!/bin/bash

# Test script for myworkspace_textual_v3.py
# This script goes to parent directory and runs the v3 script

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Go to parent directory
cd "$SCRIPT_DIR/.."

# Run the myworkspace_textual_v3.py script
"$SCRIPT_DIR/myworkspace_textual_v3.py"
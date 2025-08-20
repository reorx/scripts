#!/bin/bash

# Test script for cc-notify.py - simulates Claude Code hook call

# Set test environment
export CLAUDE_PROJECT_DIR="/Users/reorx/Code/test-project"

# Use SOUND env var or default
SOUND="${SOUND:-default}"

# Simulate a Claude Code hook event
echo "Testing cc-notify.py with simulated hook data..."
echo "Using sound: $SOUND"
echo '{
  "session_id": "sess_1234567890abcdef",
  "transcript_path": "/tmp/claude/transcript.json",
  "cwd": "/Users/reorx/Code/test-project",
  "hook_event_name": "tool-before-bash"
}' | ./cc-notify.py -m "Running bash command" -s "$SOUND" -d \
    --icon '/Applications/Ani.app/Contents/Resources/Ani.icns'

echo "Test completed!"

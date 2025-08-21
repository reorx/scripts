#!/bin/bash

# Test script for cc-notify.py - simulates Claude Code hook call

# Set test environment
export CLAUDE_PROJECT_DIR="/Users/reorx/Code/test-project"

# Use SOUND env var or default
SOUND="${SOUND:-default}"
echo "Using sound: $SOUND"

ICON=""
echo "Using icon: $ICON"
if [ -n "$ICON" ]; then
    iconargs="--icon $ICON"
else
    iconargs=""
fi

if [ "$1" == "n" ]; then
    # Simulate a Claude Code hook event
    echo "test notification"
    echo '{
      "session_id": "sess_1234567890abcdef",
      "transcript_path": "/tmp/claude/transcript.json",
      "cwd": "/Users/reorx/Code/test-project",
      "hook_event_name": "tool-before-bash"
    }' | ./cc-notify.py -m "Running bash command" -s "$SOUND" -d
    echo "Test completed!"
elif [ "$1" == "a" ];then
    echo "test alert"
    echo '{
      "session_id": "sess_1234567890abcdef",
      "transcript_path": "/tmp/claude/transcript.json",
      "cwd": "/Users/reorx/Code/test-project",
      "hook_event_name": "tool-before-bash"
    }' | ./cc-notify.py -m "Running bash command" -s "$SOUND" -t alert $iconargs -d
fi


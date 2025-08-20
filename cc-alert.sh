#!/usr/bin/env bash

title="Claude Code"

# Get the content from first argument
content="$1"

# Get project name from CLAUDE_PROJECT_DIR environment variable
project_name=$(basename "$CLAUDE_PROJECT_DIR")

# Construct the message
message="$project_name: $content"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
icon="$SCRIPT_DIR/assets/icons/claude.icns"

# Display alert dialog in background (non-blocking)

osascript -e "use scripting additions

property app_icon : \"$icon\"

display dialog \"$message\" with title \"$title\" with icon POSIX file app_icon as alias buttons {\"OK\"} default button \"OK\"
return
" >/dev/null 2>&1 &

# Speak the message in background (non-blocking)
say "$message" &

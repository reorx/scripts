#!/bin/bash
set -euo pipefail

# Create a zettelkasten note in Obsidian using the Obsidian CLI.
# Usage: ob-zettel-create.sh [-t TAG]... TITLE [< content]
#
# Content is read from stdin if available, otherwise the note is created empty.
# After creation, the note is opened in Obsidian.
#
# Environment variables:
#   OBSIDIAN_ZETTEL_DIR  - directory path relative to vault root (required)
#   OBSIDIAN_VAULT       - vault name (optional, uses active vault if unset)

OBSIDIAN_ZETTEL_DIR="${OBSIDIAN_ZETTEL_DIR:-80 Zettelkasten Notes}"

TAGS=()
TITLE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -t)
            TAGS+=("$2")
            shift 2
            ;;
        *)
            TITLE="$1"
            shift
            ;;
    esac
done

if [[ -z "$TITLE" ]]; then
    echo "Usage: ob-zettel-create.sh [-t TAG]... TITLE" >&2
    echo "  Content is read from stdin if piped." >&2
    exit 1
fi

# Read content from stdin if available
CONTENT=""
if [[ ! -t 0 ]]; then
    CONTENT=$(cat)
fi

# Prepend tags
if [[ ${#TAGS[@]} -gt 0 ]]; then
    TAG_LINE=$(printf '#%s ' "${TAGS[@]}")
    TAG_LINE="${TAG_LINE% }"
    CONTENT="${TAG_LINE}

${CONTENT}"
fi

TIMESTAMP=$(date +"%Y%m%d.%H")
NOTE_PATH="${OBSIDIAN_ZETTEL_DIR}/${TIMESTAMP} ${TITLE}.md"

# Build vault parameter
VAULT_PARAM=""
if [[ -n "${OBSIDIAN_VAULT:-}" ]]; then
    VAULT_PARAM="vault=\"${OBSIDIAN_VAULT}\""
fi

# Create the note; use content param only if non-empty
if [[ -n "$CONTENT" ]]; then
    # Write via obsidian create for short content, fall back to direct file write for large content
    # obsidian CLI passes content as command-line arg which is subject to OS ARG_MAX (~256KB on macOS)
    VAULT_PATH=$(eval obsidian ${VAULT_PARAM} vault info=path 2>/dev/null | tr -d '\n')
    FILEPATH="${VAULT_PATH}/${NOTE_PATH}"
    mkdir -p "$(dirname "$FILEPATH")"
    printf '%s' "$CONTENT" > "$FILEPATH"
else
    eval obsidian ${VAULT_PARAM} create path="\"${NOTE_PATH}\""
fi

# Open the note in Obsidian
eval obsidian ${VAULT_PARAM} open path="\"${NOTE_PATH}\""

echo "Created and opened: ${NOTE_PATH}"

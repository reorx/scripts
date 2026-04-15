#!/bin/bash
set -euo pipefail

# Create a zettelkasten note by writing directly to the vault on disk,
# then open it in Obsidian via the obsidian CLI.
# Usage: ob-zettel-create.sh [-t TAG]... [-n] [--src FILE] TITLE [< content]
#
# Content source priority: --src FILE > piped stdin > empty.
# After creation, the note is opened via `obsidian open` unless -n is passed.
#
# Environment variables:
#   OBSIDIAN_VAULT_PATH  absolute path to the vault root (required)
#   OBSIDIAN_ZETTEL_DIR  directory relative to vault root (default: "80 Zettelkasten Notes")

if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
    echo "error: OBSIDIAN_VAULT_PATH is not set" >&2
    echo "  set it to the absolute path of your Obsidian vault root" >&2
    exit 1
fi

if [[ ! -d "$OBSIDIAN_VAULT_PATH" ]]; then
    echo "error: OBSIDIAN_VAULT_PATH is not a directory: $OBSIDIAN_VAULT_PATH" >&2
    exit 1
fi

ZETTEL_DIR="${OBSIDIAN_ZETTEL_DIR:-80 Zettelkasten Notes}"

TAGS=()
TITLE=""
OPEN_AFTER=1
SRC_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -t)
            TAGS+=("$2")
            shift 2
            ;;
        -n)
            OPEN_AFTER=0
            shift
            ;;
        --src)
            SRC_FILE="$2"
            shift 2
            ;;
        *)
            TITLE="$1"
            shift
            ;;
    esac
done

if [[ -z "$TITLE" ]]; then
    echo "usage: ob-zettel-create.sh [-t TAG]... [-n] [--src FILE] TITLE" >&2
    echo "  content priority: --src FILE > piped stdin > empty" >&2
    echo "  -n   do not open the note in Obsidian after creating" >&2
    exit 1
fi

CONTENT=""
if [[ -n "$SRC_FILE" ]]; then
    if [[ ! -f "$SRC_FILE" ]]; then
        echo "error: --src file not found: $SRC_FILE" >&2
        exit 1
    fi
    CONTENT=$(cat "$SRC_FILE")
elif [[ ! -t 0 ]]; then
    CONTENT=$(cat)
fi

if [[ ${#TAGS[@]} -gt 0 ]]; then
    TAG_LINE=$(printf '#%s ' "${TAGS[@]}")
    TAG_LINE="${TAG_LINE% }"
    CONTENT="${TAG_LINE}

${CONTENT}"
fi

TIMESTAMP=$(date +"%Y%m%d.%H")
REL_PATH="${ZETTEL_DIR}/${TIMESTAMP} ${TITLE}.md"
FILE_PATH="${OBSIDIAN_VAULT_PATH}/${REL_PATH}"

mkdir -p "$(dirname "$FILE_PATH")"
printf '%s' "$CONTENT" > "$FILE_PATH"

if [[ $OPEN_AFTER -eq 1 ]]; then
    obsidian open path="$REL_PATH"
fi

echo "Created: ${REL_PATH}"

#!/bin/bash
set -euo pipefail

DIR_PATH="${DIR_PATH:-80 Zettelkasten Notes}"
TAG=""
TITLE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)
            TAG="$2"
            shift 2
            ;;
        *)
            TITLE="$1"
            shift
            ;;
    esac
done

if [[ -z "$TITLE" ]]; then
    echo "Usage: cat foo.md | ob-zettel.sh [--tag TAG] TITLE" >&2
    exit 1
fi

CONTENT=$(cat)

if [[ -n "$TAG" ]]; then
    CONTENT="#${TAG}

${CONTENT}"
fi

if [[ -z "${VAULT_PATH:-}" ]]; then
    if command -v obsidian-cli &>/dev/null; then
        VAULT_PATH=$(obsidian-cli print-default 2>/dev/null | grep 'Default vault path:' | sed 's/Default vault path:  //')
    fi
fi
if [[ -z "${VAULT_PATH:-}" ]]; then
    echo "Error: VAULT_PATH is not set and obsidian-cli is not available" >&2
    exit 1
fi

TIMESTAMP=$(date +"%Y%m%d.%H")
FILENAME="${DIR_PATH}/${TIMESTAMP} ${TITLE}.md"
FILEPATH="${VAULT_PATH}/${FILENAME}"

# Write file directly instead of using `obsidian-cli create --content`,
# because --content passes data as a command-line argument which is subject to
# OS ARG_MAX limit (~256KB on macOS), causing large content to be truncated.
mkdir -p "$(dirname "$FILEPATH")"
printf '%s' "$CONTENT" > "$FILEPATH"

if command -v obsidian-cli &>/dev/null; then
    obsidian-cli open "$FILENAME"
fi
echo "\`$FILENAME\` created in obsidian"

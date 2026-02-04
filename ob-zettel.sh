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

TIMESTAMP=$(date +"%Y%m%d.%H")
FILENAME="${DIR_PATH}/${TIMESTAMP} ${TITLE}.md"

obsidian-cli create "$FILENAME" --content "$CONTENT" --overwrite --open

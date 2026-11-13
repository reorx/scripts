#!/bin/bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: openon.sh [user@]host:path/to/file

Copy a remote file with scp and open it with the macOS default application.
Relative remote paths start at the remote user's home directory.
Quote the argument if the path contains spaces.

Example: openon.sh genji.ts:Code/foo/bar.md

Each download gets a fresh temporary directory, keeping the original filename.
The local copy is retained after opening; edits are not uploaded to the remote.
EOF
}

main() {
    if [[ $# == 1 && ($1 == --help || $1 == -h) ]]; then
        usage
        return
    fi
    if [[ $# != 1 ]]; then
        usage >&2
        return 2
    fi

    local source=$1 remote_path filename directory target status
    if [[ $source != *:* || $source == :* || $source == -* ]]; then
        echo 'Error: expected [user@]host:path/to/file' >&2
        return 2
    fi
    remote_path=${source#*:}
    filename=${remote_path##*/}
    if [[ -z $filename || $filename == . || $filename == .. ]]; then
        echo 'Error: specify a remote file, not a directory.' >&2
        return 2
    fi

    directory=$(mktemp -d "${TMPDIR:-/tmp}/openon.XXXXXX")
    target=$directory/$filename
    if scp -- "$source" "$target"; then
        printf 'Local copy: %s\n' "$target"
        open "$target"
    else
        status=$?
        rm -rf "$directory"
        return "$status"
    fi
}

main "$@"

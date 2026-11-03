#!/usr/bin/env bash
set -euo pipefail

# Runs agent-inspect-session.sh against fake config dirs; never reads the real ~/.claude.
script="$(cd "$(dirname "$0")" && pwd)/agent-inspect-session.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failures=0
session_id=11111111-2222-3333-4444-555555555555

write_transcript() {
    local dir=$1
    mkdir -p "$dir/-Users-me-proj"
    cat > "$dir/-Users-me-proj/$session_id.jsonl" <<'JSONL'
{"type":"user","message":{"role":"user","content":"hi"}}
{"type":"assistant","message":{"role":"assistant","model":"claude-opus-4-5","content":[{"type":"text","text":"hello"}],"usage":{"input_tokens":2,"cache_creation_input_tokens":8000,"cache_read_input_tokens":14000,"output_tokens":10}}}
JSONL
}

expect_tokens() {
    local name=$1 config_dir=$2 got
    got=$(env -u CODEX_SESSION_ID -u CODEX_THREAD_ID \
        CLAUDE_CONFIG_DIR="$config_dir" CLAUDE_CODE_SESSION_ID="$session_id" \
        "$script" --json | jq -r '"\(.model) \(.context_tokens)"')
    if [[ "$got" == "claude-opus-4-5 22002" ]]; then
        echo "ok: $name"
    else
        echo "FAIL: $name: got '$got'"
        failures=$((failures + 1))
    fi
}

# Plain directory layout.
write_transcript "$work/plain/projects"
expect_tokens "projects is a directory" "$work/plain"

# ~/.claude/projects synced elsewhere (e.g. iCloud) through a symlink.
write_transcript "$work/real-projects"
mkdir -p "$work/linked"
ln -s "$work/real-projects" "$work/linked/projects"
expect_tokens "projects is a symlink" "$work/linked"

# The whole config dir is a symlink too.
ln -s "$work/linked" "$work/linked-config"
expect_tokens "config dir and projects are symlinks" "$work/linked-config"

if (( failures )); then
    echo "$failures test(s) failed"
    exit 1
fi
echo "all tests passed"

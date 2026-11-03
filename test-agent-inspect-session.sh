#!/usr/bin/env bash
set -euo pipefail

# Runs agent-inspect-session.sh against fake config dirs; never reads the real ~/.claude.
script="$(cd "$(dirname "$0")" && pwd)/agent-inspect-session.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failures=0
session_id=11111111-2222-3333-4444-555555555555

# Latest response: 2 + 8000 + 14000 = 22002 context tokens.
write_transcript() {
    local dir=$1 model=${2:-claude-opus-4-5}
    mkdir -p "$dir/-Users-me-proj"
    cat > "$dir/-Users-me-proj/$session_id.jsonl" <<JSONL
{"type":"user","message":{"role":"user","content":"hi"}}
{"type":"assistant","message":{"role":"assistant","model":"$model","content":[{"type":"text","text":"hello"}],"usage":{"input_tokens":2,"cache_creation_input_tokens":8000,"cache_read_input_tokens":14000,"output_tokens":10}}}
JSONL
}

# Account catalog, as cached by Claude Code 2.1.311: one line, no trailing newline.
write_cc_catalog() {
    local config_dir=$1 name=$2 fetched_at=$3 model=$4 window=$5
    mkdir -p "$config_dir/cache/model-catalog"
    printf '%s' "{\"version\":2,\"fetchedAt\":$fetched_at,\"staleAt\":$fetched_at,\"catalog\":{\"surface\":\"cc\",\"config\":{\"id\":\"cc\",\"models\":[{\"id\":\"$model\",\"name\":\"Model\",\"runtime\":{\"max_input_tokens\":$window,\"max_output_tokens\":128000}}]}}}" \
        > "$config_dir/cache/model-catalog/$name-cc.json"
}

# Published catalog: models of every surface, only the cc surface applies.
write_published_catalog() {
    local config_dir=$1 fetched_at=$2 model=$3 window=$4
    mkdir -p "$config_dir/cache/model-catalog"
    printf '%s' "{\"version\":1,\"fetchedAt\":$fetched_at,\"source\":\"hosted\",\"document\":{\"surfaces\":{\"cc\":{\"model_selector_config\":[{\"models\":[{\"id\":\"$model\",\"runtime\":{\"max_input_tokens\":$window}}]}]},\"web\":{\"model_selector_config\":[{\"models\":[{\"id\":\"$model\",\"runtime\":{\"max_input_tokens\":1}}]}]}}}}" \
        > "$config_dir/cache/model-catalog/published-0123abcd.json"
    printf '%s' '{"version":1,"sources":{}}' > "$config_dir/cache/model-catalog/published-floor.json"
}

# Usage: inspect CONFIG_DIR [ENV=VALUE...] -- [SCRIPT ARGS...]; prints JSON.
inspect() {
    local config_dir=$1 envs=()
    shift
    while (( $# )) && [[ "$1" != -- ]]; do envs+=("$1"); shift; done
    (( $# )) && shift
    env -u CODEX_SESSION_ID -u CODEX_THREAD_ID -u CLAUDE_CODE_DISABLE_1M_CONTEXT \
        CLAUDE_CONFIG_DIR="$config_dir" CLAUDE_CODE_SESSION_ID="$session_id" \
        ${envs[@]+"${envs[@]}"} "$script" --json ${@+"$@"}
}

expect() {
    local name=$1 want=$2 got=$3
    if [[ "$got" == "$want" ]]; then
        echo "ok: $name"
    else
        echo "FAIL: $name: want '$want', got '$got'"
        failures=$((failures + 1))
    fi
}

fields='"\(.model) \(.context_tokens) \(.context_window) \(.context_used_percent) \(.context_source)"'

# --- transcript lookup ---

write_transcript "$work/plain/projects"
expect "projects is a directory" "claude-opus-4-5 22002 200000 11 model-default" \
    "$(inspect "$work/plain" | jq -r "$fields")"

# ~/.claude/projects synced elsewhere (e.g. iCloud) through a symlink.
write_transcript "$work/real-projects"
mkdir -p "$work/linked"
ln -s "$work/real-projects" "$work/linked/projects"
expect "projects is a symlink" "claude-opus-4-5 22002 200000 11 model-default" \
    "$(inspect "$work/linked" | jq -r "$fields")"

# The whole config dir is a symlink too.
ln -s "$work/linked" "$work/linked-config"
expect "config dir and projects are symlinks" "claude-opus-4-5 22002 200000 11 model-default" \
    "$(inspect "$work/linked-config" | jq -r "$fields")"

# --- context window from the model catalog ---

write_transcript "$work/no-catalog/projects" claude-opus-5-5
expect "unknown model without catalog" "claude-opus-5-5 22002 null null unknown" \
    "$(inspect "$work/no-catalog" | jq -r "$fields")"

write_transcript "$work/cc/projects" claude-opus-5-5
write_cc_catalog "$work/cc" acct 1793683186341 claude-opus-5-5 1000000
expect "window from account catalog" "claude-opus-5-5 22002 1000000 2 catalog" \
    "$(inspect "$work/cc" | jq -r "$fields")"

# Catalog beats the built-in 200k default for older models.
write_transcript "$work/cc-old/projects" claude-opus-4-5
write_cc_catalog "$work/cc-old" acct 1793683186341 claude-opus-4-5 400000
expect "catalog beats built-in default" "claude-opus-4-5 22002 400000 6 catalog" \
    "$(inspect "$work/cc-old" | jq -r "$fields")"

write_transcript "$work/published/projects" claude-opus-5-5
write_published_catalog "$work/published" 1793589047962 claude-opus-5-5 1000000
expect "window from published catalog, cc surface only" "claude-opus-5-5 22002 1000000 2 catalog" \
    "$(inspect "$work/published" | jq -r "$fields")"

# Account catalog wins over the published one, even when older.
write_transcript "$work/both/projects" claude-opus-5-5
write_published_catalog "$work/both" 1793683186341 claude-opus-5-5 1000000
write_cc_catalog "$work/both" acct 1793589047962 claude-opus-5-5 200000
expect "account catalog beats published" "claude-opus-5-5 22002 200000 11 catalog" \
    "$(inspect "$work/both" | jq -r "$fields")"

# Several account catalogs: the most recently fetched one wins.
write_transcript "$work/two-cc/projects" claude-opus-5-5
write_cc_catalog "$work/two-cc" old 1793589047962 claude-opus-5-5 200000
write_cc_catalog "$work/two-cc" new 1793683186341 claude-opus-5-5 1000000
expect "newest account catalog wins" "claude-opus-5-5 22002 1000000 2 catalog" \
    "$(inspect "$work/two-cc" | jq -r "$fields")"

# A half-written cache file must not hide the others.
write_transcript "$work/broken/projects" claude-opus-5-5
write_cc_catalog "$work/broken" good 1793589047962 claude-opus-5-5 1000000
printf '{"version":2,"fetchedAt":17936' > "$work/broken/cache/model-catalog/bad-cc.json"
expect "malformed catalog file is skipped" "claude-opus-5-5 22002 1000000 2 catalog" \
    "$(inspect "$work/broken" | jq -r "$fields")"

# Model missing from the catalog falls through to the built-in defaults.
write_transcript "$work/miss/projects" claude-opus-4-5
write_cc_catalog "$work/miss" acct 1793683186341 claude-opus-5-5 1000000
expect "model absent from catalog" "claude-opus-4-5 22002 200000 11 model-default" \
    "$(inspect "$work/miss" | jq -r "$fields")"

expect "CLAUDE_CODE_DISABLE_1M_CONTEXT caps the window" "claude-opus-5-5 22002 200000 11 catalog" \
    "$(inspect "$work/cc" CLAUDE_CODE_DISABLE_1M_CONTEXT=1 | jq -r "$fields")"

expect "--context-window beats catalog and the 1M switch" "claude-opus-5-5 22002 100000 22 override" \
    "$(inspect "$work/cc" CLAUDE_CODE_DISABLE_1M_CONTEXT=1 -- --context-window 100000 | jq -r "$fields")"

# --- output field names ---

expect "JSON percent fields say they are used, not remaining" "2 2" \
    "$(inspect "$work/cc" | jq -r '"\(.context_used_percent) \(.raw_context_used_percent)"')"

expect "text output labels the used percent" "context_used_percent: 2%" \
    "$(env -u CODEX_SESSION_ID -u CODEX_THREAD_ID CLAUDE_CONFIG_DIR="$work/cc" \
        CLAUDE_CODE_SESSION_ID="$session_id" "$script" | grep '^context_used')"

if (( failures )); then
    echo "$failures test(s) failed"
    exit 1
fi
echo "all tests passed"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/agent-inspect-session.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export CODEX_HOME="$WORK/codex" CLAUDE_CONFIG_DIR="$WORK/claude"
unset CODEX_SESSION_ID CODEX_THREAD_ID CLAUDE_CODE_SESSION_ID
mkdir -p "$CODEX_HOME/sessions/2026/10/09" "$CLAUDE_CONFIG_DIR/projects/project"
CODEX_LOG="$CODEX_HOME/sessions/2026/10/09/rollout-test-codex-session.jsonl"
CLAUDE_LOG="$CLAUDE_CONFIG_DIR/projects/project/claude-session.jsonl"
passed=0

expect() {
    local label=$1 filter=$2 output=$3
    if ! jq -e "$filter" <<< "$output" >/dev/null; then
        printf 'FAIL: %s\n%s\n' "$label" "$output" >&2
        exit 1
    fi
    printf 'PASS: %s\n' "$label"
    passed=$((passed + 1))
}

# Given multiple responses, report the latest context, never cumulative usage.
cat > "$CODEX_LOG" <<'JSON'
{"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"total_tokens":80000},"model_context_window":200000}}}
{"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"total_tokens":50000},"total_token_usage":{"total_tokens":900000},"model_context_window":200000}}}
{"type":"event_msg","payload":{"type":"token_count","info":null}}
{"unfinished":
JSON
export CODEX_SESSION_ID=codex-session
expect 'Codex latest usage and incomplete trailing line' '.agent == "codex" and .session_id == "codex-session" and .context_percent == 25' "$(bash "$SCRIPT" --json)"
unset CODEX_SESSION_ID
export CODEX_THREAD_ID=codex-session
expect 'Codex thread ID fallback' '.context_percent == 25' "$(bash "$SCRIPT" --json)"
unset CODEX_THREAD_ID

cat > "$CLAUDE_LOG" <<'JSON'
{"type":"assistant","message":{"model":"claude-sonnet-4-20250514","usage":{"input_tokens":10000,"cache_creation_input_tokens":20000,"cache_read_input_tokens":30000,"output_tokens":40000}}}
JSON
export CLAUDE_CODE_SESSION_ID=claude-session
expect 'Claude includes both caches, excludes output' '.agent == "claude" and .context_percent == 30 and .context_window == 200000 and .context_source == "model-default"' "$(bash "$SCRIPT" --json)"
expect 'Explicit extended context window' '.context_percent == 6 and .context_window == 1000000' "$(bash "$SCRIPT" --json --context-window 1000000)"

cat > "$CLAUDE_LOG" <<'JSON'
{"type":"assistant","message":{"model":"claude-opus-5","usage":{"input_tokens":10000,"cache_creation_input_tokens":20000,"cache_read_input_tokens":30000}}}
{"type":"cost-state","modelUsage":{"claude-opus-5[1m]":{"inputTokens":9999999}}}
JSON
expect 'Claude extended model key from session cost state' '.context_percent == 6 and .context_window == 1000000' "$(bash "$SCRIPT" --json)"
cat >> "$CLAUDE_LOG" <<'JSON'
{"type":"cost-state","modelUsage":{"claude-opus-5":{"contextWindow":300000}}}
JSON
expect 'Claude recorded window' '.context_percent == 20 and .context_source == "session"' "$(bash "$SCRIPT" --json)"
cat >> "$CLAUDE_LOG" <<'JSON'
{"type":"system","subtype":"compact_boundary"}
JSON
expect 'Claude compaction invalidates old usage' '.context_percent == null' "$(bash "$SCRIPT" --json 2>/dev/null)"
cat >> "$CLAUDE_LOG" <<'JSON'
{"type":"assistant","message":{"model":"custom-model","usage":{"input_tokens":1000}}}
JSON
expect 'Unknown model does not guess a window' '.context_percent == null' "$(bash "$SCRIPT" --json 2>/dev/null)"
expect 'Override makes custom models usable' '.context_percent == 1' "$(bash "$SCRIPT" --json --context-window 100000)"

export CODEX_SESSION_ID=codex-session
if bash "$SCRIPT" --json > /dev/null 2>&1; then
    echo 'FAIL: ambiguous agents must fail' >&2; exit 1
fi
expect 'Explicit agent resolves inherited IDs' '.agent == "codex"' "$(bash "$SCRIPT" --json --agent codex)"
unset CODEX_SESSION_ID CLAUDE_CODE_SESSION_ID
if bash "$SCRIPT" > /dev/null 2>&1; then
    echo 'FAIL: missing session must fail' >&2; exit 1
fi
export CODEX_SESSION_ID=missing-session
expect 'Missing transcript preserves identity' '.session_id == "missing-session" and .context_percent == null' "$(bash "$SCRIPT" --json 2>/dev/null)"
unset CODEX_SESSION_ID
export CLAUDE_CODE_SESSION_ID=missing-session
expect 'Claude missing transcript preserves identity' '.agent == "claude" and .context_percent == null' "$(bash "$SCRIPT" --json)"
export CLAUDE_CODE_SESSION_ID=claude-session
: > "$CLAUDE_LOG"
expect 'Claude empty transcript before first response' '.context_percent == null' "$(bash "$SCRIPT" --json 2>/dev/null)"
cat > "$CLAUDE_LOG" <<'JSON'
{"type":"assistant","message":{"model":"claude-opus-4-20250514","usage":{"input_tokens":0}}}
{"type":"assistant","isSidechain":true,"message":{"model":"claude-opus-4-20250514","usage":{"input_tokens":190000}}}
{"type":"assistant","message":{"model":"<synthetic>","usage":{"input_tokens":10000}}}
JSON
expect 'Real zero usage survives sidechain and synthetic messages' '.context_percent == 0' "$(bash "$SCRIPT" --json)"
unset CLAUDE_CODE_SESSION_ID
export CODEX_SESSION_ID=codex-session
if bash "$SCRIPT" --context-window 0 >/dev/null 2>&1; then
    echo 'FAIL: zero window must fail' >&2; exit 1
fi
output=$(bash "$SCRIPT")
[[ "$output" == *'agent: codex'* && "$output" == *'session_id: codex-session'* && "$output" == *'context_percent: 25%'* ]]
echo "$passed JSON cases and CLI error/text checks passed."

#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/agent-inspect-session.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export CODEX_HOME="$WORK/codex" CLAUDE_CONFIG_DIR="$WORK/claude"
export XDG_CACHE_HOME="$WORK/local-cache"
unset CODEX_SESSION_ID CODEX_THREAD_ID CLAUDE_CODE_SESSION_ID
# Reproduce a Claude config directory symlinked into cloud storage.
mkdir -p "$WORK/cloud/claude"
ln -s "$WORK/cloud/claude" "$CLAUDE_CONFIG_DIR"
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
expect 'Codex latest usage and incomplete trailing line' '.agent == "codex" and .session_id == "codex-session" and .context_percent == 20 and .raw_context_percent == 25' "$(bash "$SCRIPT" --json)"
unset CODEX_SESSION_ID
export CODEX_THREAD_ID=codex-session
expect 'Codex thread ID fallback' '.context_percent == 20' "$(bash "$SCRIPT" --json)"
cp "$CODEX_LOG" "$WORK/original.jsonl"
for sample in '53066 258400 17 21' '1000 200000 0 1' '2140 12000 100 18' '12500 112000 0 11' '300000 200000 100 150'; do
    read -r tokens capacity expected raw <<< "$sample"
    jq -nc --argjson tokens "$tokens" --argjson capacity "$capacity" '{type:"event_msg",payload:{type:"token_count",info:{last_token_usage:{total_tokens:$tokens},model_context_window:$capacity}}}' > "$CODEX_LOG"
    expect "Codex native rounding and boundaries: $sample" ".context_percent == $expected and .raw_context_percent == $raw" "$(bash "$SCRIPT" --json)"
done
cp "$WORK/original.jsonl" "$CODEX_LOG"
# Given a model/effort switch, report the latest turn even before token usage.
cat >> "$CODEX_LOG" <<'JSON'
{"type":"turn_context","payload":{"model":"model-old","effort":"low"}}
{"type":"turn_context","payload":{"model":"model-current","effort":"high","collaboration_mode":{"settings":{"reasoning_effort":"low"}}}}
JSON
expect 'Codex latest turn model and effort' '.model == "model-current" and .thinking_effort == "high" and .context_percent == 20' "$(bash "$SCRIPT" --json)"
output=$(bash "$SCRIPT")
[[ "$output" == *'model: model-current'* && "$output" == *'thinking_effort: high'* ]]
cat >> "$CODEX_LOG" <<'JSON'
{"type":"turn_context","payload":{"model":"model-next"}}
JSON
expect 'Missing effort must not retain previous turn effort' '.model == "model-next" and .thinking_effort == null' "$(bash "$SCRIPT" --json)"
cat >> "$CODEX_LOG" <<'JSON'
{"type":"turn_context","payload":{"model":"model-next","effort":"none"}}
{"type":"compacted"}
JSON
expect 'Compaction preserves model and explicit none effort' '.model == "model-next" and .thinking_effort == "none" and .context_percent == null' "$(bash "$SCRIPT" --json 2>/dev/null)"
cp "$WORK/original.jsonl" "$CODEX_LOG"
expect 'Older transcripts expose unknown model and effort' 'has("model") and has("thinking_effort") and .model == null and .thinking_effort == null' "$(bash "$SCRIPT" --json)"
unset CODEX_THREAD_ID

cat > "$CLAUDE_LOG" <<'JSON'
{"type":"assistant","message":{"model":"claude-sonnet-4-20250514","usage":{"input_tokens":10000,"cache_creation_input_tokens":20000,"cache_read_input_tokens":30000,"output_tokens":40000}}}
JSON
export CLAUDE_CODE_SESSION_ID=claude-session
expect 'Claude includes both caches, excludes output' '.agent == "claude" and .context_percent == 30 and .context_window == 200000 and .context_source == "model-default"' "$(bash "$SCRIPT" --json)"
expect 'Claude transcript model without guessing effort' '.model == "claude-sonnet-4-20250514" and has("thinking_effort") and .thinking_effort == null' "$(bash "$SCRIPT" --json)"
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
# Queries must not create cache directories, including under cloud-synced config.
[[ ! -e "$XDG_CACHE_HOME" && ! -e "$CLAUDE_CONFIG_DIR/agent-inspect-session" ]]
# Given conflicting old caches, only the transcript determines the result.
mkdir -p "$XDG_CACHE_HOME/agent-inspect-session" "$CLAUDE_CONFIG_DIR/agent-inspect-session"
cat > "$WORK/old-cache.json" <<'JSON'
{"agent":"claude","session_id":"claude-session","model":"cached-model","updated_at":1,"context_window":{"used_percentage":17,"context_window_size":1000000,"current_usage":{"input_tokens":170000}}}
JSON
cp "$WORK/old-cache.json" "$XDG_CACHE_HOME/agent-inspect-session/claude-session.json"
cp "$WORK/old-cache.json" "$CLAUDE_CONFIG_DIR/agent-inspect-session/claude-session.json"
expect 'Old caches cannot override transcript data' '.model == "claude-opus-4-20250514" and .context_percent == 0 and .context_source == "model-default" and (has("updated_at") | not) and (has("cache_age_seconds") | not)' "$(bash "$SCRIPT" --json)"
cat >> "$CLAUDE_LOG" <<'JSON'
{"type":"assistant","message":{"model":"claude-opus-4-20250514","usage":{"input_tokens":40000}}}
JSON
expect 'Next query immediately reads appended transcript usage' '.context_tokens == 40000 and .context_percent == 20' "$(bash "$SCRIPT" --json)"
expect 'Override uses transcript tokens despite old caches' '.context_percent == 4 and .context_source == "override"' "$(bash "$SCRIPT" --json --context-window 1000000)"
cat >> "$CLAUDE_LOG" <<'JSON'
{"type":"system","subtype":"compact_boundary"}
JSON
expect 'Old cache cannot resurrect usage after compaction' '.context_percent == null' "$(bash "$SCRIPT" --json 2>/dev/null)"
rm "$CLAUDE_LOG"
expect 'Old cache cannot replace a missing transcript' '.model == null and .context_percent == null' "$(bash "$SCRIPT" --json 2>/dev/null)"
cmp "$WORK/old-cache.json" "$XDG_CACHE_HOME/agent-inspect-session/claude-session.json"
cmp "$WORK/old-cache.json" "$CLAUDE_CONFIG_DIR/agent-inspect-session/claude-session.json"
rm -r "$XDG_CACHE_HOME/agent-inspect-session" "$CLAUDE_CONFIG_DIR/agent-inspect-session"
if bash "$SCRIPT" --cache-statusline < "$WORK/old-cache.json" > "$WORK/removed-option.out" 2> "$WORK/removed-option.err"; then
    echo 'FAIL: removed cache writer option must fail' >&2; exit 1
fi
[[ ! -s "$WORK/removed-option.out" ]]
[[ "$(cat "$WORK/removed-option.err")" == 'Unknown argument: --cache-statusline' ]]
[[ ! -e "$XDG_CACHE_HOME/agent-inspect-session" && ! -e "$CLAUDE_CONFIG_DIR/agent-inspect-session" ]]
# Unknown windows still expose token evidence and actionable guidance.
cat > "$CLAUDE_LOG" <<'JSON'
{"type":"assistant","message":{"model":"custom-model","usage":{"input_tokens":100000}}}
JSON
expect 'Unknown window warns at token threshold' '.context_percent == null and .context_tokens == 100000 and .assessment_basis == "tokens" and .context_high == true and (.guidance | contains("context is unknown") and contains("new session"))' "$(bash "$SCRIPT" --json)"
output=$(bash "$SCRIPT")
[[ "$output" == *'context_tokens: 100000'* && "$output" == *'context is unknown'* && "$output" == *'new session'* ]]
expect 'Known window takes precedence over absolute token heuristic' '.context_percent == 10 and .assessment_basis == "percent" and .context_high == null' "$(bash "$SCRIPT" --json --context-window 1000000)"
cat > "$CLAUDE_LOG" <<'JSON'
{"type":"assistant","message":{"model":"custom-model","usage":{"input_tokens":99999}}}
JSON
expect 'Below token threshold is not proof of safety' '.context_high == false and (.guidance | contains("does not prove"))' "$(bash "$SCRIPT" --json)"
# Count UTF-8 message text and tool payloads, not metadata or image data.
cat > "$CLAUDE_LOG" <<'JSON'
{"type":"user","message":{"content":"中文"},"metadata":"not context"}
{"type":"assistant","message":{"model":"custom-model","content":[{"type":"text","text":"abc"},{"type":"tool_use","input":{"x":1}},{"type":"image","source":{"data":"ignore"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","content":[{"type":"text","text":"ok"}]}]}}
{"type":"assistant","isSidechain":true,"message":{"content":"ignore"}}
{"type":"progress","data":{"text":"ignore"}}
{"unfinished":
JSON
expect 'Bytes count message content only, including Unicode and tools' '.context_tokens == null and .context_bytes == 18 and .assessment_basis == "bytes" and .model == "custom-model" and .context_high == false' "$(bash "$SCRIPT" --json)"
expect 'Window alone cannot produce a percentage without tokens' '.context_window == 200000 and .context_percent == null and .assessment_basis == "bytes" and .context_bytes == 18' "$(bash "$SCRIPT" --json --context-window 200000)"
cat >> "$CLAUDE_LOG" <<'JSON'
{"type":"system","subtype":"compact_boundary"}
{"type":"user","message":{"content":"summary"}}
JSON
expect 'Compaction resets byte estimate to retained summary' '.context_bytes == 7 and .context_tokens == null' "$(bash "$SCRIPT" --json)"
jq -nc '{type:"user",message:{content:("x" * 400000)}}' > "$CLAUDE_LOG"
expect 'Byte threshold warns without inventing tokens' '.context_bytes == 400000 and .context_tokens == null and .context_high == true and (.guidance | contains("new session"))' "$(bash "$SCRIPT" --json)"
output=$(bash "$SCRIPT")
[[ "$output" == *'context_tokens: unknown'* && "$output" == *'context_bytes (approximate UTF-8): 400000'* && "$output" == *'new session'* ]]
cat >> "$CLAUDE_LOG" <<'JSON'
{"type":"assistant","message":{"model":"custom-model","usage":{"input_tokens":0}}}
JSON
expect 'Measured zero tokens outranks large byte estimate' '.assessment_basis == "tokens" and .context_tokens == 0 and .context_high == false' "$(bash "$SCRIPT" --json)"
jq -nc '{type:"user",message:{content:("x" * 399999)}}' > "$CLAUDE_LOG"
expect 'Below byte threshold does not trigger a high-context warning' '.context_bytes == 399999 and .context_high == false' "$(bash "$SCRIPT" --json)"
: > "$CLAUDE_LOG"
expect 'Empty transcript cannot imply zero context' '.assessment_basis == "unavailable" and .context_bytes == null and .context_high == null and (.guidance | contains("cannot assess"))' "$(bash "$SCRIPT" --json)"
cp "$CODEX_LOG" "$WORK/codex-original.jsonl"
cat > "$CODEX_LOG" <<'JSON'
{"type":"response_item","payload":{"type":"message","content":[{"type":"input_text","text":"old history"}]}}
{"type":"compacted","replacement_history":[{"type":"message","content":[{"type":"input_text","text":"summary"}]}]}
{"type":"response_item","payload":{"type":"function_call","arguments":"{}"}}
{"type":"response_item","payload":{"type":"function_call_output","output":"ok"}}
{"type":"event_msg","payload":{"type":"user_message","message":"duplicate display event"}}
JSON
export CODEX_SESSION_ID=codex-session
expect 'Codex uses replacement history and excludes display duplicates' '.assessment_basis == "bytes" and .context_bytes == 11' "$(bash "$SCRIPT" --agent codex --json)"
cp "$WORK/codex-original.jsonl" "$CODEX_LOG"
unset CLAUDE_CODE_SESSION_ID
if bash "$SCRIPT" --context-window 0 >/dev/null 2>&1; then
    echo 'FAIL: zero window must fail' >&2; exit 1
fi
output=$(bash "$SCRIPT")
[[ "$output" == *'agent: codex'* && "$output" == *'session_id: codex-session'* && "$output" == *'context_percent: 20%'* ]]
echo "$passed JSON cases and CLI error/text checks passed."

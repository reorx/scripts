#!/usr/bin/env bash
set -euo pipefail

# Read-only, on-demand inspection of local session transcripts.
# Claude formula: https://code.claude.com/docs/en/statusline#context-window-fields
# Codex window: https://developers.openai.com/codex/config-reference

usage() {
    cat <<'HELP'
Usage: agent-inspect-session.sh [--json] [--agent codex|claude]
                                [--context-window TOKENS]

Print agent, session_id, model, thinking_effort and context_percent (used).
Requires Bash and jq. Reads local JSONL transcripts only when invoked;
no statusline integration, persistent cache, background work or network requests.

Codex model and thinking_effort come from the latest turn_context record.
Claude model comes from the latest real response in the transcript.
Claude transcripts do not reliably record effort; report unknown.
Missing model/effort is unknown (JSON null); global defaults are not inferred.

Session detection:
  Codex:  CODEX_SESSION_ID, then CODEX_THREAD_ID
  Claude: CLAUDE_CODE_SESSION_ID
  If both agents are detected, select one with --agent.

Data directories: CODEX_HOME (default ~/.codex) and CLAUDE_CONFIG_DIR
(default ~/.claude). Only the matching session transcript is inspected.

Codex matches its native status line: subtract the fixed 12000-token baseline
from usage and window, round remaining percent, then subtract it from 100.
JSON raw_context_percent preserves the unadjusted token/window ratio.
Source: github.com/openai/codex/blob/main/codex-rs/tui/src/token_usage.rs

Claude uses the latest input_tokens + cache_creation_input_tokens +
cache_read_input_tokens, excluding output tokens, as its status line does.
Claude window priority: --context-window, recorded session window, explicit
[1m] model marker, 200k default for recognized older Claude models.
Model defaults are estimates: extended-context/provider overrides may differ.
Use --context-window to supply the effective window for those configurations
or for an unrecognized model. JSON includes context_source for this reason.

Percent is rounded to the nearest integer, clamped to 0..100. It reflects
the last recorded response, not pending tool results or the live /context
estimate. Raw JSON percent is not clamped; native percent is clamped to 0..100.
Missing usage/window is unknown (JSON null), never a fabricated zero.
If percent is unknown, assess the latest recorded tokens (threshold: 100000),
then approximate UTF-8 message/tool text bytes since compaction (400000 bytes).
These are conservative heuristics, not model limits or byte-to-token conversion.
Byte estimates exclude metadata, images and sidechains, but cannot reconstruct
the exact active branch, hidden prompts or tool-result pruning. They may differ
from live context. Known tokens always take precedence, including zero.
JSON includes context_bytes, assessment_basis, context_high, warning_threshold
and guidance. context_high is null when percent is known or evidence is absent;
false only means below the fallback threshold, not proven safe. Guidance advises
agents to treat high fallback readings as excessive context and consider a new
session. No usable evidence means unknown, not zero.
Missing session ID, ambiguous agents and invalid arguments exit nonzero.
HELP
}

find_transcript() {
    local root=$1 pattern=$2 file
    [[ -d "$root" ]] || return 0
    # Session IDs are validated before becoming a find pattern. Newer resumed
    # rollouts win if an installation has more than one file for the same ID.
    while IFS= read -r -d '' file; do
        if [[ -z "$transcript" || "$file" -nt "$transcript" ]]; then
            transcript=$file
        fi
    done < <(find "$root" -type f -name "$pattern" -print0)
}

print_result() {
    if "$json"; then
        printf '%s\n' "$result"
    else
        jq -r '
            "agent: \(.agent)\nsession_id: \(.session_id)\nmodel: \(.model // "unknown")\nthinking_effort: \(.thinking_effort // "unknown")\ncontext_percent: \(if .context_percent == null then "unknown" elif .context_source == "model-default" then "~\(.context_percent)%" else "\(.context_percent)%" end)",
            "context_tokens: \(.context_tokens // "unknown")",
            "context_window: \(.context_window // "unknown")",
            (if .assessment_basis == "bytes" then "context_bytes (approximate UTF-8): \(.context_bytes)" else empty end),
            (if .guidance != null then "guidance: \(.guidance)" else empty end)
        ' <<< "$result"
    fi
}

main() {
    local agent='' session_id='' window='' json=false transcript='' result
    local codex_id=${CODEX_SESSION_ID:-${CODEX_THREAD_ID:-}}
    local claude_id=${CLAUDE_CODE_SESSION_ID:-}
    while (( $# )); do
        case "$1" in
            --help|-h) usage; return 0 ;;
            --json) json=true; shift ;;
            --agent|--context-window)
                if (( $# < 2 )); then
                    printf 'Missing value for %s\n' "$1" >&2; return 2
                fi
                if [[ "$1" == --agent ]]; then agent=$2; else window=$2; fi
                shift 2 ;;
            *) printf 'Unknown argument: %s\n' "$1" >&2; return 2 ;;
        esac
    done
    if [[ -n "$window" && ! "$window" =~ ^[1-9][0-9]*$ ]]; then
        echo '--context-window must be a positive integer.' >&2; return 2
    fi
    if ! command -v jq >/dev/null 2>&1; then
        echo 'jq is required (macOS: brew install jq).' >&2; return 1
    fi
    if [[ -z "$agent" ]]; then
        if [[ -n "$codex_id" && -n "$claude_id" ]]; then
            echo 'Both agents detected; use --agent codex|claude.' >&2; return 2
        elif [[ -n "$codex_id" ]]; then agent=codex
        elif [[ -n "$claude_id" ]]; then agent=claude
        else
            echo 'No session ID: set CODEX_SESSION_ID or CLAUDE_CODE_SESSION_ID.' >&2
            return 1
        fi
    fi
    case "$agent" in
        codex) session_id=$codex_id ;;
        claude) session_id=$claude_id ;;
        *) echo '--agent must be codex or claude.' >&2; return 2 ;;
    esac
    if [[ ! "$session_id" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        echo 'Session ID is missing or contains unsupported characters.' >&2; return 2
    fi
    if [[ "$agent" == codex ]]; then
        find_transcript "${CODEX_HOME:-$HOME/.codex}/sessions" "*-${session_id}.jsonl"
    else
        find_transcript "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects" "${session_id}.jsonl"
    fi

    # Parse line-by-line: bounded memory, tolerate a concurrently written final
    # JSON fragment. A malformed line must not discard the last valid reading.
    result=$(jq -Rn --arg agent "$agent" --arg id "$session_id" --arg override "$window" '
        def positive: type == "number" and . > 0;
        def nonnegative: type == "number" and . >= 0;
        # Select text-bearing fields explicitly: never count base64 images or
        # recursive metadata strings. Tool arguments are serialized JSON text.
        def text_bytes:
            if type == "string" then utf8bytelength
            elif type == "array" then map(text_bytes) | add
            elif type == "object" then
                if .type == "text" or .type == "input_text" or .type == "output_text" then .text | text_bytes
                elif .type == "thinking" then .thinking | text_bytes
                elif .type == "tool_use" then
                    if .input == null then null else .input | tojson | utf8bytelength end
                elif .type == "tool_result" or .type == "message" then .content | text_bytes
                elif .type == "function_call" then .arguments | text_bytes
                elif .type == "custom_tool_call" then .input | text_bytes
                elif .type == "function_call_output" or .type == "custom_tool_call_output" then .output | text_bytes
                else null end
            else null end;
        reduce inputs as $line ({};
            ($line | fromjson? // {}) as $e |
            if $agent == "codex" then
                if $e.type == "compacted" then
                    .bytes = (if ($e.replacement_history | type) == "array"
                        then $e.replacement_history | text_bytes
                        else $e.message | text_bytes end)
                elif $e.type == "response_item" then .bytes += ($e.payload | text_bytes)
                else . end
            else
                if $e.type == "system" and $e.subtype == "compact_boundary" then .bytes = null
                elif ($e.type == "user" or $e.type == "assistant")
                     and $e.isSidechain != true and $e.message.model != "<synthetic>"
                then .bytes += ($e.message.content | text_bytes)
                else . end
            end |
            if $agent == "codex" then
                if $e.type == "turn_context" then
                    .model = $e.payload.model | .thinking_effort = $e.payload.effort
                elif $e.type == "compacted" then .usage = null
                elif $e.type == "event_msg" and $e.payload.type == "token_count"
                     and $e.payload.info != null then
                    .usage = $e.payload.info.last_token_usage.total_tokens |
                    .window = $e.payload.info.model_context_window
                else . end
            else
                if $e.type == "system" and $e.subtype == "compact_boundary" then
                    .usage = null
                elif $e.type == "assistant" and $e.isSidechain != true
                     and $e.message.model != "<synthetic>" then
                    if ($e.message.usage.input_tokens | nonnegative) then
                        .usage = ($e.message.usage |
                        .input_tokens + (.cache_creation_input_tokens // 0)
                        + (.cache_read_input_tokens // 0))
                    else . end |
                    if $e.message.model != null then .model = $e.message.model else . end
                elif $e.type == "cost-state" then .models = $e.modelUsage
                else . end
            end
        ) |
        if $override != "" then
            .window = ($override | tonumber) | .source = "override"
        elif $agent == "codex" then .source = "session"
        else
            (.model // "") as $model |
            [(.models // {} | to_entries[]) |
                select((.key | sub("\\[1m\\]$"; "")) == $model)] as $matches |
            if (.models[$model].contextWindow | positive) then
                .window = .models[$model].contextWindow | .source = "session"
            elif ($matches | length) == 1 and ($matches[0].value.contextWindow | positive) then
                .window = $matches[0].value.contextWindow | .source = "session"
            elif (($model // "") | endswith("[1m]")) or
                 (($matches | length) == 1 and ($matches[0].key | endswith("[1m]"))) then
                .window = 1000000 | .source = "model-1m"
            elif (($model // "") | test("^claude-(3([.-]|$)|sonnet-4(-[0-9]{8})?$|opus-4(-[0-9]{8})?$|opus-4-1(-[0-9]{8})?$|sonnet-4-5(-[0-9]{8})?$|opus-4-5(-[0-9]{8})?$|haiku-4-5(-[0-9]{8})?$)")) then
                .window = 200000 | .source = "model-default"
            else .window = null | .source = "unknown" end
        end |
        {agent: $agent, session_id: $id, model: .model, thinking_effort: .thinking_effort,
         context_percent: (if (.usage | nonnegative) and (.window | positive)
             then if $agent == "codex" then
                 if .window <= 12000 then 100 else
                     (.window - 12000) as $effective |
                     ([0, (.usage - 12000)] | max) as $used |
                     100 - (([0, ($effective - $used)] | max) / $effective * 100 | round)
                 end
             else ([0, ([100, (.usage / .window * 100 | round)] | min)] | max) end
             else null end),
         raw_context_percent: (if (.usage | nonnegative) and (.window | positive)
             then (.usage / .window * 100 | round) else null end),
         context_tokens: (if (.usage | nonnegative) then .usage else null end),
         context_bytes: .bytes, context_window: .window,
         context_source: .source} |
        if .context_percent != null then
            . + {assessment_basis:"percent",context_high:null,warning_threshold:null,guidance:null}
        else
            (if .context_tokens != null then
                {basis:"tokens",value:.context_tokens,threshold:100000}
             elif .context_bytes != null then
                {basis:"bytes",value:.context_bytes,threshold:400000}
             else {basis:"unavailable",value:null,threshold:null} end) as $fallback |
            .assessment_basis = $fallback.basis |
            .warning_threshold = $fallback.threshold |
            .context_high = (if $fallback.value == null then null
                             else $fallback.value >= $fallback.threshold end) |
            .guidance = ("context is unknown; " +
                if $fallback.value == null then
                    "no usable token or text-byte data; cannot assess context pressure. Do not assume low usage; consider a new session if this conversation is long."
                else
                    (if $fallback.basis == "tokens" then "latest recorded usage: \($fallback.value) tokens"
                     else "approximately \($fallback.value) UTF-8 text bytes; token usage is unknown" end) +
                    "; heuristic threshold: \($fallback.threshold) \($fallback.basis). " +
                    (if .context_high then
                        "Treat this as potentially excessive context. Summarize the current work and consider starting a new session before continuing substantial work."
                     else "Below the heuristic threshold; this does not prove low context usage. Recheck before substantial work." end)
                end)
        end
    ' "${transcript:-/dev/null}")
    print_result
}

main "$@"

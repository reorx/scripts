#!/usr/bin/env bash
set -euo pipefail

# Read-only inspection: no agent/API invocation and no changes to agent settings.
# Claude formula: https://code.claude.com/docs/en/statusline#context-window-fields
# Codex window: https://developers.openai.com/codex/config-reference

usage() {
    cat <<'HELP'
Usage: agent-inspect-session.sh [--json] [--agent codex|claude]
                                [--context-window TOKENS]

Print agent, session_id and context_percent (used, not remaining).
Requires Bash and jq. Reads local JSONL transcripts; makes no network requests.

Session detection:
  Codex:  CODEX_SESSION_ID, then CODEX_THREAD_ID
  Claude: CLAUDE_CODE_SESSION_ID
  If both agents are detected, select one with --agent.

Data directories: CODEX_HOME (default ~/.codex) and CLAUDE_CONFIG_DIR
(default ~/.claude). Only the matching session transcript is inspected.

Codex uses the latest last_token_usage.total_tokens / model_context_window.
Claude uses the latest input_tokens + cache_creation_input_tokens +
cache_read_input_tokens, excluding output tokens, as its status line does.
Claude window priority: --context-window, recorded session window, explicit
[1m] model marker, 200k default for recognized older Claude models.
Model defaults are estimates: extended-context/provider overrides may differ.
Use --context-window to supply the effective window for those configurations
or for an unrecognized model. JSON includes context_source for this reason.

Percent is rounded to the nearest integer, clamped to 0..100. It reflects
the last recorded response, not pending tool results or the live /context
estimate. Codex UI accounting may subtract reserved tokens and differ.
Missing usage/window is unknown (JSON null), never a fabricated zero.
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
    if ! command -v jq >/dev/null 2>&1; then
        echo 'jq is required (macOS: brew install jq).' >&2; return 1
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
        reduce inputs as $line ({};
            ($line | fromjson? // {}) as $e |
            if $agent == "codex" then
                if $e.type == "compacted" then .usage = null
                elif $e.type == "event_msg" and $e.payload.type == "token_count"
                     and $e.payload.info != null then
                    .usage = $e.payload.info.last_token_usage.total_tokens |
                    .window = $e.payload.info.model_context_window
                else . end
            else
                if $e.type == "system" and $e.subtype == "compact_boundary" then
                    .usage = null
                elif $e.type == "assistant" and $e.isSidechain != true
                     and ($e.message.usage.input_tokens | nonnegative)
                     and $e.message.model != "<synthetic>" then
                    .usage = ($e.message.usage |
                        .input_tokens + (.cache_creation_input_tokens // 0)
                        + (.cache_read_input_tokens // 0)) |
                    .model = $e.message.model
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
        {agent: $agent, session_id: $id,
         context_percent: (if (.usage | nonnegative) and (.window | positive)
             then ([0, ([100, (.usage / .window * 100 | round)] | min)] | max)
             else null end),
         context_tokens: .usage, context_window: .window,
         context_source: .source}
    ' "${transcript:-/dev/null}")
    if [[ $(jq -r '.context_percent' <<< "$result") == null ]]; then
        echo 'Context unavailable: transcript, usage or window size missing; see --help.' >&2
    fi
    if "$json"; then
        printf '%s\n' "$result"
    else
        jq -r '"agent: \(.agent)\nsession_id: \(.session_id)\ncontext_percent: \(if .context_percent == null then "unknown" elif .context_source == "model-default" then "~\(.context_percent)%" else "\(.context_percent)%" end)"' <<< "$result"
    fi
}

main "$@"

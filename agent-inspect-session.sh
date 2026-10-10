#!/usr/bin/env bash
set -euo pipefail

# Inspection is read-only; --cache-statusline stores Claude callback metrics.
# Claude formula: https://code.claude.com/docs/en/statusline#context-window-fields
# Codex window: https://developers.openai.com/codex/config-reference

usage() {
    cat <<'HELP'
Usage: agent-inspect-session.sh [--json] [--agent codex|claude]
                                [--context-window TOKENS]
       agent-inspect-session.sh --cache-statusline < statusline.json

Print agent, session_id, model, thinking_effort and context_percent (used).
Requires Bash and jq. Reads local JSONL transcripts; makes no network requests.

Codex model and thinking_effort come from the latest turn_context record.
Claude model comes from statusline model.id or the latest real response.
Claude transcripts/statusline do not reliably record effort; report unknown.
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

Claude prefers official statusline data cached by --cache-statusline. This
mode reads stdin JSON, caches only session/model/context metrics atomically under
${XDG_CACHE_HOME:-~/Library/Caches}/agent-inspect-session/<session_id>.json,
outside CLAUDE_CONFIG_DIR (which may be synced by iCloud), and forwards the
original JSON to stdout. Chain it before an existing statusline command:
  /absolute/path/agent-inspect-session.sh --cache-statusline | existing-command
It uses the callback session_id, not inherited agent environment variables.
JSON includes updated_at and cache_age_seconds; cached readings may lag the
live session. No cache means transcript fallback as described below.

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
        jq -r '"agent: \(.agent)\nsession_id: \(.session_id)\nmodel: \(.model // "unknown")\nthinking_effort: \(.thinking_effort // "unknown")\ncontext_percent: \(if .context_percent == null then "unknown" elif .context_source == "model-default" then "~\(.context_percent)%" else "\(.context_percent)%" end)"' <<< "$result"
    fi
}

main() {
    local agent='' session_id='' window='' json=false transcript='' result
    local cache_mode=false payload cache_file temporary cached
    # Statusline callbacks refresh even when token usage is unchanged. Keep their
    # heartbeat timestamps local; ~/.claude may be a symlink into iCloud Drive.
    local cache_dir="${XDG_CACHE_HOME:-$HOME/Library/Caches}/agent-inspect-session"
    local codex_id=${CODEX_SESSION_ID:-${CODEX_THREAD_ID:-}}
    local claude_id=${CLAUDE_CODE_SESSION_ID:-}
    while (( $# )); do
        case "$1" in
            --help|-h) usage; return 0 ;;
            --json) json=true; shift ;;
            --cache-statusline) cache_mode=true; shift ;;
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
    if "$cache_mode"; then
        if [[ -n "$agent" || -n "$window" || "$json" == true ]]; then
            echo '--cache-statusline cannot be combined with query options.' >&2; return 2
        fi
        payload=$(cat)
        # Forward even invalid callback data so an existing renderer still sees it.
        printf '%s' "$payload"
        cached=$(jq -ce '
            select(.session_id | type == "string" and test("^[a-zA-Z0-9_-]+$")) |
            select(.context_window | type == "object") |
            select(.context_window.used_percentage == null or
                (.context_window.used_percentage | type == "number" and . >= 0 and . <= 100)) |
            {agent:"claude",session_id,model:(.model.id // null),context_window,updated_at:(now | floor)}
        ' <<< "$payload") || { echo 'Invalid Claude statusline data.' >&2; return 1; }
        session_id=$(jq -r '.session_id' <<< "$cached")
        mkdir -p "$cache_dir"
        temporary=$(mktemp "$cache_dir/.${session_id}.XXXXXX")
        if ! printf '%s\n' "$cached" > "$temporary" ||
           ! mv -f "$temporary" "$cache_dir/$session_id.json"; then
            rm -f "$temporary"
            echo 'Could not write Claude statusline cache.' >&2; return 1
        fi
        return 0
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
    cache_file="$cache_dir/$session_id.json"
    if [[ "$agent" == claude && -f "$cache_file" ]]; then
        if result=$(jq -ce --arg id "$session_id" --arg override "$window" '
            select(.agent == "claude" and .session_id == $id) |
            select(.updated_at | type == "number") |
            select(.context_window | type == "object") |
            select(.context_window.used_percentage == null or
                (.context_window.used_percentage | type == "number" and . >= 0 and . <= 100)) |
            .context_window as $c |
            (if $c.current_usage == null then null else ($c.current_usage |
                .input_tokens + (.cache_creation_input_tokens // 0) +
                (.cache_read_input_tokens // 0)) end) as $tokens |
            (if $override == "" then $c.context_window_size else ($override | tonumber) end) as $window |
            (if ($tokens | type == "number") and ($window | type == "number" and . > 0)
                then ($tokens / $window * 100 | round) else null end) as $raw |
            {agent,session_id,model,thinking_effort:null,updated_at,
             cache_age_seconds:([0,(now - .updated_at | floor)] | max),
             context_tokens:$tokens,context_window:$window,raw_context_percent:$raw,
             context_source:(if $override == "" then "statusline" else "override" end),
             context_percent:(if $override == "" then $c.used_percentage
                 elif $raw == null then null else ([0,([100,$raw] | min)] | max) end)}
        ' "$cache_file" 2>/dev/null); then
            print_result
            return 0
        fi
        echo 'Invalid statusline cache; falling back to transcript.' >&2
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
         context_tokens: .usage, context_window: .window,
         context_source: .source}
    ' "${transcript:-/dev/null}")
    if [[ $(jq -r '.context_percent' <<< "$result") == null ]]; then
        echo 'Context unavailable: transcript, usage or window size missing; see --help.' >&2
    fi
    print_result
}

main "$@"

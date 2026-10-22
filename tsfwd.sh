#!/bin/bash
# tsfwd - forward TCP ports on the tailnet to localhost via tailscale serve
#
# GOTCHA: once a port is forwarded, tailscaled itself listens on
# <tailscale-ip>:<port> (e.g. 100.x.y.z:5180). A local server that then binds
# the wildcard address (Node's default `::`/0.0.0.0) will fail listen() with
# EADDRINUSE on macOS — and some stacks swallow it: Express fires the listen
# callback anyway and the process exits 0 silently right after "listening".
# The tailscaled listener is invisible to lsof; use `netstat -anv | grep <port>`
# (shows io.tailscale.ipn). Fix: make the local server bind 127.0.0.1 — the
# forward targets localhost anyway, so tailnet access keeps working.
#
# $TAILSCALE overrides the tailscale CLI path (test-tsfwd.sh points it at a stub).
set -euo pipefail

TS=${TAILSCALE:-/Applications/Tailscale.app/Contents/MacOS/Tailscale}
[[ -x $TS ]] || TS=$(command -v tailscale) || { echo "error: tailscale CLI not found" >&2; exit 1; }

if [[ -t 1 ]]; then
    BOLD=$'\e[1m' GREEN=$'\e[32m' CYAN=$'\e[36m' YELLOW=$'\e[33m' DIM=$'\e[2m' RESET=$'\e[0m'
else
    BOLD='' GREEN='' CYAN='' YELLOW='' DIM='' RESET=''
fi

usage() {
    cat <<EOF
${BOLD}tsfwd${RESET} - forward TCP ports on the tailnet to localhost via tailscale serve

${BOLD}Usage:${RESET}
  tsfwd <port> [target]   forward tailnet :<port> to localhost:<target> (default: same port)
  tsfwd -l, --list        list active serve forwards, marking targets with nothing listening
  tsfwd -d, --del <port>  stop forwarding <port>
  tsfwd -p, --prune       stop every TCP forward whose target has nothing listening
  tsfwd -h, --help        show this help
EOF
}

die() { echo "${YELLOW}error:${RESET} $*" >&2; exit 1; }

check_port() {
    [[ $1 =~ ^[0-9]+$ ]] && (( $1 >= 1 && $1 <= 65535 )) || die "invalid port: $1"
}

ts_hostname() {
    "$TS" status --json | jq -r '.Self.DNSName | rtrimstr(".")'
}

serve_json() {
    local json
    json=$("$TS" serve status --json 2>/dev/null) || die "tailscale is not running"
    echo "${json:-"{}"}"
}

# TCP forwards as "<port>\t<host:port>" lines, by port number; skips TLS-terminated entries
tcp_forwards() {
    jq -r '.TCP // {} | to_entries | sort_by(.key | tonumber)[]
        | select(.value.TCPForward) | [.key, .value.TCPForward] | @tsv'
}

# true if something accepts connections on <host:port>; stdin is closed so nc can't eat a caller's loop input
target_alive() {
    local host=${1%:*} port=${1##*:}
    host=${host#\[} host=${host%\]}
    nc -z -w 1 "$host" "$port" </dev/null 2>/dev/null
}

cmd_list() {
    local json host dead=0 proto from to scope target state
    json=$(serve_json)
    host=$(ts_hostname)

    if [[ $(jq '(.TCP // {} | length) + (.Web // {} | length)' <<<"$json") -eq 0 ]]; then
        echo "${DIM}no active serve forwards on ${host}${RESET}"
        return
    fi

    echo "${BOLD}serve forwards on ${CYAN}${host}${RESET}"
    while IFS=$'\t' read -r proto from to scope target; do
        state=''
        if [[ $target != - ]]; then
            if target_alive "$target"; then
                state="${GREEN}live${RESET}"
            else
                state="${YELLOW}dead${RESET}"
                dead=$((dead + 1))
            fi
        fi
        printf "  %s%-5s%s %s%-45s%s ${DIM}->${RESET} %-25s %-20s %s\n" \
            "$GREEN" "$proto" "$RESET" "$CYAN" "$from" "$RESET" "$to" "${DIM}(${scope})${RESET}" "$state"
    done < <(jq -r --arg host "$host" '
        [ (.AllowFunnel // {} | keys[]) ] as $funnel |
        (.TCP // {} | to_entries | sort_by(.key | tonumber)[] | .key as $port | .value as $v |
            [ "tcp",
              "tcp://\($host):\($port)",
              ($v.TCPForward // "tls-terminated :\($port)"),
              (if $funnel | index("\($host):\($port)") then "funnel" else "tailnet" end),
              ($v.TCPForward // "-")
            ] | @tsv),
        (.Web // {} | to_entries[] | .key as $hp | .value.Handlers | to_entries[] | .key as $path | .value as $h |
            [ "web",
              "https://\($hp | sub(":443$"; ""))\($path)",
              ($h.Proxy // $h.Path // "text"),
              (if $funnel | index($hp) then "funnel" else "tailnet" end),
              "-"
            ] | @tsv)
    ' <<<"$json")

    if ((dead)); then
        echo
        echo "${YELLOW}${dead} forward(s) with nothing listening${RESET} ${DIM}— remove them with: tsfwd -p${RESET}"
    fi
}

cmd_del() {
    local json
    check_port "$1"
    json=$(serve_json)
    jq -e --arg p "$1" '.TCP[$p]' <<<"$json" >/dev/null || die "port $1 is not forwarded"
    "$TS" serve --tcp "$1" off
    echo "${GREEN}✓${RESET} stopped forwarding port ${BOLD}$1${RESET}"
}

cmd_prune() {
    local json port target entry dead=()
    json=$(serve_json)

    # probe every target before removing anything, so removal never races the probes
    while IFS=$'\t' read -r port target; do
        target_alive "$target" || dead+=("$port"$'\t'"$target")
    done < <(tcp_forwards <<<"$json")

    if [[ ${#dead[@]} -eq 0 ]]; then
        echo "${DIM}nothing to prune: every TCP forward has a listener${RESET}"
        return
    fi

    for entry in "${dead[@]}"; do
        port=${entry%%$'\t'*} target=${entry#*$'\t'}
        "$TS" serve --tcp "$port" off
        echo "${GREEN}✓${RESET} stopped forwarding port ${BOLD}${port}${RESET} ${DIM}(nothing listening on ${target})${RESET}"
    done
}

cmd_fwd() {
    local port=$1 target=${2:-$1} host
    check_port "$port"
    check_port "$target"

    if ! target_alive "localhost:${target}"; then
        echo "${YELLOW}warning:${RESET} nothing is listening on localhost:${target} yet" >&2
    fi

    "$TS" serve --bg --tcp "$port" "tcp://localhost:${target}" >/dev/null
    host=$(ts_hostname)
    echo "${GREEN}✓${RESET} forwarding ${CYAN}tcp://${host}:${port}${RESET} ${DIM}->${RESET} localhost:${target}"
}

case ${1:-} in
    -h|--help|'') usage ;;
    -l|--list)    cmd_list ;;
    -d|--del)     [[ -n ${2:-} ]] || die "-d requires a port"; cmd_del "$2" ;;
    -p|--prune)   cmd_prune ;;
    -*)           die "unknown option: $1" ;;
    *)            cmd_fwd "$1" "${2:-}" ;;
esac

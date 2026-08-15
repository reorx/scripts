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
set -euo pipefail

TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
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
  tsfwd -l, --list        list active serve forwards
  tsfwd -d, --del <port>  stop forwarding <port>
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

cmd_list() {
    local json host
    json=$("$TS" serve status --json 2>/dev/null) || die "tailscale is not running"
    host=$(ts_hostname)

    if [[ -z $json ]] || [[ $(jq '(.TCP // {} | length) + (.Web // {} | length)' <<<"$json") -eq 0 ]]; then
        echo "${DIM}no active serve forwards on ${host}${RESET}"
        return
    fi

    echo "${BOLD}serve forwards on ${CYAN}${host}${RESET}"
    jq -r --arg host "$host" '
        [ (.AllowFunnel // {} | keys[]) ] as $funnel |
        (.TCP // {} | to_entries[] | .key as $port | .value as $v |
            [ "tcp",
              "tcp://\($host):\($port)",
              ($v.TCPForward // "tls-terminated :\($port)"),
              (if $funnel | index("\($host):\($port)") then "funnel" else "tailnet" end)
            ] | @tsv),
        (.Web // {} | to_entries[] | .key as $hp | .value.Handlers | to_entries[] | .key as $path | .value as $h |
            [ "web",
              "https://\($hp | sub(":443$"; ""))\($path)",
              ($h.Proxy // $h.Path // "text"),
              (if $funnel | index($hp) then "funnel" else "tailnet" end)
            ] | @tsv)
    ' <<<"$json" | while IFS=$'\t' read -r proto from to scope; do
        printf "  %s%-5s%s %s%-45s%s ${DIM}->${RESET} %-25s %s\n" \
            "$GREEN" "$proto" "$RESET" "$CYAN" "$from" "$RESET" "$to" "${DIM}(${scope})${RESET}"
    done
}

cmd_del() {
    check_port "$1"
    "$TS" serve --tcp "$1" off
    echo "${GREEN}✓${RESET} stopped forwarding port ${BOLD}$1${RESET}"
}

cmd_fwd() {
    local port=$1 target=${2:-$1} host
    check_port "$port"
    check_port "$target"

    if ! nc -z -w 1 localhost "$target" 2>/dev/null; then
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
    -*)           die "unknown option: $1" ;;
    *)            cmd_fwd "$1" "${2:-}" ;;
esac

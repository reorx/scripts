#!/usr/bin/env bash
# Behavior tests for tsfwd.sh against a stub tailscale CLI.
#
# The stub keeps `tailscale serve` state in a JSON file and logs every call, so the
# real tailnet config is never touched. Liveness is real: live targets have a
# 127.0.0.1 listener, dead ones point at ports nothing listens on.
set -uo pipefail

TSFWD=$(cd "$(dirname "$0")" && pwd)/tsfwd.sh
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tsfwd-test.XXXXXX")
STATE=$WORK/serve.json
CALLS=$WORK/calls.log
LISTENERS=()
FAILED=0

cleanup() {
    [[ ${#LISTENERS[@]} -gt 0 ]] && kill "${LISTENERS[@]}" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

cat >"$WORK/tailscale" <<'EOF'
#!/bin/bash
set -euo pipefail
state=$TSFWD_STUB_DIR/serve.json
echo "$*" >>"$TSFWD_STUB_DIR/calls.log"
update() { jq "$@" "$state" >"$state.tmp" && mv "$state.tmp" "$state"; }
case "$*" in
    "status --json")
        echo '{"Self":{"DNSName":"box.example.ts.net."}}' ;;
    "serve status --json")
        cat "$state" ;;
    "serve --tcp "*" off")
        jq -e --arg p "$3" '.TCP[$p]' "$state" >/dev/null \
            || { echo "error: failed to remove TCP serve: serve config does not exist" >&2; exit 1; }
        update --arg p "$3" 'del(.TCP[$p])' ;;
    "serve --bg --tcp "*)
        update --arg p "$4" --arg t "${5#tcp://}" '.TCP[$p] = {TCPForward: $t}' ;;
    *)
        echo "stub: unexpected args: $*" >&2; exit 2 ;;
esac
EOF
chmod +x "$WORK/tailscale"
export TAILSCALE=$WORK/tailscale TSFWD_STUB_DIR=$WORK

listen() { # listen -> sets PORT to a port with a live 127.0.0.1 listener
    local ready=$WORK/ready.$RANDOM
    python3 - "$ready" >/dev/null 2>&1 <<'EOF' &
import socket, sys, time
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen()
open(sys.argv[1], "w").write(str(s.getsockname()[1]))
time.sleep(300)
EOF
    LISTENERS+=($!)
    disown $!
    while [[ ! -s $ready ]]; do sleep 0.05; done
    PORT=$(<"$ready")
}

free_port() { # a port nothing listens on
    python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

set_state() { printf '%s\n' "$1" >"$STATE"; : >"$CALLS"; }
run() { OUT=$("$TSFWD" "$@" 2>&1); CODE=$?; }

pass() { echo "  ✅ $1"; }
fail() {
    echo "  ❌ $1"
    [[ -n ${2:-} ]] && sed 's/^/       /' <<<"$2"
    FAILED=$((FAILED + 1))
}
expect_code() { [[ $CODE == "$2" ]] && pass "$1 (exit $CODE)" || fail "$1 — want exit $2, got $CODE" "$OUT"; }
expect_out() { grep -q -- "$2" <<<"$OUT" && pass "$1" || fail "$1 — expected /$2/ in output:" "$OUT"; }
expect_ports() { # expect_ports <label> <TCP ports in numeric order>
    local got
    got=$(jq -r '.TCP // {} | keys | sort_by(tonumber) | join(" ")' "$STATE")
    [[ $got == "$2" ]] && pass "$1" || fail "$1 — want TCP ports [$2], got [$got]"
}
expect_no_off() { # expect_no_off <label> [port]
    grep -q -- "--tcp ${2:-[0-9]*} off" "$CALLS" && fail "$1" "$(cat "$CALLS")" || pass "$1"
}

listen; LIVE=$PORT
DEAD=$(free_port)

echo "prune removes forwards whose target has nothing listening"
set_state "$(jq -n --arg live "$LIVE" --arg dead "$DEAD" '{
    TCP: {
        ($live): {TCPForward: "localhost:\($live)"},
        ($dead): {TCPForward: "localhost:\($dead)"},
        "18080": {TCPForward: "localhost:\($live)"},
        "18081": {TCPForward: "127.0.0.1:\($dead)"},
        "443": {HTTPS: true}
    },
    Web: {"box.example.ts.net:443": {Handlers: {"/": {Proxy: "http://127.0.0.1:\($dead)"}}}}
}')"
web_before=$(jq -c .Web "$STATE")
run -p
expect_code "succeeds" 0
expect_ports "keeps live forwards and the HTTPS entry" "443 18080 $LIVE"
expect_out "reports the dead same-port forward" "port $DEAD"
expect_out "reports the remapped dead forward" "port 18081"
[[ $(jq -c .Web "$STATE") == "$web_before" ]] && pass "leaves web handlers alone" || fail "leaves web handlers alone"
expect_no_off "never turns off a live forward" "$LIVE"

echo
echo "prune with every target alive changes nothing"
set_state "$(jq -n --arg live "$LIVE" '{TCP: {($live): {TCPForward: "localhost:\($live)"}}}')"
run --prune
expect_code "succeeds" 0
expect_out "says there is nothing to prune" "nothing to prune"
expect_ports "keeps the forward" "$LIVE"
expect_no_off "issues no off calls"

echo
echo "prune with no serve config at all"
set_state '{}'
run -p
expect_code "succeeds" 0
expect_out "says there is nothing to prune" "nothing to prune"

echo
echo "list sorts ports numerically and marks dead targets"
set_state "$(jq -n --arg live "$LIVE" --arg dead "$DEAD" '{TCP: {
    "10000": {TCPForward: "localhost:\($live)"},
    "9000": {TCPForward: "localhost:\($dead)"}
}}')"
run -l
expect_code "succeeds" 0
order=$(grep -o 'ts\.net:[0-9]*' <<<"$OUT" | cut -d: -f2 | xargs)
[[ $order == "9000 10000" ]] && pass "9000 comes before 10000" || fail "9000 comes before 10000 — got [$order]" "$OUT"
grep 'ts\.net:9000 ' <<<"$OUT" | grep -q dead && pass "marks 9000 dead" || fail "marks 9000 dead" "$OUT"
grep 'ts\.net:10000 ' <<<"$OUT" | grep -q live && pass "marks 10000 live" || fail "marks 10000 live" "$OUT"
expect_out "points at prune" "tsfwd -p"

echo
echo "del refuses a port that is not forwarded"
set_state '{"TCP": {"9000": {"TCPForward": "localhost:9000"}}}'
run -d 9001
expect_code "fails" 1
expect_out "says the port is not forwarded" "not forwarded"
expect_no_off "issues no off call"

echo
echo "del removes a forwarded port"
run -d 9000
expect_code "succeeds" 0
expect_ports "the forward is gone" ""

echo
echo "forward adds a TCP forward"
set_state '{}'
run "$DEAD"
expect_code "succeeds" 0
expect_out "warns that nothing listens yet" "nothing is listening"
expect_ports "the forward exists" "$DEAD"

echo
if ((FAILED)); then
    echo "❌ $FAILED check(s) failed"
    exit 1
fi
echo "✅ all checks passed"

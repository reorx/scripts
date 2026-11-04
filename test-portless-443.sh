#!/bin/bash
# Checks portless-443.sh without root and without touching launchd: argument handling,
# the sudo guard, and the plist it would install.
set -euo pipefail

script="$(cd "$(dirname "$0")" && pwd)/portless-443.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
failures=0

check() {
  local name=$1; shift
  if "$@"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

plist_value() { plutil -extract "$1" raw -o - "$tmp/out.plist"; }

# usage
set +e
"$script" >/dev/null 2>&1; usage_code=$?
"$script" install >/dev/null 2>"$tmp/install.err"; install_code=$?
"$script" uninstall >/dev/null 2>"$tmp/uninstall.err"; uninstall_code=$?
set -e
check "no argument exits 64" [ "$usage_code" = 64 ]
if [ "$(id -u)" != 0 ]; then
  check "install refuses without sudo" [ "$install_code" = 1 ]
  check "install says to use sudo" grep -q 'run with sudo' "$tmp/install.err"
  check "uninstall refuses without sudo" [ "$uninstall_code" = 1 ]
fi

# plist
"$script" plist >"$tmp/out.plist"
check "plist lints" plutil -lint -s "$tmp/out.plist"
check "label" [ "$(plist_value Label)" = local.portless.proxy-443 ]
check "runs portless on 443 with https in the foreground" \
  [ "$(plist_value ProgramArguments.1) $(plist_value ProgramArguments.2) $(plist_value ProgramArguments.3) $(plist_value ProgramArguments.5)" = "proxy start --foreground 443" ]
check "HOME is the user's home" [ "$(plist_value EnvironmentVariables.HOME)" = "$HOME" ]
check "SUDO_USER is the user" [ "$(plist_value EnvironmentVariables.SUDO_USER)" = "$(id -un)" ]
check "SUDO_UID is the user's uid" [ "$(plist_value EnvironmentVariables.SUDO_UID)" = "$(id -u)" ]
check "SUDO_GID is the user's gid" [ "$(plist_value EnvironmentVariables.SUDO_GID)" = "$(id -g)" ]
check "starts at boot and stays up" [ "$(plist_value RunAtLoad) $(plist_value KeepAlive)" = "true true" ]
PORTLESS=/somewhere/portless "$script" plist >"$tmp/out.plist"
check "PORTLESS overrides the binary" [ "$(plist_value ProgramArguments.0)" = /somewhere/portless ]

# install, end to end, against fakes first in PATH: `id -u` says root, launchctl/install/lsof/ps/curl
# only record what they are asked. The hand-started proxy is a real `sleep` that `kill` must end;
# it is started from a subshell so it is reparented and never lingers as a zombie.
fakes="$tmp/fakes"
state="$tmp/state"
mkdir -p "$fakes" "$state"
cat >"$fakes/id" <<'EOF'
#!/bin/bash
if [ "$#" = 1 ] && [ "$1" = -u ]; then echo 0; else exec /usr/bin/id "$@"; fi
EOF
cat >"$fakes/install" <<'EOF'
#!/bin/bash
echo "install $*" >>"$STATE/calls"
cp "$7" "$STATE/installed.plist"  # install -o root -g wheel -m 644 SRC DEST
EOF
cat >"$fakes/launchctl" <<'EOF'
#!/bin/bash
echo "launchctl $*" >>"$STATE/calls"
case "$1" in
  print) [ -e "$STATE/bootstrapped" ] && echo "	state = running" && exit 0; exit 113 ;;
  bootstrap) touch "$STATE/bootstrapped" ;;
esac
EOF
cat >"$fakes/lsof" <<'EOF'
#!/bin/bash
if [ -e "$STATE/bootstrapped" ]; then echo 99999
elif kill -0 "$(cat "$STATE/manual.pid")" 2>/dev/null; then cat "$STATE/manual.pid"; fi
EOF
cat >"$fakes/ps" <<'EOF'
#!/bin/bash
echo "${FAKE_HOLDER:-/opt/homebrew/bin/node /x/portless/dist/cli.js proxy start --foreground --port 443 --https}"
EOF
cat >"$fakes/curl" <<'EOF'
#!/bin/bash
echo "x-portless: 1"
EOF
chmod +x "$fakes"/*

# Runs `portless-443.sh install` with the fakes; a watchdog kills it after 20 s so a hang fails.
run_install() {
  rm -f "$state"/*
  (sleep 300 & echo $! >"$state/manual.pid")
  PATH="$fakes:$PATH" STATE="$state" SUDO_USER="$(id -un)" PORTLESS=/usr/bin/true "$@" \
    "$script" install >"$tmp/run.out" 2>&1 &
  local pid=$! waited=0
  while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt 40 ]; do sleep 0.5; waited=$((waited + 1)); done
  if kill -0 "$pid" 2>/dev/null; then
    pkill -P "$pid" 2>/dev/null || true; kill "$pid" 2>/dev/null || true
    echo hung >"$state/result"
  else
    wait "$pid" && echo 0 >"$state/result" || echo $? >"$state/result"
  fi
  kill "$(cat "$state/manual.pid")" 2>/dev/null || true
}

run_install env
check "install finishes" [ "$(cat "$state/result")" = 0 ]
check "install copies the plist into LaunchDaemons" \
  grep -q "^install -o root -g wheel -m 644 .* /Library/LaunchDaemons/local.portless.proxy-443.plist$" "$state/calls"
check "the installed plist lints" plutil -lint -s "$state/installed.plist"
check "install stops the hand-started proxy" grep -q '^stopping hand-started proxy' "$tmp/run.out"
check "install loads the daemon" \
  grep -q '^launchctl bootstrap system /Library/LaunchDaemons/local.portless.proxy-443.plist$' "$state/calls"
check "install copies the plist before loading it" \
  [ "$(grep -n '^install ' "$state/calls" | cut -d: -f1)" -lt "$(grep -n 'bootstrap' "$state/calls" | cut -d: -f1)" ]
check "install reports Portless on 443" grep -q '^443: Portless answers' "$tmp/run.out"

run_install env FAKE_HOLDER="/usr/sbin/httpd -D FOREGROUND"
check "install refuses when something else holds 443" [ "$(cat "$state/result")" = 1 ]
check "and says what holds it" grep -q 'held by something other than Portless' "$tmp/run.out"
check "and neither writes the plist nor loads the daemon" bash -c "! grep -sqE '^(install|launchctl bootstrap)' '$state/calls'"

[ "$failures" = 0 ] && echo "all passed" || { echo "$failures failed"; exit 1; }

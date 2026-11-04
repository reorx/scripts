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

[ "$failures" = 0 ] && echo "all passed" || { echo "$failures failed"; exit 1; }

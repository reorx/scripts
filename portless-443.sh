#!/bin/bash
# Keeps the machine-wide Portless HTTPS proxy on port 443 running as a LaunchDaemon, so every
# Portless route (https://<name>.localhost) works without a port number and comes back after a
# reboot. A proxy on another port (e.g. 1355, no sudo needed) can keep running beside it.
#
#   sudo portless-443.sh install     # write the plist, replace a hand-started 443 proxy, load it
#   sudo portless-443.sh uninstall   # unload and remove the plist
#   portless-443.sh status           # launchd state and whether 443 answers as Portless
#   portless-443.sh plist            # print the plist install would write (no root needed)
#
# After upgrading Portless: sudo launchctl kickstart -k system/local.portless.proxy-443
#
# The daemon runs as root but must behave like `sudo portless proxy start --port 443`:
# Portless finds the user's ~/.portless through SUDO_USER/HOME and chowns what it writes back
# to SUDO_UID/SUDO_GID, so the plist sets those four variables.
set -euo pipefail

LABEL=local.portless.proxy-443
PLIST=/Library/LaunchDaemons/$LABEL.plist
LOG=/Library/Logs/portless-443.log
PORTLESS=${PORTLESS:-/opt/homebrew/bin/portless}
CHECK_URL=https://localhost/

die() { echo "error: $*" >&2; exit 1; }

require_root() {
  [ "$(id -u)" = 0 ] || die "run with sudo"
  [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ] || die "run with sudo from your own account (SUDO_USER is not set)"
}

write_plist() {
  local user=$1 uid gid home
  uid=$(id -u "$user")
  gid=$(id -g "$user")
  home=$(dscl . -read "/Users/$user" NFSHomeDirectory | awk '{print $2}')
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PORTLESS</string>
    <string>proxy</string><string>start</string><string>--foreground</string>
    <string>--port</string><string>443</string><string>--https</string><string>--skip-trust</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>$home</string>
    <key>SUDO_USER</key><string>$user</string>
    <key>SUDO_UID</key><string>$uid</string>
    <key>SUDO_GID</key><string>$gid</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
}

listeners_443() { lsof -nP -iTCP:443 -sTCP:LISTEN -t 2>/dev/null | sort -u; }

# Only a Portless proxy may hold 443 (one started by hand with sudo); checked before anything is written.
check_443_holders() {
  local pid cmd
  for pid in $(listeners_443); do
    cmd=$(ps -o command= -p "$pid" || true)
    case "$cmd" in
      *portless*"proxy start"*) ;;
      *) die "port 443 is held by something other than Portless (pid $pid: $cmd)" ;;
    esac
  done
}

# The hand-started proxy holds 443; the daemon cannot bind until it is gone.
stop_manual_proxy() {
  local pid
  for pid in $(listeners_443); do
    echo "stopping hand-started proxy $pid: $(ps -o command= -p "$pid" || true)"
    kill "$pid"
  done
  for _ in $(seq 1 20); do
    [ -z "$(listeners_443)" ] && return 0
    sleep 0.5
  done
  die "port 443 is still in use after stopping the old proxy"
}

wait_for_443() {
  for _ in $(seq 1 40); do
    [ -n "$(listeners_443)" ] && return 0
    sleep 0.5
  done
  die "the daemon did not start listening on 443; see $LOG"
}

cmd_install() {
  require_root
  [ -x "$PORTLESS" ] || die "$PORTLESS not found; install Portless first"
  check_443_holders
  local tmp
  tmp=$(mktemp)
  write_plist "$SUDO_USER" >"$tmp"
  plutil -lint "$tmp" >/dev/null
  if launchctl print "system/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "system/$LABEL" || true
  fi
  install -o root -g wheel -m 644 "$tmp" "$PLIST"
  rm -f "$tmp"
  stop_manual_proxy
  launchctl bootstrap system "$PLIST"
  wait_for_443
  cmd_status
}

cmd_uninstall() {
  require_root
  launchctl bootout "system/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $LABEL; proxies on other ports keep working"
}

cmd_status() {
  if launchctl print "system/$LABEL" >/dev/null 2>&1; then
    launchctl print "system/$LABEL" | grep -E '^[[:space:]]+(state|pid|last exit code) =' | sed -E 's/^[[:space:]]+/launchd: /'
  else
    echo "launchd: $LABEL is not loaded"
  fi
  if curl -sk -D - -o /dev/null --max-time 3 "$CHECK_URL" 2>/dev/null | grep -qi '^x-portless:'; then
    echo "443: Portless answers"
  else
    echo "443: no Portless answer at $CHECK_URL"
  fi
}

case "${1:-}" in
  install) cmd_install ;;
  uninstall) cmd_uninstall ;;
  status) cmd_status ;;
  plist) write_plist "${SUDO_USER:-$(id -un)}" ;;
  *) echo "usage: $0 install|uninstall|status|plist" >&2; exit 64 ;;
esac

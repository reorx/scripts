#!/usr/bin/env bash
# End-to-end check of pg-doctor against synthetic data directories.
#
# `pg-doctor --selftest` covers the pure logic; this exercises the parts that touch the
# real filesystem, real ps output, and the --fix path — including the safety property
# that matters most: a live postmaster's lock file must never be removed.
set -u

DOCTOR=/Users/reorx/Code/scripts/skills/systools/scripts/pg-doctor
WORK=$(mktemp -d /tmp/pg-doctor-verify.XXXXXX)
LIVE_DATADIR=/opt/homebrew/var/postgresql@18
FAILED=0

expect() { # expect <label> <needle> <output>
    if grep -q -- "$2" <<<"$3"; then
        echo "  ✅ $1"
    else
        echo "  ❌ $1 — expected /$2/ in:"
        sed 's/^/       /' <<<"$3"
        FAILED=$((FAILED + 1))
    fi
}

expect_code() { # expect_code <label> <want> <got>
    if [ "$2" = "$3" ]; then
        echo "  ✅ $1 (exit $3)"
    else
        echo "  ❌ $1 — want exit $2, got $3"
        FAILED=$((FAILED + 1))
    fi
}

make_datadir() { # make_datadir <name> <pid|"">
    local dir="$WORK/$1"
    mkdir -p "$dir"
    [ -n "$2" ] && printf '%s\n%s\n1781576841\n5499\n/tmp\nlocalhost\n1 2\nready\n' "$2" "$dir" >"$dir/postmaster.pid"
    echo "$dir"
}

echo "pid recycled by an unrelated process (pid 1 = launchd)"
dir=$(make_datadir reused 1)
out=$("$DOCTOR" --datadir "$dir" 2>&1)
code=$?
expect "verdict is stale-reused" "stale-reused" "$out"
expect "names the intruder" "launchd" "$out"
expect_code "reports a problem" 1 $code

echo
echo "pid no longer exists"
dir=$(make_datadir dead 4194303)
out=$("$DOCTOR" --datadir "$dir" 2>&1)
expect "verdict is stale-dead" "stale-dead" "$out"

echo
echo "lock file is empty/corrupt"
dir=$(make_datadir corrupt "")
: >"$dir/postmaster.pid"
out=$("$DOCTOR" --datadir "$dir" 2>&1)
expect "verdict is corrupt" "corrupt" "$out"

echo
echo "no lock file at all"
dir=$(make_datadir nolock "")
out=$("$DOCTOR" --datadir "$dir" 2>&1)
code=$?
expect "verdict is no-lock" "no-lock" "$out"
expect_code "an idle instance is not a problem" 0 $code

echo
echo "lock held by a postgres serving a different data directory"
live_pid=$(pgrep -f "postgresql@18/bin/postgres" | head -1)
if [ -n "$live_pid" ]; then
    dir=$(make_datadir foreign "$live_pid")
    out=$("$DOCTOR" --datadir "$dir" 2>&1)
    expect "verdict is ambiguous" "ambiguous" "$out"
    out=$("$DOCTOR" --datadir "$dir" --fix --backup-dir "$WORK" 2>&1)
    expect "--fix refuses to touch it" "nothing to fix" "$out"
    [ -f "$dir/postmaster.pid" ] && echo "  ✅ lock file left in place" || {
        echo "  ❌ lock file was deleted"
        FAILED=$((FAILED + 1))
    }
else
    echo "  ⏭  no live postgres to borrow a pid from"
fi

echo
echo "--fix clears a stale lock"
dir=$(make_datadir fixme 1)
mkdir -p "$WORK/backups"
out=$("$DOCTOR" --datadir "$dir" --fix --backup-dir "$WORK/backups" 2>&1)
code=$?
expect "removes the lock file" "removed $dir/postmaster.pid" "$out"
expect "does not poke brew for a detached datadir" "not managed by brew services" "$out"
expect_code "repair reported as success" 0 $code
[ ! -f "$dir/postmaster.pid" ] && echo "  ✅ lock file gone" || {
    echo "  ❌ lock file still there"
    FAILED=$((FAILED + 1))
}
if compgen -G "$WORK/backups/postmaster.pid.*" >/dev/null; then
    echo "  ✅ backup written"
    grep -q "^1$" "$WORK"/backups/postmaster.pid.* && echo "  ✅ backup preserves original content" || {
        echo "  ❌ backup content wrong"
        FAILED=$((FAILED + 1))
    }
else
    echo "  ❌ no backup written"
    FAILED=$((FAILED + 1))
fi

echo
echo "SAFETY: --fix must never disturb a live database"
if [ -f "$LIVE_DATADIR/postmaster.pid" ]; then
    before=$(stat -f '%i %m %z' "$LIVE_DATADIR/postmaster.pid")
    out=$("$DOCTOR" --datadir "$LIVE_DATADIR" --fix --backup-dir "$WORK" 2>&1)
    code=$?
    after=$(stat -f '%i %m %z' "$LIVE_DATADIR/postmaster.pid" 2>&1)
    expect "verdict is healthy" "healthy" "$out"
    expect_code "healthy instance exits 0" 0 $code
    [ "$before" = "$after" ] && echo "  ✅ live lock file untouched" || {
        echo "  ❌ live lock file changed: $before → $after"
        FAILED=$((FAILED + 1))
    }
else
    echo "  ⏭  $LIVE_DATADIR is not running"
fi

echo
rm -rf "$WORK"
if [ "$FAILED" -gt 0 ]; then
    echo "❌ $FAILED check(s) failed"
    exit 1
fi
echo "✅ all end-to-end checks passed"

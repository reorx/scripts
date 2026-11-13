#!/bin/bash
set -euo pipefail

SCRIPT=$(cd "$(dirname "$0")" && pwd)/openon.sh
WORK=$(mktemp -d "${TMPDIR:-/tmp}/openon-test.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/temp files"
export TMPDIR="$WORK/temp files" OPENON_TEST_DIR="$WORK"
export PATH="$WORK/bin:$PATH"

cat > "$WORK/bin/scp" <<'EOF'
#!/bin/bash
set -euo pipefail
[[ $# == 3 && $1 == -- && $2 == "$EXPECTED_SOURCE" ]]
printf '%s\n' "$3" > "$OPENON_TEST_DIR/copied"
printf 'remote contents\n' > "$3"
exit "${COPY_STATUS:-0}"
EOF
cat > "$WORK/bin/open" <<'EOF'
#!/bin/bash
set -euo pipefail
[[ $# == 1 && -f $1 ]]
[[ $(cat "$1") == 'remote contents' ]]
printf '%s\n' "$1" > "$OPENON_TEST_DIR/opened"
exit "${OPEN_STATUS:-0}"
EOF
chmod +x "$WORK/bin/scp" "$WORK/bin/open"

# Given a remote file, preserve its name and contents, and retain the local copy.
export EXPECTED_SOURCE='genji.ts:Code/foo/bar.md'
"$SCRIPT" "$EXPECTED_SOURCE"
first=$(cat "$WORK/opened")
[[ $first == "$TMPDIR"/openon.*/bar.md && -f $first ]]
[[ $(cat "$WORK/copied") == "$first" ]]

# Repeated downloads must not overwrite a file already open in an application.
"$SCRIPT" "$EXPECTED_SOURCE"
[[ $(cat "$WORK/opened") != "$first" && -f $first ]]

# Quoted paths and user@host syntax reach scp as a single unchanged argument.
export EXPECTED_SOURCE='alice@genji.ts:/Code/foo/a b:中文.md'
"$SCRIPT" "$EXPECTED_SOURCE"
[[ $(cat "$WORK/opened") == "$TMPDIR"/openon.*/'a b:中文.md' ]]

# Failed transfers must not open or retain partial files.
rm "$WORK/opened"
if COPY_STATUS=1 "$SCRIPT" "$EXPECTED_SOURCE"; then
    echo 'FAIL: failed transfer reported success' >&2
    exit 1
fi
[[ ! -e $WORK/opened && ! -e $(dirname "$(cat "$WORK/copied")") ]]

# If opening fails, keep the downloaded file available for manual recovery.
if OPEN_STATUS=1 "$SCRIPT" "$EXPECTED_SOURCE"; then
    echo 'FAIL: failed open reported success' >&2
    exit 1
fi
[[ -f $(cat "$WORK/copied") ]]

# Invalid input and help must not invoke either external command.
rm "$WORK/copied" "$WORK/opened"
for spec in '' 'local.md' ':file.md' 'host:' '-host:file' 'host:dir/' 'host:.' 'host:..'; do
    if "$SCRIPT" "$spec"; then
        echo "FAIL: accepted invalid source: $spec" >&2
        exit 1
    fi
done
if "$SCRIPT" || "$SCRIPT" host:file extra; then
    echo 'FAIL: accepted wrong number of arguments' >&2
    exit 1
fi
"$SCRIPT" --help
[[ ! -e $WORK/copied && ! -e $WORK/opened ]]
echo 'All openon behavior tests passed.'

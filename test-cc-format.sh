#!/usr/bin/env bash
# Behavior tests for `cc-format --hook` with Claude Code and Codex PostToolUse events
set -euo pipefail

CC_FORMAT="$(cd "$(dirname "$0")" && pwd)/cc-format"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
REPO="$WORK/repo"
mkdir -p "$REPO" "$WORK/elsewhere"
git -C "$REPO" init -q
passed=0

if [ -f "$HOME/.config/cc-format/is_off" ]; then
    echo "cc-format is toggled off, turn it on with 'CONTROL_MODE=1 cc-format toggle' first" >&2
    exit 1
fi

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    [ -n "${OUT:-}" ] && printf 'stdout: %s\n' "$OUT" >&2
    printf 'stderr: %s\n' "$(cat "$WORK/stderr" 2> /dev/null)" >&2
    exit 1
}

pass() {
    printf 'PASS: %s\n' "$1"
    passed=$((passed + 1))
}

expect_content() {
    local file=$1 expected=$2
    [ "$(cat "$file")" == "$expected" ] || fail "$file should be '$expected', got '$(cat "$file")'"
}

expect_json() {
    local filter=$1
    jq -e "$filter" <<< "$OUT" > /dev/null || fail "stdout should match $filter"
}

claude_event() {
    jq -nc --arg path "$1" '{hook_event_name: "PostToolUse", tool_name: "Write", tool_input: {file_path: $path}}'
}

codex_event() {
    jq -nc --arg patch "$1" --arg cwd "$REPO" \
        '{hook_event_name: "PostToolUse", cwd: $cwd, tool_name: "apply_patch", tool_input: {command: $patch}}'
}

# Run the hook from a dir other than the session cwd; sets OUT and STATUS
run_hook() {
    STATUS=0
    OUT="$(cd "$WORK/elsewhere" && "$CC_FORMAT" --hook <<< "$1" 2> "$WORK/stderr")" || STATUS=$?
}

# Given a Claude Code Write on a supported file, it formats the file like the old inline command
printf 'x=1\n' > "$REPO/a.py"
run_hook "$(claude_event "$REPO/a.py")"
[ "$STATUS" -eq 0 ] || fail "Claude .py exit status $STATUS"
expect_content "$REPO/a.py" 'x = 1'
pass 'Claude: Write on a .py file formats it'

# Given a Claude Code Write on an unsupported file, it does nothing
printf 'x=1\n' > "$REPO/notes.md"
run_hook "$(claude_event "$REPO/notes.md")"
[ "$STATUS" -eq 0 ] && [ -z "$OUT" ] || fail "Claude .md should be a silent no-op"
expect_content "$REPO/notes.md" 'x=1'
pass 'Claude: unsupported extension is skipped'

# Given a formatter error in Claude Code, its exit status and stderr reach Claude unchanged
printf 'def f(:\n' > "$REPO/bad.py"
run_hook "$(claude_event "$REPO/bad.py")"
[ "$STATUS" -eq 2 ] || fail "Claude syntax error should exit 2, got $STATUS"
grep -q 'Failed to parse' "$WORK/stderr" || fail 'Claude syntax error should print the ruff error'
pass 'Claude: formatter exit status passes through'

# Given a Codex patch, it formats the files it added, updated or moved to, and tells the model about them
printf 'x=1\n' > "$REPO/new.py"
mkdir -p "$REPO/space dir"
printf 'const a = "x"\n' > "$REPO/space dir/new.ts"
printf 'const b = "y"\n' > "$REPO/view.tsx"
printf "const c = 'z';\n" > "$REPO/app.js"
printf 'x=1\n' > "$REPO/notes.md"
printf 'const d = "w"\n' > "$REPO/skip.jsx"
run_hook "$(codex_event "*** Begin Patch
*** Add File: new.py
+x=1
*** Update File: old.ts
*** Move to: space dir/new.ts
@@
-const a = 1
+const a = \"x\"
*** Update File: $REPO/view.tsx
@@
-const b = 1
+const b = \"y\"
*** Update File: app.js
@@
-const c = 1
+const c = 'z';
*** Delete File: gone.py
*** Add File: notes.md
+x=1
*** Add File: skip.jsx
+const d = \"w\"
*** End Patch")"
[ "$STATUS" -eq 0 ] || fail "Codex patch exit status $STATUS"
expect_content "$REPO/new.py" 'x = 1'
expect_content "$REPO/space dir/new.ts" "const a = 'x';"
expect_content "$REPO/view.tsx" "const b = 'y';"
expect_content "$REPO/app.js" "const c = 'z';"
expect_content "$REPO/notes.md" 'x=1'
expect_content "$REPO/skip.jsx" 'const d = "w"'
expect_json '.hookSpecificOutput.hookEventName == "PostToolUse"'
expect_json '.hookSpecificOutput.additionalContext | contains("re-read")'
expect_json '.hookSpecificOutput.additionalContext | (contains("new.py") and contains("space dir/new.ts") and contains("view.tsx"))'
expect_json '.hookSpecificOutput.additionalContext | contains("app.js") | not'
expect_json 'has("systemMessage") | not'
pass 'Codex: added, updated and moved-to files are formatted and reported'

# Given a Codex patch whose files are already formatted, it prints nothing
run_hook "$(codex_event "*** Begin Patch
*** Update File: app.js
@@
-const c = 1
+const c = 'z';
*** Add File: notes.md
+x=1
*** End Patch")"
[ "$STATUS" -eq 0 ] && [ -z "$OUT" ] || fail 'Codex patch without formatting changes should print nothing'
pass 'Codex: nothing reformatted, no output'

# Given a formatter error in Codex, it reports the error as context and exits 0 to keep the patch result
printf 'def f(:\n' > "$REPO/broken.py"
printf 'y=2\n' > "$REPO/ok.py"
run_hook "$(codex_event "*** Begin Patch
*** Add File: broken.py
+def f(:
*** Add File: ok.py
+y=2
*** End Patch")"
[ "$STATUS" -eq 0 ] || fail "Codex formatter error should exit 0, got $STATUS"
expect_content "$REPO/ok.py" 'y = 2'
expect_json '.hookSpecificOutput.additionalContext | (contains("broken.py") and contains("Failed to parse") and contains("ok.py"))'
expect_json '.systemMessage | contains("broken.py")'
pass 'Codex: formatter error is reported without failing the patch'

# Given header lines with surrounding whitespace, which Codex's patch parser accepts, the path is still found
printf 'z=3\n' > "$REPO/padded.py"
run_hook "$(codex_event "*** Begin Patch
  *** Update File: padded.py
@@
-z=1
+z=3
*** End Patch")"
expect_content "$REPO/padded.py" 'z = 3'
pass 'Codex: padded header lines are parsed'

# Given cc-format is toggled off, the hook does nothing
mkdir -p "$WORK/home/.config/cc-format"
touch "$WORK/home/.config/cc-format/is_off"
printf 'w=4\n' > "$REPO/off.py"
HOME="$WORK/home" run_hook "$(codex_event "*** Begin Patch
*** Add File: off.py
+w=4
*** End Patch")"
[ "$STATUS" -eq 0 ] && [ -z "$OUT" ] || fail 'toggled off should be a silent no-op'
expect_content "$REPO/off.py" 'w=4'
pass 'toggled off: no formatting'

echo "$passed passed"

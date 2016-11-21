#!/bin/bash

DEBUG="false"

function usage() {
    echo "Usage: gobuildcheck PATH"
}

function findgo() {
    local num=$(find $1 -maxdepth 1 -type f -name "*.go" -not -path "*_test.go" | wc -l)
    local num=$(echo $num)
    echo "$num"
}

function finddir() {
    find $1 -type d \
        -not -path "./vendor*" \
        -not -path "./.*"
}

function log_debug() {
    if [ "$DEBUG" = "true" ]; then
        echo "$@"
    fi
}

target="$1"
if [ -z "$target" ]; then
    usage
    exit 1
fi

declare -a errpaths

for dir in $(finddir $1); do
    num=$(findgo $dir)
    if [ $num -eq 0 ]; then
        log_debug "→ $dir (skip)"
        continue
    fi
    log_debug "→ $dir $num"

    ro=$(go install $dir 2>&1)
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "$dir ... FAIL"
        echo "$ro"
        errpaths=("${errpaths[@]}" "$dir")
    fi
done

echo
if [ ${#errpaths[@]} -eq 0 ]; then
    echo "OK"
else
    echo "FAILED ${#errpaths[@]} (${errpaths[@]})"
    exit 2
fi

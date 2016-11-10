#!/bin/bash

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

target="$1"
if [ -z "$target" ]; then
    usage
    exit 1
fi

declare -a errpaths

for dir in $(finddir $1); do
    num=$(findgo $dir)
    if [ $num -eq 0 ]; then
        echo "-> $dir (skip)"
        continue
    fi
    echo "-> $dir $num"

    go install $dir
    rc=$?
    if [ $rc -ne 0 ]; then
        errpaths=("${errpaths[@]}" "$dir")
    fi
done

echo
if [ ${#errpaths[@]} -eq 0 ]; then
    echo "All pass!"
else
    echo "Find errors in: ${errpaths[@]}"
fi

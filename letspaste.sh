#!/bin/bash

# TODO:
# - rewrite in python
# - implement paste upload by urllib2
# - option for generate command with chmod

function modify_url_bpaste() {
    python -c "import sys
import re
url = sys.argv[1]
if not url.startswith('http:'):
    print('invalid url')
    sys.exit(1)
sp = url.split('/')
rv = 'http://dpaste.com/{}.txt'.format(sp[-1])
print(rv)
" "$1"
    exit $?
}

function assert_success() {
    if [ $1 -ne 0 ]; then
        echo "exit $1, $2"
        exit 1
    fi
}

function pastebin() {
    pastebinit -i "$1" -b dpaste.com
}

function generate_and_copy() {
    local filename=$(basename "$2")
    local cmd="curl -s -o \"$filename\" \"$1\""
    echo "$cmd"
    echo "$cmd" | tr -d '\n' | pbcopy
    echo "* Copied to clipboard"
}

function fail_usage() {
    usage
    exit 1
}

function usage() {
    echo "Usage: letspaste FILE"
}


# main
filepath="$1"
[ -z "$filepath" ] && fail_usage

out=$(pastebin "$filepath")
assert_success $? "failed to upload pastebin"

url=$(modify_url_bpaste "$out")
assert_success $? "failed to modify url"

generate_and_copy "$url" "$filepath"
assert_success $? "failed to copy to clipboard"

#!/bin/bash
#
# Usage:
# $ local-vendor ../foo
# $ local-vendor ~/go/src/github.com/me/foo
# $ local-vendor ~/projects/foo github.com/me/foo
#
# Vars:
# abs_path -> /Users/me/go/src/github.com/me/foo
# import_path -> github.com/me/foo
# vendor_path -> vendor/github.com/me/foo
#
# Workflow:
# 1. rm $vendor_path
# 2. ln -s $abs_path $vendor_path

set -eo pipefail

function usage() {
    cat << EOF
usage: local-vendor LOCALPATH [IMPORTPATH]

Remove IMPORTPATH under vendor/ of current directory, link LOCALPATH as
the new vendor package.
EOF
}

function get_realpath() {
    if [[ $OSTYPE == darwin* ]]; then
        grealpath $1
    else
        realpath $1
    fi
}

function parse_import_path() {
    python -c 'import sys; a=sys.argv[1]; print "/".join(a.split("/")[-3:])' $1
}

# check args
if [ "$#" -gt 2 ]; then
    echo "error: only accept 1 or 2 arguments"
    usage
    exit 1
fi
if [ -z "$1" ]; then
    echo "error: please input at least 1 argument"
    usage
    exit 1
fi

# parse paths
abs_path=$(get_realpath "$1")
if [ -n "$2" ]; then
    import_path="$2"
else
    import_path=$(parse_import_path "$abs_path")
fi
vendor_path="vendor/$import_path"
vendor_dir=$(dirname "$vendor_path")
#echo "abs_path $abs_path"
#echo "import_path $import_path"
#echo "vendor_path $vendor_path"

# step 1. rm $vendor_path
echo "> rm $vendor_path"
rm -rf "$vendor_path"

# step 2. link $abs_path to $vendor_path
echo "> link $abs_path -> $vendor_path"
if [ ! -e "$vendor_dir" ]; then
    mkdir -p "$vendor_dir"
fi
ln -s $abs_path $vendor_path
#ls -ld $vendor_path

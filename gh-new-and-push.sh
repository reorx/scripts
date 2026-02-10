#!/bin/bash

username=reorx
reponame=$(basename "$PWD")

if [ -n "$SKIP_CREATE" ]; then
    echo "skip creating the repo"
else
    visibility="--private"
    if [ -n "$PUBLIC" ]; then
        visibility="--public"
    fi
    gh repo create "$reponame" $visibility
fi

set -eu
set -x

git remote add origin "git@github.com:$username/$reponame.git"
git push -u origin master

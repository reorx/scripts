#!/bin/bash

username=reorx
reponame=$(basename "$PWD")

if [ -n "$SKIP_CREATE" ]; then
    echo "skip creating the repo"
else
    gh repo create "$reponame" --private
fi

set -eu
set -x

git remote add origin "git@github.com:$username/$reponame.git"
git push -u origin master

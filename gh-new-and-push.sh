#!/bin/bash

set -eu

username=reorx
reponame=$(basename "$PWD")
set -x

gh repo create "$reponame" --private

git remote add origin "git@github.com:$username/$basename.git"
git push -u origin master

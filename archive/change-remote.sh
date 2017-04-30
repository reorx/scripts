#!/usr/bin/env bash

#sedargs="-i ''"
sedargs=""

for dir in `find . -maxdepth 1 -type d`; do
    gitcfg="$dir/.git/config"
    if [ -f "$gitcfg" ]; then
        echo $gitcfg
        sed $sedargs "s/git.corp.16financial.com/repo.16financial.net/g" $gitcfg
        #grep 'git.corp.16financial.com' $gitcfg
    fi
done

#!/usr/bin/env bash

#sedargs="-i ''"
sedargs=""

from_remote=""
to_remote=""

for dir in `find . -maxdepth 1 -type d`; do
    gitcfg="$dir/.git/config"
    if [ -f "$gitcfg" ]; then
        echo $gitcfg
        sed $sedargs "s/$from_remote/$to_remote/g" $gitcfg
        #grep $from_remote $gitcfg
    fi
done

#!/bin/bash


if [ -z "$ZT_IP_PREFIX" ]; then
    echo "ZT_IP_PREFIX is not set"
    exit 1
fi

zt_ip=$(ifconfig | grep $ZT_IP_PREFIX | awk '{ print $2 }')

if [ -z "$zt_ip" ]; then
    echo "cannot get zt ip"
    exit 1
fi
echo "$zt_ip"


if [ -n "$TARGET_SERVER" ]; then
    if [ -z "$TARGET_DIR" ]; then
        echo "TARGET_DIR is not set"
        exit 1
    fi
    set -eu
    tmp_file="/tmp/$(hostname).zt_ip.txt"
    echo "$zt_ip
    $(date)" > "$tmp_file"

    echo "upload $tmp_file to $TARGET_SERVER:$TARGET_DIR"
    scp "$tmp_file" $TARGET_SERVER:$TARGET_DIR
fi

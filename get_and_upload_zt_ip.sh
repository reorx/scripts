#!/bin/bash

if [ -z "$IP_PREFIX" ]; then
    echo "IP_PREFIX is not set"
    exit 1
fi

if [ -z "$TARGET_SERVER" ]; then
    echo "TARGET_SERVER is not set"
    exit 1
fi

if [ -z "$TARGET_DIR" ]; then
    echo "TARGET_DIR is not set"
    exit 1
fi


set -eu

zt_ip=$(ifconfig | grep $IP_PREFIX | awk '{ print $2 }')

if [ -z "$zt_ip" ]; then
    echo "cannot get zt ip"
    exit 1
fi
echo "get zt ip: $zt_ip"

tmp_file="/tmp/$(hostname).zt_ip.txt"
echo "$zt_ip
$(date)" > "$tmp_file"

echo "upload $tmp_file to $TARGET_SERVER:$TARGET_DIR"
scp "$tmp_file" $TARGET_SERVER:$TARGET_DIR

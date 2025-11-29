#!/bin/bash

CONCURRENCY=8
: ${SECRET:=YOUR_SECRET_TOKEN}


aria2c --enable-rpc \
       --rpc-listen-all=true \
       --rpc-allow-origin-all \
       --rpc-listen-port=6800 \
       --rpc-secret=$SECRET \
       --dir=$HOME/Downloads \
       --continue=true \
       --max-concurrent-downloads=5 \
       --max-connection-per-server=$CONCURRENCY \
       --split=$CONCURRENCY $@

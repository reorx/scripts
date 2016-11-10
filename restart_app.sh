#!/bin/bash

app_path="$1"
kill_wait=3

echo "[$(date)] Restaring $app_path"

pid=$(ps aux | grep "$app_path" | grep -v grep | grep -v restart_app.sh | awk '{print $2}')
if [ "$pid" ]; then
    echo "Got pid: $pid, try to kill & start"
    kill $pid
    sleep $kill_wait
else
    echo "No pid found, just start"
fi

open "$app_path"

echo "[$(date)] Done restart $app_path"
echo

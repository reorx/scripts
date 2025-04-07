#!/bin/bash

set -u

echo "Envs (ssh): $TUNNEL_HOST $TUNNEL_PORT"
echo "Envs (DB): $DB_HOST, $DB_PORT, $DB_USER, $DB_PASS, $DUMP_FILE"

# Start the ssh tunnel
ssh -o ControlMaster=no -o ControlPersist no -L $TUNNEL_PORT:$DB_HOST:$DB_PORT -N $TUNNEL_HOST &
TUNNEL_PID=$!

mysqldump --column-statistics=0 -h 127.0.0.1 -P $TUNNEL_PORT -u$DB_USER -p$DB_PASS dwtoolkit > "$DUMP_FILE"

echo "kill $TUNNEL_PID"
kill $TUNNEL_PID

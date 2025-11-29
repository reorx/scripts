#!/bin/bash

MINIO_DIR="./.minio"
DATA_DIR="$MINIO_DIR/data"
PID_FILE="$MINIO_DIR/minio.pid"
LOG_FILE="$MINIO_DIR/minio.log"
API_PORT=9000
WEBUI_PORT=56070

start_minio() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "MinIO is already running (PID: $pid)"
            return 1
        else
            echo "Removing stale PID file"
            rm "$PID_FILE"
        fi
    fi

    echo "Starting MinIO server..."
    mkdir -p "$MINIO_DIR" "$DATA_DIR"

    # Start MinIO in background and capture PID
    nohup minio server --console-address ":$WEBUI_PORT" "$DATA_DIR" > "$LOG_FILE" 2>&1 &
    local pid=$!

    # Save PID to file
    echo "$pid" > "$PID_FILE"

    # Wait a moment to check if it started successfully
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        echo "MinIO started successfully (PID: $pid)"
        echo "Log file: $LOG_FILE"
        echo
        echo "--- Last 30 lines of log ---"
        tail -n 30 "$LOG_FILE"
    else
        echo "Failed to start MinIO"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_minio() {
    if [ ! -f "$PID_FILE" ]; then
        echo "MinIO is not running (no PID file found)"
        return 1
    fi

    local pid=$(cat "$PID_FILE")
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "MinIO is not running (process not found)"
        rm -f "$PID_FILE"
        return 1
    fi

    echo "Stopping MinIO (PID: $pid)..."
    kill "$pid"

    # Wait for process to stop
    local count=0
    while kill -0 "$pid" 2>/dev/null && [ $count -lt 10 ]; do
        sleep 1
        count=$((count + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        echo "Force killing MinIO process..."
        kill -9 "$pid"
    fi

    rm -f "$PID_FILE"
    echo "MinIO stopped"
}

status_minio() {
    if [ ! -f "$PID_FILE" ]; then
        echo "MinIO is not running (no PID file)"
        return 1
    fi

    local pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "MinIO is running (PID: $pid)"
        return 0
    else
        echo "MinIO is not running (stale PID file)"
        rm -f "$PID_FILE"
        return 1
    fi
}

case "$1" in
    start)
        start_minio
        ;;
    stop)
        stop_minio
        ;;
    status)
        status_minio
        ;;
    webui)
        open http://localhost:$WEBUI_PORT
        ;;
    restart)
        stop_minio
        sleep 1
        start_minio
        ;;
    *)
        echo "Usage: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac

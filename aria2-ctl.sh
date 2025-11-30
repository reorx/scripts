#!/bin/bash

ARIA2_DIR="$HOME/.local/share/aria2"
PID_FILE="$ARIA2_DIR/aria2.pid"
LOG_FILE="$ARIA2_DIR/aria2.log"
CONCURRENCY=8
: ${SECRET:=YOUR_SECRET_TOKEN}

start_aria2() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "aria2 is already running (PID: $pid)"
            return 1
        else
            echo "Removing stale PID file"
            rm "$PID_FILE"
        fi
    fi

    echo "Starting aria2 daemon..."
    mkdir -p "$ARIA2_DIR"

    nohup aria2c --enable-rpc \
           --rpc-listen-all=true \
           --rpc-allow-origin-all \
           --rpc-listen-port=6800 \
           --rpc-secret=$SECRET \
           --dir=$HOME/Downloads \
           --continue=true \
           --max-concurrent-downloads=5 \
           --max-connection-per-server=$CONCURRENCY \
           --split=$CONCURRENCY > "$LOG_FILE" 2>&1 &
    local pid=$!

    echo "$pid" > "$PID_FILE"

    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        echo "aria2 started successfully (PID: $pid)"
        echo "Log file: $LOG_FILE"
        echo
        echo "--- Last 30 lines of log ---"
        tail -n 30 "$LOG_FILE"
    else
        echo "Failed to start aria2"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_aria2() {
    if [ ! -f "$PID_FILE" ]; then
        echo "aria2 is not running (no PID file found)"
        return 1
    fi

    local pid=$(cat "$PID_FILE")
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "aria2 is not running (process not found)"
        rm -f "$PID_FILE"
        return 1
    fi

    echo "Stopping aria2 (PID: $pid)..."
    kill "$pid"

    local count=0
    while kill -0 "$pid" 2>/dev/null && [ $count -lt 10 ]; do
        sleep 1
        count=$((count + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        echo "Force killing aria2 process..."
        kill -9 "$pid"
    fi

    rm -f "$PID_FILE"
    echo "aria2 stopped"
}

status_aria2() {
    if [ ! -f "$PID_FILE" ]; then
        echo "aria2 is not running (no PID file)"
        return 1
    fi

    local pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "aria2 is running (PID: $pid)"
        return 0
    else
        echo "aria2 is not running (stale PID file)"
        rm -f "$PID_FILE"
        return 1
    fi
}

logs_aria2() {
    if [ ! -f "$LOG_FILE" ]; then
        echo "No log file found at $LOG_FILE"
        return 1
    fi

    if [ "$1" = "-f" ]; then
        tail -f "$LOG_FILE"
    else
        tail -n 50 "$LOG_FILE"
    fi
}

case "$1" in
    start)
        start_aria2
        ;;
    stop)
        stop_aria2
        ;;
    status)
        status_aria2
        ;;
    restart)
        stop_aria2
        sleep 1
        start_aria2
        ;;
    logs)
        logs_aria2 "$2"
        ;;
    *)
        echo "Usage: $0 {start|stop|status|restart|logs [-f]}"
        exit 1
        ;;
esac

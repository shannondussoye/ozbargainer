#!/bin/bash

# Configuration
PORT=9228
PROFILE_DIR="$HOME/.ozbargain-chrome-profile"
LOG_FILE="chrome_startup.log"

function check_ready() {
    curl -s http://127.0.0.1:$PORT/json/version > /dev/null 2>&1
}

function start() {
    if check_ready; then
        echo "[Bridge] Chrome is already running and responsive on port $PORT."
        return 0
    fi

    echo "[Bridge] Ensuring profile directory exists: $PROFILE_DIR"
    mkdir -p "$PROFILE_DIR"

    echo "[Bridge] Starting Google Chrome in debug mode on port $PORT..."
    google-chrome-stable \
        --remote-debugging-port=$PORT \
        --remote-debugging-address=127.0.0.1 \
        --user-data-dir="$PROFILE_DIR" \
        --headless=new \
        --disable-gpu \
        --no-sandbox > "$LOG_FILE" 2>&1 &
    
    # Wait for Chrome to be ready
    echo "[Bridge] Waiting for Chrome to initialize..."
    for i in {1..15}; do
        if check_ready; then
            echo "[Bridge] Chrome is fully ready!"
            return 0
        fi
        sleep 1
    done
    
    echo "[Bridge] Error: Chrome failed to start or bind to port $PORT."
    if [ -f "$LOG_FILE" ]; then
        tail -n 20 "$LOG_FILE"
    fi
    return 1
}

function stop() {
    if ! pgrep -f "remote-debugging-port=$PORT" > /dev/null; then
        echo "[Bridge] Chrome is not running."
        return 0
    fi

    echo "[Bridge] Stopping Google Chrome..."
    pkill -f "remote-debugging-port=$PORT"
    sleep 2
    if pgrep -f "remote-debugging-port=$PORT" > /dev/null; then
        echo "[Bridge] Force killing Chrome..."
        pkill -9 -f "remote-debugging-port=$PORT"
    fi
}

function status() {
    if check_ready; then
        echo "BRIDGE: RUNNING (Responsive on port $PORT)"
        return 0
    else
        if pgrep -f "remote-debugging-port=$PORT" > /dev/null; then
            echo "BRIDGE: ZOMBIE (Process exists but not responsive)"
            return 1
        else
            echo "BRIDGE: STOPPED"
            return 2
        fi
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    status)
        status
        ;;
    wait)
        # Just waits for readiness, useful for CI/CD or scripts
        for i in {1..30}; do
            if check_ready; then exit 0; fi
            sleep 1
        done
        exit 1
        ;;
    *)
        echo "Usage: $0 {start|stop|status|wait}"
        exit 1
        ;;
esac

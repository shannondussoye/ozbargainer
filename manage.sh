#!/bin/bash

# Configuration
PORT=9224
PROFILE_DIR="$HOME/.ozbargain-chrome-profile"
IMAGE_NAME="ozbargain-scraper"
CONTAINER_NAME="ozbargain-monitor"
DB_PATH="$(pwd)/ozbargain.db"

# Create profile dir if missing
mkdir -p "$PROFILE_DIR"

function start_chrome() {
    echo "[Manage] Starting Google Chrome in debug mode on port $PORT..."
    google-chrome-stable \
        --remote-debugging-port=$PORT \
        --remote-debugging-address=0.0.0.0 \
        --user-data-dir="$PROFILE_DIR" \
        --headless=new \
        --disable-gpu \
        --no-sandbox > chrome_startup.log 2>&1 &
    
    # Wait for Chrome to be ready
    echo "[Manage] Waiting for Chrome to initialize..."
    for i in {1..10}; do
        if nc -zv 127.0.0.1 $PORT > /dev/null 2>&1; then
            echo "[Manage] Chrome is ready!"
            return 0
        fi
        sleep 1
    done
    echo "[Manage] Error: Chrome failed to start or bind to port $PORT."
    cat chrome_startup.log
    return 1
}

function stop_chrome() {
    echo "[Manage] Stopping Google Chrome..."
    pkill -f "remote-debugging-port=$PORT"
}

function run_monitor() {
    echo "[Manage] Starting Docker container ($CONTAINER_NAME)..."
    
    # Stop existing container if any
    docker stop "$CONTAINER_NAME" > /dev/null 2>&1
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1

    docker run -d \
        --name "$CONTAINER_NAME" \
        --network host \
        --env-file .env \
        -e CHROME_CDP_URL="http://localhost:$PORT" \
        -e TZ=Australia/Sydney \
        -v /etc/localtime:/etc/localtime:ro \
        -v "$DB_PATH":/app/ozbargain.db \
        "$IMAGE_NAME"
    
    echo "[Manage] Monitor is running. Use 'docker logs -f $CONTAINER_NAME' to view logs."
}

case "$1" in
    start)
        start_chrome
        run_monitor
        ;;
    stop)
        docker stop "$CONTAINER_NAME"
        docker rm "$CONTAINER_NAME"
        stop_chrome
        ;;
    restart)
        $0 stop
        $0 start
        ;;
    chrome)
        start_chrome
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|chrome}"
        exit 1
        ;;
esac

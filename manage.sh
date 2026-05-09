#!/bin/bash

# Configuration
PORT=9228
PROFILE_DIR="$HOME/.ozbargain-chrome-profile"
IMAGE_NAME="ozbargain-scraper"
CONTAINER_NAME="ozbargain-monitor"
DB_PATH="$(pwd)/ozbargain.db"

# Ensure .env exists
if [ ! -f .env ]; then
    echo "[Error] .env file not found. Please copy .env.example to .env and configure TELEGRAM variables."
    exit 1
fi

# Create profile dir and db file if missing
mkdir -p "$PROFILE_DIR"
touch "$DB_PATH"

function start_chrome() {
    echo "[Manage] Starting Google Chrome in debug mode on port $PORT..."
    google-chrome-stable \
        --remote-debugging-port=$PORT \
        --remote-debugging-address=127.0.0.1 \
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
    echo "[Manage] Starting Docker container via docker-compose..."
    
    export CHROME_CDP_URL="http://127.0.0.1:$PORT"
    docker compose up -d --build
    
    echo "[Manage] Monitor is running. Use 'docker compose logs -f monitor' to view logs."
}

case "$1" in
    start)
        start_chrome
        run_monitor
        ;;
    stop)
        docker compose down
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

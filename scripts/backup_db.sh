#!/bin/bash
# OzBargainer Automated SQLite Backup (via Docker)
# This script uses the container's sqlite3 to perform an online backup.
# It ensures consistency even while the bot is active.

# Configuration
PROJECT_DIR="/home/shannon/Workspace/projects/ozbargainer"
CONTAINER_NAME="ozbargain-monitor"
DB_PATH_IN_CONTAINER="/app/ozbargain.db"
BACKUP_PATH_IN_CONTAINER="/app/backups" # Mapped to ./backups on host
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILENAME="ozbargain_$TIMESTAMP.db"
RETENTION_COUNT=10

# Ensure we are in the right directory
cd "$PROJECT_DIR" || exit 1

# Create host backup directory if missing (ensures volume mapping works)
mkdir -p "$PROJECT_DIR/backups"

echo "[$(date)] Starting backup of ozbargain.db via Docker..."

# Run backup command inside the container
# This uses the container's sqlite3 and writes to the mapped volume.
docker exec "$CONTAINER_NAME" sqlite3 "$DB_PATH_IN_CONTAINER" ".backup '$BACKUP_PATH_IN_CONTAINER/$BACKUP_FILENAME'"

if [ $? -eq 0 ]; then
    echo "[Success] Backup created: backups/$BACKUP_FILENAME"
    
    # Retention Policy on Host
    # List files by time, skip the newest ones, and remove the old ones.
    ls -t "$PROJECT_DIR/backups"/ozbargain_*.db | tail -n +$((RETENTION_COUNT + 1)) | xargs -r rm
    
    echo "[Info] Retention policy applied (Kept last $RETENTION_COUNT backups)."
else
    echo "[Error] Backup failed! (Is the container running?)"
    exit 1
fi

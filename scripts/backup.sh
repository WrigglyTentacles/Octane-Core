#!/usr/bin/env bash
# Backup Octane-Core Docker volume and .env
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/backups"
VOLUME_NAME="octane-data"

# Detect docker compose command
if command -v docker compose &>/dev/null; then
  COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE="docker-compose"
else
  echo "Error: docker compose or docker-compose not found"
  exit 1
fi

NO_STOP=false
for arg in "$@"; do
  if [[ "$arg" == "--no-stop" ]]; then
    NO_STOP=true
    break
  fi
done

cd "$PROJECT_ROOT"
mkdir -p "$BACKUP_DIR"

# Resolve full volume name (compose prefixes with project name)
VOLUME_FULL=$(docker volume ls -q | grep octane-data | head -1)
[[ -z "$VOLUME_FULL" ]] && VOLUME_FULL="$VOLUME_NAME"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$BACKUP_DIR/octane-backup-$TIMESTAMP.tar.gz"

echo "Backing up Octane-Core..."

if [[ "$NO_STOP" == false ]]; then
  echo "Stopping containers..."
  $COMPOSE down
fi

echo "Creating archive from volume..."
docker run --rm \
  -v "${VOLUME_FULL}:/data:ro" \
  -v "$BACKUP_DIR:/backup" \
  alpine \
  tar czf "/backup/octane-backup-$TIMESTAMP.tar.gz" -C /data .

# Add .env to archive if it exists (do inside container to avoid permission issues)
# BusyBox tar doesn't support -r (append), so extract, add .env, recreate
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  echo "Adding .env to archive..."
  docker run --rm \
    -v "$BACKUP_DIR:/backup" \
    -v "$PROJECT_ROOT/.env:/envfile:ro" \
    alpine \
    sh -c "cd /backup && mkdir -p /tmp/restore && gunzip -c octane-backup-$TIMESTAMP.tar.gz | tar -x -C /tmp/restore && cp /envfile /tmp/restore/.env && tar -czf octane-backup-$TIMESTAMP.tar.gz -C /tmp/restore . && rm -rf /tmp/restore"
fi

# Fix ownership so backup is readable by current user
docker run --rm -v "$BACKUP_DIR:/backup" alpine chown "$(id -u):$(id -g)" "/backup/octane-backup-$TIMESTAMP.tar.gz"

if [[ "$NO_STOP" == false ]]; then
  echo "Starting containers..."
  $COMPOSE up -d
fi

echo "Backup complete: $BACKUP_FILE"

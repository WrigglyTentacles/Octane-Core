#!/usr/bin/env bash
# Restore Octane-Core from backup
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
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

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <backup-file>"
  echo "Example: $0 backups/octane-backup-20250315-120000.tar.gz"
  exit 1
fi

BACKUP_FILE="$1"
if [[ ! -f "$BACKUP_FILE" ]]; then
  if [[ -f "$PROJECT_ROOT/$BACKUP_FILE" ]]; then
    BACKUP_FILE="$PROJECT_ROOT/$BACKUP_FILE"
  else
    echo "Error: Backup file not found: $BACKUP_FILE"
    exit 1
  fi
fi

# Resolve full volume name (compose prefixes with project name)
VOLUME_FULL=$(docker volume ls -q | grep octane-data | head -1)
if [[ -z "$VOLUME_FULL" ]]; then
  echo "Volume not found. Creating it via compose..."
  $COMPOSE up -d
  sleep 2
  $COMPOSE down
  VOLUME_FULL=$(docker volume ls -q | grep octane-data | head -1)
  [[ -z "$VOLUME_FULL" ]] && VOLUME_FULL="$VOLUME_NAME"
fi

cd "$PROJECT_ROOT"

echo "Stopping containers..."
$COMPOSE down 2>/dev/null || true

echo "Restoring from $BACKUP_FILE..."
docker run --rm \
  -v "${VOLUME_FULL}:/data" \
  -v "$(realpath "$BACKUP_FILE"):/backup.tar.gz:ro" \
  alpine \
  sh -c "cd /data && find . -mindepth 1 -delete 2>/dev/null; tar xzf /backup.tar.gz"

# Restore .env if it was in the archive
if tar -tzf "$BACKUP_FILE" | grep -q '^\.env$'; then
  echo "Restoring .env..."
  tar -xzf "$BACKUP_FILE" -O .env > "$PROJECT_ROOT/.env"
fi

echo "Starting containers..."
$COMPOSE up -d

echo "Restore complete."

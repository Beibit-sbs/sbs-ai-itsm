#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${ROOT_DIR}/backups/db"
BACKUP_FILE="${BACKUP_DIR}/${TIMESTAMP}_sbs_itsm.sql.gz"

mkdir -p "$BACKUP_DIR"

if ! docker compose -f "$ROOT_DIR/docker-compose.yml" ps --services --filter status=running | grep -qx postgres; then
  echo "Postgres container is not running. Start services first."
  exit 1
fi

docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip -c > "$BACKUP_FILE"

if [[ ! -s "$BACKUP_FILE" ]]; then
  echo "Backup file is empty: $BACKUP_FILE"
  exit 1
fi

echo "Backup created: $BACKUP_FILE"

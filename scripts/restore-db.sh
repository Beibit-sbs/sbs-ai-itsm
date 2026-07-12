#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" ]]; then
  echo "Usage: CONFIRM_RESTORE=yes bash scripts/restore-db.sh <backup.sql.gz|backup.sql>"
  exit 1
fi

if [[ "${CONFIRM_RESTORE:-no}" != "yes" ]]; then
  echo "Restore blocked. Set CONFIRM_RESTORE=yes to continue."
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file not found: $BACKUP_FILE"
  exit 1
fi

if ! docker compose -f "$ROOT_DIR/docker-compose.yml" ps --services --filter status=running | grep -qx postgres; then
  echo "Postgres container is not running. Start services first."
  exit 1
fi

echo "WARNING: restoring database from $BACKUP_FILE"

if [[ "$BACKUP_FILE" == *.gz ]]; then
  gzip -dc "$BACKUP_FILE" | docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"'
else
  cat "$BACKUP_FILE" | docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"'
fi

echo "Restore completed"

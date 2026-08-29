#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROJECT_NAME="${PROJECT_NAME:-sbs-itsm-production}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" ]]; then
  echo "Usage: CONFIRM_RESTORE=yes bash scripts/restore-db.sh <backup.dump>"
  exit 1
fi
if [[ "${CONFIRM_RESTORE:-no}" != "yes" ]]; then
  echo "Restore blocked. Set CONFIRM_RESTORE=yes to continue."
  exit 1
fi

exec "$PYTHON_BIN" \
  "${ROOT_DIR}/scripts/postgres-snapshot.py" \
  restore \
  --project-name "$PROJECT_NAME" \
  --compose-file "$COMPOSE_FILE" \
  --env-file "$ENV_FILE" \
  --snapshot "$BACKUP_FILE" \
  --confirm-restore

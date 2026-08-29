#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROJECT_NAME="${PROJECT_NAME:-sbs-itsm-production}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"

args=(
  backup
  --project-name "$PROJECT_NAME"
  --compose-file "$COMPOSE_FILE"
  --env-file "$ENV_FILE"
)
if [[ -n "${BACKUP_FILE:-}" ]]; then
  args+=(--snapshot "$BACKUP_FILE")
fi

exec "$PYTHON_BIN" "${ROOT_DIR}/scripts/postgres-snapshot.py" "${args[@]}"

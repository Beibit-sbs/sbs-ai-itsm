#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 scripts/runtime-data-backup.py backup \
  --encryption-key-file "${BACKUP_ENCRYPTION_KEY_FILE:-secrets/backup_encryption_key}" \
  "$@"

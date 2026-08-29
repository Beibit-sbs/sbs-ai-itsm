#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-${ROOT_DIR}/.env.production}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" \
  "${ROOT_DIR}/scripts/check-production-env.py" \
  --env-file "$ENV_FILE"

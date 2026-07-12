#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${ROOT_DIR}/backups/data"
OUTPUT_FILE="${BACKUP_DIR}/${TIMESTAMP}_runtime_data.tar.gz"

mkdir -p "$BACKUP_DIR"

candidate_paths=(
  "${ROOT_DIR}/backend/uploads"
  "${ROOT_DIR}/backend/static"
  "${ROOT_DIR}/frontend/dist"
)

existing_paths=()
for path in "${candidate_paths[@]}"; do
  if [[ -d "$path" ]]; then
    existing_paths+=("$path")
  fi
done

if [[ "${#existing_paths[@]}" -eq 0 ]]; then
  echo "No runtime upload/static directories found in repository workspace."
  echo "If using Docker named volumes only, rely on DB/volume backup strategy."
  exit 0
fi

relative_paths=()
for path in "${existing_paths[@]}"; do
  relative_paths+=("${path#${ROOT_DIR}/}")
done

tar -czf "$OUTPUT_FILE" -C "$ROOT_DIR" "${relative_paths[@]}"

echo "Data backup created: $OUTPUT_FILE"

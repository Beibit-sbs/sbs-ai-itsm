#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.production"

ok_count=0
warn_count=0
fail_count=0

status_line() {
  local level="$1"
  local name="$2"
  local note="$3"
  printf '[%s] %s: %s\n' "$level" "$name" "$note"
}

mark_ok() {
  ok_count=$((ok_count + 1))
  status_line "OK" "$1" "$2"
}

mark_warn() {
  warn_count=$((warn_count + 1))
  status_line "WEAK" "$1" "$2"
}

mark_fail() {
  fail_count=$((fail_count + 1))
  status_line "MISSING" "$1" "$2"
}

get_env_value() {
  local key="$1"
  awk -F '=' -v k="$key" '$1==k {sub(/^[[:space:]]+/, "", $2); sub(/[[:space:]]+$/, "", $2); print $2; found=1} END {if (!found) print ""}' "$ENV_FILE"
}

check_required() {
  local key="$1"
  local value
  value="$(get_env_value "$key")"
  if [[ -n "$value" ]]; then
    mark_ok "$key" "set"
  else
    mark_fail "$key" "not set"
  fi
}

if [[ -f "$ENV_FILE" ]]; then
  mark_ok ".env.production" "file exists"
else
  mark_fail ".env.production" "file not found"
  echo "Summary: OK=${ok_count} WEAK=${warn_count} MISSING=${fail_count}"
  exit 1
fi

if git -C "$ROOT_DIR" check-ignore -q .env.production; then
  mark_ok ".env.production git ignore" "ignored"
else
  mark_fail ".env.production git ignore" "not ignored"
fi

required_vars=(
  APP_ENV
  API_V1_PREFIX
  BACKEND_CORS_ORIGINS
  JWT_SECRET_KEY
  DATABASE_URL
  REDIS_URL
  POSTGRES_DB
  POSTGRES_USER
  POSTGRES_PASSWORD
  DEMO_MODE
  RUN_STARTUP_DDL
)

for var in "${required_vars[@]}"; do
  check_required "$var"
done

frontend_port="$(get_env_value FRONTEND_PORT)"
if [[ -n "$frontend_port" ]]; then
  mark_ok "FRONTEND_PORT" "set"
else
  mark_warn "FRONTEND_PORT" "not set, compose default will be used"
fi

backend_port="$(get_env_value BACKEND_PORT)"
if [[ -n "$backend_port" ]]; then
  mark_ok "BACKEND_PORT" "set"
else
  mark_warn "BACKEND_PORT" "not set, compose default will be used"
fi

jwt_secret="$(get_env_value JWT_SECRET_KEY)"
if [[ -z "$jwt_secret" ]]; then
  mark_fail "JWT_SECRET_KEY strength" "empty"
elif [[ "$jwt_secret" == "change-me-in-production" || "$jwt_secret" == "replace-with-strong-random-secret" ]]; then
  mark_warn "JWT_SECRET_KEY strength" "default placeholder"
else
  mark_ok "JWT_SECRET_KEY strength" "non-default"
fi

postgres_password="$(get_env_value POSTGRES_PASSWORD)"
if [[ -z "$postgres_password" ]]; then
  mark_fail "POSTGRES_PASSWORD strength" "empty"
elif [[ "$postgres_password" == "change_me_before_production" || "$postgres_password" == "replace_password" || "$postgres_password" == "sbs_itsm" ]]; then
  mark_warn "POSTGRES_PASSWORD strength" "default/weak"
else
  mark_ok "POSTGRES_PASSWORD strength" "non-default"
fi

demo_mode="$(get_env_value DEMO_MODE)"
if [[ "$demo_mode" == "false" ]]; then
  mark_ok "DEMO_MODE" "false"
else
  mark_warn "DEMO_MODE" "should be false"
fi

startup_ddl="$(get_env_value RUN_STARTUP_DDL)"
if [[ "$startup_ddl" == "false" ]]; then
  mark_ok "RUN_STARTUP_DDL" "false"
else
  mark_warn "RUN_STARTUP_DDL" "should be false"
fi

cors_origins="$(get_env_value BACKEND_CORS_ORIGINS)"
if [[ "$cors_origins" == *"*"* ]]; then
  mark_warn "BACKEND_CORS_ORIGINS" "wildcard detected"
else
  mark_ok "BACKEND_CORS_ORIGINS" "no wildcard"
fi

if docker compose -f "$ROOT_DIR/docker-compose.yml" ps --services --filter status=running | grep -qx postgres; then
  if docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null'; then
    mark_ok "postgres runtime" "reachable"
  else
    mark_warn "postgres runtime" "container running but not ready"
  fi
else
  mark_warn "postgres runtime" "container not running"
fi

if docker compose -f "$ROOT_DIR/docker-compose.yml" ps --services --filter status=running | grep -qx redis; then
  if docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T redis redis-cli ping >/dev/null 2>&1; then
    mark_ok "redis runtime" "reachable"
  else
    mark_warn "redis runtime" "container running but ping failed"
  fi
else
  mark_warn "redis runtime" "container not running"
fi

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  if (cd "$ROOT_DIR/backend" && "$ROOT_DIR/.venv/bin/python" -m alembic heads >/dev/null 2>&1); then
    mark_ok "alembic heads" "available"
  else
    mark_warn "alembic heads" "unavailable in local venv"
  fi
else
  mark_warn "alembic heads" "local venv python missing"
fi

echo "Summary: OK=${ok_count} WEAK=${warn_count} MISSING=${fail_count}"
if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi

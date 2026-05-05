#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STATE_DIR="${SYNTHETOS_DEV_STATE_DIR:-$ROOT/.dev}"
PID_DIR="$STATE_DIR/pids"
LOG_DIR="$STATE_DIR/logs"
API_PORT="${SYNTHETOS_DEV_API_PORT:-8002}"
WEB_PORT="${SYNTHETOS_DEV_WEB_PORT:-5173}"
DEV_HOST="${SYNTHETOS_DEV_HOST:-}"

mkdir -p "$PID_DIR" "$LOG_DIR"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

pid_is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" >/dev/null 2>&1
}

start_service() {
  local name="$1"
  shift
  local pid_file="$PID_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"

  if pid_is_running "$pid_file"; then
    echo "$name already running (pid $(cat "$pid_file"), log $log_file)"
    return
  fi

  rm -f "$pid_file"
  echo "Starting $name (log $log_file)"
  nohup setsid "$@" >"$log_file" 2>&1 </dev/null &
  echo "$!" >"$pid_file"
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"

  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name is ready at $url"
      return
    fi
    sleep 1
  done

  echo "$name did not become ready at $url" >&2
  return 1
}

detect_lan_host() {
  if [[ -n "$DEV_HOST" ]]; then
    echo "$DEV_HOST"
    return
  fi

  local detected=""
  if command -v ip >/dev/null 2>&1; then
    detected="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}')"
  fi
  if [[ -z "$detected" ]] && command -v hostname >/dev/null 2>&1; then
    detected="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi

  echo "${detected:-localhost}"
}

require_cmd docker
require_cmd uv
require_cmd npm
require_cmd curl
require_cmd setsid

LAN_HOST="$(detect_lan_host)"
API_BASE_URL="http://$LAN_HOST:$API_PORT/api/v1"

echo "Starting Postgres"
docker compose up -d postgres

echo "Running database migrations"
uv run synthetos db init

if [[ ! -d "$ROOT/apps/web/node_modules" ]]; then
  echo "Installing frontend dependencies"
  (cd "$ROOT/apps/web" && npm install)
fi

start_service api \
  env LAB_ENV=dev LAB_API_PORT="$API_PORT" \
  uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port "$API_PORT"

wait_for_http api "http://localhost:$API_PORT/health"

start_service worker \
  env LAB_ENV=dev \
  uv run python -m apps.worker

start_service web \
  env VITE_API_BASE_URL="$API_BASE_URL" VITE_ALLOWED_HOSTS="$LAN_HOST,mnemosyne.local" \
  npm --prefix apps/web run dev -- --host 0.0.0.0 --port "$WEB_PORT"

echo
echo "Synthetos dev stack is up."
echo "  Web:  http://localhost:$WEB_PORT"
echo "  LAN:  http://$LAN_HOST:$WEB_PORT"
echo "  API:  http://localhost:$API_PORT/docs"
echo "  API LAN: http://$LAN_HOST:$API_PORT/docs"
echo "  Logs: $LOG_DIR"
echo
echo "Stop it with: scripts/dev-down.sh"

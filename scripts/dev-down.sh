#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STATE_DIR="${SYNTHETOS_DEV_STATE_DIR:-$ROOT/.dev}"
PID_DIR="$STATE_DIR/pids"

stop_pid_file() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"

  if [[ ! -f "$pid_file" ]]; then
    echo "$name is not tracked"
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "$name is not running; removing stale pid file"
    rm -f "$pid_file"
    return
  fi

  echo "Stopping $name (pid $pid)"
  kill -- "-$pid" >/dev/null 2>&1 || kill "$pid" >/dev/null 2>&1 || true

  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      rm -f "$pid_file"
      return
    fi
    sleep 0.5
  done

  echo "$name did not stop gracefully; sending SIGKILL"
  kill -9 -- "-$pid" >/dev/null 2>&1 || kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$pid_file"
}

stop_pid_file web
stop_pid_file worker
stop_pid_file api

echo "Stopping Postgres container without removing volumes"
docker compose stop postgres

echo
echo "Synthetos dev stack is down. Logs remain under $STATE_DIR/logs."

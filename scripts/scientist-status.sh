#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DB_SERVICE="${DB_SERVICE:-postgres}"
DB_USER="${DB_USER:-synthetos}"
DB_NAME="${DB_NAME:-synthetos}"
TAIL_LINES="${TAIL_LINES:-12}"
WATCH_SECONDS=0
CYCLE_ID=""

usage() {
  cat <<'EOF'
Usage:
  scripts/scientist-status.sh [cycle-id]
  scripts/scientist-status.sh --latest
  scripts/scientist-status.sh --watch 30 [cycle-id]

Shows a human-readable snapshot of the autonomous scientist system:
services, worker processes, selected cycle, active/recent jobs, experiment
runs, verification verdicts, artifacts, and a small worker-log tail.

Environment overrides:
  COMPOSE_FILE=docker-compose.yml
  DB_SERVICE=postgres
  DB_USER=synthetos
  DB_NAME=synthetos
  TAIL_LINES=12
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --latest)
      CYCLE_ID=""
      shift
      ;;
    --watch)
      if [[ $# -lt 2 || ! "$2" =~ ^[0-9]+$ ]]; then
        echo "--watch requires a positive integer interval in seconds" >&2
        exit 2
      fi
      WATCH_SECONDS="$2"
      shift 2
      ;;
    --tail)
      if [[ $# -lt 2 || ! "$2" =~ ^[0-9]+$ ]]; then
        echo "--tail requires a non-negative integer line count" >&2
        exit 2
      fi
      TAIL_LINES="$2"
      shift 2
      ;;
    -*)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "$CYCLE_ID" ]]; then
        echo "only one cycle id may be provided" >&2
        exit 2
      fi
      CYCLE_ID="$1"
      shift
      ;;
  esac
done

if [[ -n "$CYCLE_ID" && ! "$CYCLE_ID" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "cycle id must look like a UUID: $CYCLE_ID" >&2
  exit 2
fi

compose=(docker compose -f "$COMPOSE_FILE")

psql_value() {
  local sql="$1"
  "${compose[@]}" exec -T "$DB_SERVICE" \
    psql -X -qAt -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "$sql"
}

psql_table() {
  local sql="$1"
  "${compose[@]}" exec -T "$DB_SERVICE" \
    psql -X -P pager=off -P null='-' -U "$DB_USER" -d "$DB_NAME" \
      -v ON_ERROR_STOP=1 -c "$sql"
}

section() {
  printf '\n== %s ==\n' "$1"
}

strip_ansi() {
  sed -E $'s/\x1b\\[[0-9;]*[A-Za-z]//g'
}

pid_env_value() {
  local pid="$1"
  local key="$2"
  if [[ -r "/proc/$pid/environ" ]]; then
    tr '\0' '\n' <"/proc/$pid/environ" 2>/dev/null \
      | awk -F= -v k="$key" '$1 == k {print substr($0, length(k) + 2); exit}'
  fi
}

latest_cycle_id() {
  psql_value "select id from research_cycles order by created_at desc limit 1;"
}

cycle_clause() {
  printf "cycle_id = '%s'::uuid" "$1"
}

show_services() {
  section "Compose Services"
  if ! "${compose[@]}" ps --format 'table {{.Name}}\t{{.Service}}\t{{.Status}}\t{{.Ports}}' \
      2>/dev/null; then
    "${compose[@]}" ps
  fi
}

show_workers() {
  section "Host Worker Processes"
  shopt -s nullglob
  local pid_files=("$ROOT"/.dev/pids/worker*.pid)
  shopt -u nullglob
  if [[ ${#pid_files[@]} -eq 0 ]]; then
    echo "No .dev worker pid files found."
    return
  fi

  printf '%-44s %-8s %-10s %-38s %s\n' "name" "state" "elapsed" "model_config" "log"
  for pid_file in "${pid_files[@]}"; do
    local name pid log elapsed model_config
    name="$(basename "$pid_file" .pid)"
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    log="$ROOT/.dev/logs/$name.log"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      elapsed="$(ps -p "$pid" -o etime= 2>/dev/null | xargs || true)"
      model_config="$(pid_env_value "$pid" "LAB_MODEL_CONFIG")"
      [[ -z "$model_config" ]] && model_config="$(pid_env_value "$pid" "LAB_MODEL_CONFIG_PATH")"
      printf '%-44s %-8s %-10s %-38s %s\n' \
        "$name" "running" "${elapsed:-?}" "${model_config:--}" "$log"
    else
      printf '%-44s %-8s %-10s %-38s %s\n' "$name" "stale" "-" "-" "$log"
    fi
  done
}

show_worker_config_warnings() {
  local cycle_id="$1"
  local pilot
  pilot="$(psql_value "
    select coalesce(config->'pilot'->>'problem_id', '')
    from research_cycles
    where id = '$cycle_id'::uuid;
  ")"
  [[ -z "$pilot" ]] && return

  shopt -s nullglob
  local pid_files=("$ROOT"/.dev/pids/worker*.pid)
  shopt -u nullglob
  for pid_file in "${pid_files[@]}"; do
    local name pid model_config
    name="$(basename "$pid_file" .pid)"
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      model_config="$(pid_env_value "$pid" "LAB_MODEL_CONFIG")"
      [[ -z "$model_config" ]] && model_config="$(pid_env_value "$pid" "LAB_MODEL_CONFIG_PATH")"
      if [[ -z "$model_config" ]]; then
        echo "Warning: pilot cycle '$pilot' is selected but worker '$name' has no LAB_MODEL_CONFIG set."
      fi
    fi
  done
}

show_cycle() {
  local cycle_id="$1"
  section "Cycle"
  psql_table "
    select
      c.id,
      c.status,
      coalesce(c.config->'pilot'->>'problem_id', '') as pilot,
      ch.title as charter,
      c.created_at,
      c.updated_at,
      c.completed_at
    from research_cycles c
    join research_charters ch on ch.id = c.charter_id
    where c.id = '$cycle_id'::uuid;
  "
}

show_job_status() {
  local cycle_id="$1"
  section "Job Summary"
  psql_table "
    select status, count(*) as jobs
    from jobs
    where $(cycle_clause "$cycle_id")
    group by status
    order by
      case status
        when 'running' then 1
        when 'claimed' then 2
        when 'pending' then 3
        when 'paused' then 4
        when 'failed' then 5
        when 'completed' then 6
        else 9
      end,
      status;
  "

  section "Active Jobs"
  psql_table "
    select
      job_type,
      status,
      coalesce(date_trunc('second', now() - started_at)::text, '-') as runtime,
      attempt_count || '/' || max_attempts as attempts,
      coalesce(left(error, 120), '') as error
    from jobs
    where $(cycle_clause "$cycle_id")
      and status in ('pending', 'claimed', 'running', 'paused')
    order by created_at;
  "

  section "Recent Jobs"
  psql_table "
    select
      to_char(created_at, 'MM-DD HH24:MI:SS') as created,
      job_type,
      status,
      attempt_count || '/' || max_attempts as attempts,
      coalesce(to_char(completed_at, 'HH24:MI:SS'), '') as done,
      coalesce(left(error, 90), '') as error
    from jobs
    where $(cycle_clause "$cycle_id")
    order by created_at desc
    limit 16;
  "
}

show_runs() {
  local cycle_id="$1"
  section "Experiment Runs"
  psql_table "
    select
      r.run_number as run,
      r.status,
      coalesce(v.verdict, '') as verdict,
      coalesce(r.failure_class, '') as failure,
      coalesce(r.exit_code::text, '') as exit,
      coalesce(left(es.title, 48), '') as spec,
      r.id
    from run_records r
    left join experiment_specs es on es.id = r.experiment_spec_id
    left join lateral (
      select verdict
      from verification_reports vr
      where vr.run_record_id = r.id
      order by vr.created_at desc
      limit 1
    ) v on true
    where r.cycle_id = '$cycle_id'::uuid
    order by r.created_at desc
    limit 10;
  "

  section "Recent Verification"
  psql_table "
    select
      to_char(vr.created_at, 'MM-DD HH24:MI:SS') as created,
      vr.verdict,
      left(vr.summary, 120) as summary,
      vr.run_record_id
    from verification_reports vr
    where vr.cycle_id = '$cycle_id'::uuid
    order by vr.created_at desc
    limit 8;
  "
}

show_artifacts() {
  local cycle_id="$1"
  section "Latest Artifacts"
  psql_table "
    select
      'run#' || r.run_number as run,
      artifact->>'name' as name,
      artifact->>'path' as path,
      artifact->>'size_bytes' as bytes
    from run_records r
    cross join lateral jsonb_array_elements(coalesce(r.artifact_manifest, '[]'::jsonb)) artifact
    where r.cycle_id = '$cycle_id'::uuid
    order by r.created_at desc, artifact->>'name'
    limit 20;
  "
}

show_failures() {
  local cycle_id="$1"
  section "Recent Postmortems"
  psql_table "
    select
      to_char(created_at, 'MM-DD HH24:MI:SS') as created,
      failure_class,
      left(root_cause, 100) as root_cause,
      left(coalesce(next_step_recommendation, ''), 100) as next_step,
      run_record_id
    from failure_postmortems
    where cycle_id = '$cycle_id'::uuid
    order by created_at desc
    limit 6;
  "
}

show_latest_log_tail() {
  [[ "$TAIL_LINES" -eq 0 ]] && return
  section "Latest Worker Log Tail"
  shopt -s nullglob
  local logs=("$ROOT"/.dev/logs/worker*.log)
  shopt -u nullglob
  if [[ ${#logs[@]} -eq 0 ]]; then
    echo "No worker logs found under .dev/logs."
    return
  fi
  local latest
  latest="$(ls -t "${logs[@]}" | head -n 1)"
  echo "$latest"
  tail -n "$TAIL_LINES" "$latest" | strip_ansi
}

render_once() {
  if ! "${compose[@]}" exec -T "$DB_SERVICE" pg_isready -U "$DB_USER" -d "$DB_NAME" \
      >/dev/null 2>&1; then
    echo "Postgres is not ready through docker compose service '$DB_SERVICE'."
    echo "Try: docker compose -f $COMPOSE_FILE up -d postgres"
    exit 1
  fi

  local cycle_id="$CYCLE_ID"
  if [[ -z "$cycle_id" ]]; then
    cycle_id="$(latest_cycle_id)"
  fi
  if [[ -z "$cycle_id" ]]; then
    echo "No research cycles found."
    exit 1
  fi

  printf 'Synthetos Scientist Status  %s\n' "$(date -u '+%Y-%m-%d %H:%M:%SZ')"
  printf 'Selected cycle: %s\n' "$cycle_id"

  show_services
  show_workers
  show_worker_config_warnings "$cycle_id"
  show_cycle "$cycle_id"
  show_job_status "$cycle_id"
  show_runs "$cycle_id"
  show_artifacts "$cycle_id"
  show_failures "$cycle_id"
  show_latest_log_tail
}

if [[ "$WATCH_SECONDS" -gt 0 ]]; then
  while true; do
    clear
    render_once
    printf '\nRefreshing every %ss. Ctrl-C to stop.\n' "$WATCH_SECONDS"
    sleep "$WATCH_SECONDS"
  done
else
  render_once
fi

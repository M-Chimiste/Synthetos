#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NO_CACHE=0
PULL=0
GPU=0
RESTART=0
PROD=0
SERVICES=()

usage() {
  cat <<'USAGE'
Usage: scripts/dev-rebuild.sh [options] [service...]

Rebuild Docker Compose images for Synthetos.

Options:
  --no-cache   Build without Docker layer cache.
  --pull       Always attempt to pull newer base images.
  --gpu        Include the gpu profile and experiment-runner image.
  --restart    Restart the Compose stack after a successful build.
  --prod       Use docker-compose.yml only, ignoring docker-compose.override.yml.
  -h, --help   Show this help.

Examples:
  scripts/dev-rebuild.sh
  scripts/dev-rebuild.sh --no-cache api worker
  scripts/dev-rebuild.sh --gpu experiment-runner
  scripts/dev-rebuild.sh --restart
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-cache)
      NO_CACHE=1
      ;;
    --pull)
      PULL=1
      ;;
    --gpu)
      GPU=1
      ;;
    --restart)
      RESTART=1
      ;;
    --prod)
      PROD=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        SERVICES+=("$1")
        shift
      done
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      SERVICES+=("$1")
      ;;
  esac
  shift
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Missing required command: docker" >&2
  exit 1
fi

COMPOSE=(docker compose)
if [[ "$PROD" -eq 1 ]]; then
  COMPOSE+=(-f docker-compose.yml)
fi
if [[ "$GPU" -eq 1 ]]; then
  COMPOSE+=(--profile gpu)
fi

BUILD_ARGS=(build)
if [[ "$NO_CACHE" -eq 1 ]]; then
  BUILD_ARGS+=(--no-cache)
fi
if [[ "$PULL" -eq 1 ]]; then
  BUILD_ARGS+=(--pull)
fi
if [[ "${#SERVICES[@]}" -gt 0 ]]; then
  BUILD_ARGS+=("${SERVICES[@]}")
fi

echo "Rebuilding Docker images"
printf '  %q' "${COMPOSE[@]}" "${BUILD_ARGS[@]}"
echo
"${COMPOSE[@]}" "${BUILD_ARGS[@]}"

if [[ "$RESTART" -eq 1 ]]; then
  echo
  echo "Restarting Compose stack"
  "${COMPOSE[@]}" up -d "${SERVICES[@]}"
fi

echo
echo "Rebuild complete."

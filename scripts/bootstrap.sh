#!/usr/bin/env bash
set -euo pipefail

uv sync
docker compose up -d postgres
uv run alembic upgrade head || true
echo "Phase 0 bootstrap complete."


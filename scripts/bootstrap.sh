#!/usr/bin/env bash
set -euo pipefail

uv sync
docker compose up -d postgres
uv run alembic upgrade head
echo "Semantic-search bootstrap complete."

# Synthetos Python orchestration image (API + worker share this)
#
# Build: docker build -t synthetos:latest .
# Run as API:    uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
# Run as worker: python -m apps.worker
#
# The compose file sets per-service `command:` so a single image serves both.

# ---------- builder ----------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Cache deps install separately from project source for fast iteration.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy the project source last (changes invalidate cache least often).
COPY apps/ ./apps/
COPY libs/ ./libs/
COPY configs/ ./configs/
COPY skills/ ./skills/
COPY prompts/ ./prompts/
COPY alembic.ini README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

# Native libs that docling / PDF processing depend on at runtime.
# Kept minimal; OCR (tesseract) is omitted — text-extraction PDFs only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user. UID/GID 1000 matches typical host devs and lets
# bind-mounted source in dev mode keep sane ownership.
ARG SYNTHETOS_UID=1000
ARG SYNTHETOS_GID=1000
RUN groupadd --system --gid ${SYNTHETOS_GID} synthetos \
    && useradd --system --uid ${SYNTHETOS_UID} --gid ${SYNTHETOS_GID} \
       --shell /bin/bash --home-dir /app synthetos

WORKDIR /app

COPY --from=builder --chown=synthetos:synthetos /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER synthetos

# No CMD — compose's `command:` selects api vs worker.

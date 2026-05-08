# syntax=docker/dockerfile:1

# ── builder stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq5 libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

# ── runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

COPY backend/ ./backend/
COPY manage.py ./
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh

RUN useradd --system --uid 1001 app \
    && chown -R app:app /app

USER app

EXPOSE 8000

ENTRYPOINT ["/app/scripts/entrypoint.sh"]

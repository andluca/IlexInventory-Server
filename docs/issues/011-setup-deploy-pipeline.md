# 011 — Setup deploy pipeline (Docker, target host, CI)

## Overview

Production deployment: Dockerfile, docker-compose for the prod target (Fly.io / Railway / Render — TBD), CI pipeline running the full validation gates, env-var fail-fast verification.

**Scope:**
- `Dockerfile` (multi-stage build for the BE: deps install, copy code, run migrations on start, run `gunicorn` or equivalent)
- `docker-compose.yml` for prod target (BE + Postgres) — distinct from the dev compose already present
- CI pipeline (GitHub Actions): pytest, mypy, ruff, no-ORM grep, no-SQL-outside-queries grep, no-floats grep, OpenAPI drift check
- Migration runner on container start (`python -m backend.migrate` or equivalent)
- Env-var fail-fast: app refuses to start if required vars missing
- Smoke: container boots, `/api/v1/health` returns 200 against Dockerized Postgres
- Pick deploy target (Fly.io / Railway / Render); commit the platform-specific config

**Reference:** SPEC §2.9, §4 (Validation Gates).

**Depends on:** 010.

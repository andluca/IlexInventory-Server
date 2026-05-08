---
id: ILEX-011
github_id: null
status: open
assignee: null
state: Queued
type: item
depends_on: [ILEX-010]
---

# ILEX-011 Setup deploy pipeline (Docker, target host, CI)

Production deployment: Dockerfile, docker-compose for the prod target (Fly.io / Railway / Render — TBD), CI pipeline running the full validation gates, env-var fail-fast verification.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.9, §4 (Validation Gates).

## Scope

- `Dockerfile` (multi-stage build for the BE: deps install, copy code, run migrations on start, run `gunicorn` or equivalent)
- `docker-compose.yml` for prod target (BE + Postgres) — distinct from the dev compose already present
- CI pipeline (GitHub Actions): pytest, mypy, ruff, no-ORM grep, no-SQL-outside-queries grep, no-floats grep, OpenAPI drift check
- Migration runner on container start (`python manage.py migrate_sql`)
- Env-var fail-fast: app refuses to start if required vars missing
- Smoke: container boots, `/api/v1/health` returns 200 against Dockerized Postgres
- Pick deploy target (Fly.io / Railway / Render); commit the platform-specific config

## Dependencies

1. ILEX-010 (OpenAPI handoff complete; deploys land with the FE-consumable schema in place)

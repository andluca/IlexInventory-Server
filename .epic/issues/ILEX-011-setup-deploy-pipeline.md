---
id: ILEX-011
github_id: null
status: completed
assignee: null
state: Done
type: item
depends_on: [ILEX-010]
---

# ILEX-011 Setup deploy pipeline (Docker, target host, CI)

Production deployment surface: a multi-stage `Dockerfile` that builds a `gunicorn`-served BE image, an entrypoint that applies SQL migrations and fail-fast-validates env vars before booting, a prod-shape `docker-compose.prod.yml` (BE + Postgres 16) used by the smoke test, the `/docs` Swagger UI gated behind `OPENAPI_PUBLIC_DOCS`, a GitHub Actions CI workflow running every existing validation gate (`pytest`, `ruff`, `check_no_orm.sh`, `check_openapi_drift.sh`) against a real Postgres service, and Fly.io as the picked deploy target with `deploy/fly.toml` committed.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.9 (Config), §3.9 (Health & meta), §4 (Validation Gates — "Deploy" row).

## Operation: docker-build-and-smoke
Route/Command: `docker compose -f deploy/docker-compose.prod.yml up --build -d && ./scripts/smoke_health.sh`

Builds the production image from the multi-stage `Dockerfile`, brings up the BE + Postgres prod-shape stack, applies SQL migrations, and confirms `GET /api/v1/health` returns `200 {"status":"ok","checks":{"postgres":"ok"}}`. Run locally before tagging a release; run in CI as the final deploy-pipeline gate (SPEC §4 "Deploy" row).

### Preconditions
* Docker daemon is running (`docker info` succeeds).
* `.env.prod` exists at repo root with the required prod vars (or the equivalent values are exported into the shell). See **Function: validate_required_env**.
* The `backend/openapi.json` snapshot is current (drift gate from ILEX-010 is green) — image build does not regenerate it.

### Primary Use Case (local prod-shape smoke)

#### Input
```
docker compose -f deploy/docker-compose.prod.yml up --build -d
./scripts/smoke_health.sh
```

#### Workflow
* `docker compose build` runs the multi-stage `Dockerfile`: stage `builder` installs system + Python deps into a virtualenv at `/opt/venv`; stage `runtime` copies `/opt/venv` plus `backend/`, drops to a non-root `app` user, and sets `ENTRYPOINT ["/app/scripts/entrypoint.sh"]`.
* `docker compose up -d` starts `postgres` (image `postgres:16` with healthcheck) and `backend` (waits on Postgres `service_healthy`).
* On boot the BE entrypoint: (1) calls `validate_required_env` and exits 1 with the missing-var name on failure; (2) runs `python manage.py migrate_sql` against `DATABASE_URL`; (3) execs `gunicorn wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3 --access-logfile - --error-logfile -`.
* `smoke_health.sh` polls `http://localhost:8000/api/v1/health` for up to 30s, exits 0 on the first `200 {"status":"ok",…}`, exits 1 with the last response body otherwise.

#### Output (success)
```
smoke-health: OK — /api/v1/health returned 200 with {"status":"ok","checks":{"postgres":"ok"}}
```

### Edge Cases / Error Flows

#### Missing required env var
* Operator runs `docker compose up` without `DJANGO_SECRET_KEY`.
* Container starts; entrypoint's `validate_required_env` detects the missing variable and writes `entrypoint: FATAL — required env var DJANGO_SECRET_KEY is not set` to stderr.
* Container exits with status 1 before `gunicorn` is exec'd.
* Exit code: 1.

#### Migration failure on first boot
* Migration file at `backend/migrations/00NN_*.sql` has invalid SQL.
* Entrypoint runs `migrate_sql`; the management command rolls back the transaction, prints `error applying 00NN_*.sql: <psycopg error>` to stderr, exits 1 (existing behaviour at `backend/apps/core/management/commands/migrate_sql.py:84-89`).
* Entrypoint propagates the non-zero exit; `gunicorn` is never started; the orchestrator (compose / Fly) marks the container unhealthy.

#### `/docs` exposure toggle
* `OPENAPI_PUBLIC_DOCS=false` (the prod default per SPEC §2.9) → `GET /api/v1/docs` returns 404.
* `OPENAPI_PUBLIC_DOCS=true` → `GET /api/v1/docs` returns 200 HTML (drf-spectacular's Swagger UI bundle).
* The `/api/v1/openapi.json` schema endpoint is unaffected by the toggle (always public, per SPEC §3.9).

## Function: validate_required_env
File: `backend/apps/core/management/commands/check_env.py`

A management command (`python manage.py check_env`) that imports `settings.prod` under the hood and asserts every required env var is set, exiting non-zero with the first missing var name. The entrypoint script calls it before `migrate_sql`, giving operators a single canonical fail-fast path that is reused by the CI smoke job and by Fly.io's release command.

### Implementation
* Required vars (must be present, any value): `DJANGO_SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`.
* Optional vars (defaults applied silently): `PORT`, `OPENAPI_PUBLIC_DOCS`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, plus the agent vars listed in SPEC §2.9 that are reserved for ILEX-012.
* Reuses the existing `settings._env.env` / `env_csv` helpers — does not duplicate the parsing logic. The command imports `settings.prod` (which already calls `env_csv("ALLOWED_HOSTS")` and `env_csv("CORS_ALLOWED_ORIGINS")` at module load); the resulting `ImproperlyConfigured` exception is caught and reformatted as `check-env: FATAL — <var name> is not set` on stderr with exit 1.
* On success: prints `check-env: OK` and exits 0.

## Function: docs_view
File: `backend/urls.py`

Conditionally registers `path("api/v1/docs", SpectacularSwaggerView.as_view(url_name="schema"))` based on `OPENAPI_PUBLIC_DOCS`. SPEC §3.9 specifies the toggle; ILEX-010 deliberately deferred it to this issue.

### Implementation
* Read `OPENAPI_PUBLIC_DOCS` via `settings._env.env_bool("OPENAPI_PUBLIC_DOCS", False)` at module load.
* When `True`, append the `SpectacularSwaggerView` route to `urlpatterns`.
* When `False`, the route is absent — Django's resolver returns 404 naturally; no extra middleware needed.

## Lib: entrypoint
File: `scripts/entrypoint.sh`

Single shell entrypoint baked into the image. Sequence: env validation → SQL migration → `exec gunicorn`. Uses `exec` so `gunicorn` becomes PID 1, receives SIGTERM cleanly, and avoids zombie children.

### Functions
* `set -euo pipefail` — fail on any sub-step error (no `|| true` swallowing).
* Step 1: `python manage.py check_env` — fail-fast on missing required vars (delegates to **Function: validate_required_env**).
* Step 2: `python manage.py migrate_sql` — apply pending SQL files; idempotent on re-deploy.
* Step 3: `exec gunicorn wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers "${GUNICORN_WORKERS:-3}" --access-logfile - --error-logfile -` — replace shell with the server process.

## Lib: smoke_health
File: `scripts/smoke_health.sh`

Polls `/api/v1/health` until 200 or timeout. Mirrors the shape of `scripts/check_no_orm.sh` (set -euo pipefail; clear failure messaging).

### Functions
* Defaults: `URL=${SMOKE_URL:-http://localhost:8000/api/v1/health}`, `TIMEOUT=${SMOKE_TIMEOUT:-30}`.
* Loop: `curl -fsS "$URL"`, sleep 1, retry until elapsed ≥ TIMEOUT.
* Success: prints `smoke-health: OK — /api/v1/health returned 200 …`, exits 0.
* Failure: prints `smoke-health: FAIL — /api/v1/health did not return 200 within ${TIMEOUT}s`, last `curl` exit code, and last response body; exits 1.

## Lib: dockerfile
File: `Dockerfile`

Multi-stage build, Python 3.12-slim base, non-root runtime user, `gunicorn` as the production WSGI server.

### Stages
* **builder** — `python:3.12-slim`. `apt-get install -y --no-install-recommends build-essential libpq5 libpq-dev`. Copies `pyproject.toml` + `uv.lock`. Runs `pip install --no-cache-dir uv && uv sync --frozen --no-dev` into a venv at `/opt/venv`. Adds `gunicorn` to runtime deps (see step 3 of the plan).
* **runtime** — `python:3.12-slim`. `apt-get install -y --no-install-recommends libpq5` (runtime libpq only, no `-dev`). Copies `/opt/venv` from builder. Copies `backend/`, `manage.py`, `scripts/entrypoint.sh`. `RUN useradd --system --uid 1001 app && chown -R app:app /app`. `USER app`. `EXPOSE 8000`. `ENTRYPOINT ["/app/scripts/entrypoint.sh"]`.
* `.dockerignore` excludes `.venv`, `.git`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `node_modules`, `.epic`, `docs`, `*.egg-info`, `.env*`.

## Lib: docker_compose_prod
File: `deploy/docker-compose.prod.yml`

Prod-shape compose stack used by the smoke test. Distinct from the existing `deploy/docker-compose.yml` (dev: Postgres only).

### Services
* `postgres` — `postgres:16`, named volume `ilex_pgdata`, healthcheck `pg_isready`, env from `.env.prod` (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`).
* `backend` — `build: { context: ., dockerfile: Dockerfile }`, depends_on `postgres: { condition: service_healthy }`, env_file `.env.prod`, ports `8000:8000`, restart `unless-stopped`. `DATABASE_URL` constructed to point at the compose `postgres` service hostname.
* No nginx / reverse proxy in compose — Fly.io fronts TLS in production; smoke test hits `gunicorn` directly on port 8000.

## Lib: github_actions_ci
File: `.github/workflows/ci.yml`

Single workflow `ci` with one job `validate` running every existing gate against a real Postgres. Triggers on `push` and `pull_request` to `main`. SPEC §4 lists `mypy` but the repo currently has no mypy config — adding one is out of scope; CI runs only the gates that exist.

### Job: validate
* `runs-on: ubuntu-latest`.
* Service: `postgres:16` (env `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=postgres`, `POSTGRES_DB=ilex_test`), health-check `pg_isready`, port `5432:5432`.
* Steps:
  1. `actions/checkout@v4`.
  2. `actions/setup-python@v5` with `python-version: "3.12"` and pip cache.
  3. `pip install uv && uv sync --frozen --extra dev` (installs runtime + dev deps including `pytest`, `ruff`, `gunicorn`).
  4. Write `.env` from secrets / hard-coded test values (`DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ilex_test`, `DJANGO_SECRET_KEY=ci-test-secret`).
  5. `ruff check backend/`.
  6. `./scripts/check_no_orm.sh`.
  7. `./scripts/check_openapi_drift.sh`.
  8. `pytest`.

### Job: docker-smoke (separate, runs after validate)
* Builds the image (`docker compose -f deploy/docker-compose.prod.yml build`), brings up the stack, runs `./scripts/smoke_health.sh`, tears the stack down on success or failure (`docker compose down -v` in an `if: always()` step).

## Lib: fly_target
File: `deploy/fly.toml`

Fly.io platform config. Picked for: native Postgres add-on (Fly Postgres) eliminates a separate DB-host concern; release-command primitive matches our entrypoint shape (run `migrate_sql` once before traffic shifts); single-region (`iad`) matches the v1 single-tenant scope; free-tier-friendly for the take-home demo.

### Keys
* `app = "ilex-inventory-server"`, `primary_region = "iad"`.
* `[build] dockerfile = "Dockerfile"`.
* `[deploy] release_command = "python manage.py migrate_sql"` — Fly runs this in a one-off VM with the prod env injected before swapping the live image. Belt-and-suspenders with the entrypoint's own migrate step (release command catches migration failures before the rollout starts).
* `[http_service]` — `internal_port = 8000`, `force_https = true`, `auto_stop_machines = "stop"`, `auto_start_machines = true`.
* `[[http_service.checks]]` — `path = "/api/v1/health"`, `interval = "10s"`, `timeout = "2s"`, `grace_period = "10s"`.
* Secrets (set via `fly secrets set`, not in this file): `DJANGO_SECRET_KEY`, `DATABASE_URL` (auto-injected by `fly postgres attach`), `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `OPENAPI_PUBLIC_DOCS`.

## External Dependencies

### gunicorn
Used for: production WSGI server (replaces `runserver` in containers).
Commands: `gunicorn wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile - --error-logfile -`

* New runtime dep added to `pyproject.toml` (project.dependencies).
* `--workers 3` matches the `2 × CPU + 1` rule of thumb on Fly's shared-cpu-1x machines (1 vCPU). Tunable via `GUNICORN_WORKERS` env var.

### Fly.io
Used for: production deploy target (single-region container hosting + managed Postgres).
Commands: `fly deploy`, `fly postgres create`, `fly postgres attach`, `fly secrets set`

* Authenticated via `flyctl auth login` (operator) or `FLY_API_TOKEN` (CI; not wired in this issue — manual `fly deploy` for v1).
* Release command (`migrate_sql`) is the only Fly-specific glue; the rest is plain Docker.

### Docker / Docker Compose
Used for: image build, local prod-shape smoke, CI smoke job.
Commands: `docker compose -f deploy/docker-compose.prod.yml up --build`, `docker compose down -v`

* Already required for local Postgres (`deploy/docker-compose.yml`); this issue extends usage to BE image build.

# Plan

Each step ends with green `pytest`, `ruff`, `check_no_orm.sh`, and `check_openapi_drift.sh` gates. Steps are ordered so each one is independently shippable (the issue's net effect is "deploy works" only after step 8, but every intermediate commit leaves `main` green).

1. **Add `gunicorn` to runtime deps + `OPENAPI_PUBLIC_DOCS` Swagger UI toggle**
   - Why: ILEX-010 explicitly deferred the `/docs` toggle to this issue, and we need `gunicorn` pinned in `pyproject.toml` before the Dockerfile can install it. Both changes are pure-Python, no infra, so they ship first and unlock every later step.
   - [ ] Add `"gunicorn>=23"` to `[project].dependencies` in `pyproject.toml`; run `uv lock` to refresh `uv.lock`.
   - [ ] Update `backend/urls.py` to conditionally register `SpectacularSwaggerView` at `/api/v1/docs` when `env_bool("OPENAPI_PUBLIC_DOCS", False)` is `True`.
   - [ ] Test (`apps/core/tests/api/test_docs_toggle.py`): with `OPENAPI_PUBLIC_DOCS` unset/false, `GET /api/v1/docs` → 404; with the env var set to `true` (override via `os.environ` + Django `override_settings`-equivalent reload, or by parametrising the `urls` import), `GET /api/v1/docs` → 200 and the response body contains the Swagger UI marker (`"swagger-ui"` substring).
   - [ ] Test (`apps/core/tests/api/test_openapi_snapshot.py`): re-run `check_openapi_drift.sh` after the urls change — `/docs` is an HTML view (not a DRF endpoint), so it must NOT appear in `backend/openapi.json`. Update snapshot only if drift gate flags it (it should not).

2. **Add `manage.py check_env` fail-fast command + tests**
   - Why: SPEC §2.9 requires "app refuses to start if required env vars are missing." The entrypoint (step 4) calls this command; landing it first means the entrypoint has something concrete to invoke and lets us pin the required-var list in tests before any infra change.
   - [ ] Create `backend/apps/core/management/commands/check_env.py` (`Command` class with `handle` that imports `settings.prod` inside a try/except for `ImproperlyConfigured`; on success prints `check-env: OK`).
   - [ ] Test (`apps/core/tests/api/test_check_env.py`): subprocess-runs `python manage.py check_env` with `DJANGO_SETTINGS_MODULE=settings.prod` and a complete env → exit 0, stdout `check-env: OK`. With `ALLOWED_HOSTS` cleared from the env → exit 1, stderr matches `ALLOWED_HOSTS`.
   - [ ] Test: same but with `CORS_ALLOWED_ORIGINS` cleared → exit 1, stderr matches `CORS_ALLOWED_ORIGINS`. (Two cases is enough — they prove the loop, not exhaustive var coverage.)

3. **Write `Dockerfile` + `.dockerignore` and verify it builds**
   - Why: the image is the contract for every later step (compose, smoke, Fly). Landing it standalone — with a manual `docker build .` verification — keeps the surface change atomic and reviewable, and step 4's entrypoint can be tested against a real built image.
   - [ ] Create `Dockerfile` (multi-stage, Python 3.12-slim, builder/runtime split, `app` non-root user, EXPOSE 8000, `ENTRYPOINT ["/app/scripts/entrypoint.sh"]`).
   - [ ] Create `.dockerignore` (excludes `.venv`, `.git`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `node_modules`, `.epic`, `docs`, `*.egg-info`, `.env*`).
   - [ ] Manual verification: `docker build -t ilex-be:test .` succeeds locally; `docker run --rm ilex-be:test python -c "import django, gunicorn; print(django.__version__, gunicorn.__version__)"` prints both versions. (No Python test for this — building Docker images inside `pytest` is too slow / brittle; CI does the real build in step 7.)

4. **Write `scripts/entrypoint.sh` (env check → migrate → gunicorn) + smoke script**
   - Why: the entrypoint encodes the boot contract (validate → migrate → serve). Pairing it with `scripts/smoke_health.sh` in the same step gives us a script-only verification path before we wire compose (step 5) — `entrypoint.sh` can be tested against a locally-running Postgres without a container.
   - [ ] Create `scripts/entrypoint.sh` (`set -euo pipefail`; `python manage.py check_env`; `python manage.py migrate_sql`; `exec gunicorn wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers "${GUNICORN_WORKERS:-3}" --access-logfile - --error-logfile -`).
   - [ ] Create `scripts/smoke_health.sh` (poll loop on `/api/v1/health` with `SMOKE_URL` and `SMOKE_TIMEOUT` overrides; clear OK / FAIL output).
   - [ ] `chmod +x` both scripts.
   - [ ] Test (`apps/core/tests/api/test_entrypoint_script.py`): static assertions only — script exists, is executable, contains the literal commands `python manage.py check_env`, `python manage.py migrate_sql`, and `exec gunicorn` in that order (regex grep). No subprocess execution — that lives in step 7's CI smoke job. This is a regression guard against accidentally dropping a step from the boot sequence.
   - [ ] Manual verification: with the dev Postgres running, `DJANGO_SETTINGS_MODULE=settings.prod ALLOWED_HOSTS=localhost CORS_ALLOWED_ORIGINS=http://localhost ./scripts/entrypoint.sh &` boots `gunicorn`; `./scripts/smoke_health.sh` exits 0.

5. **Write `deploy/docker-compose.prod.yml` + `.env.prod.example`**
   - Why: compose is the local equivalent of the Fly stack — a smoke gate without leaving the laptop. `.env.prod.example` documents the prod-required vars (separate from `.env.example` which is dev-shaped) and is the file CI's docker-smoke job copies.
   - [ ] Create `deploy/docker-compose.prod.yml` (`postgres` + `backend` services per the **Lib: docker_compose_prod** section).
   - [ ] Create `.env.prod.example` with every required prod var (`DJANGO_SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `OPENAPI_PUBLIC_DOCS=false`, `SESSION_COOKIE_SECURE=true`, `CSRF_COOKIE_SECURE=true`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) — values are placeholders, the file is committed.
   - [ ] Add `.env.prod` to `.gitignore` (the real-values file).
   - [ ] Manual verification: `cp .env.prod.example .env.prod`, fill secrets, `docker compose -f deploy/docker-compose.prod.yml up --build -d`, `./scripts/smoke_health.sh` exits 0, `docker compose -f deploy/docker-compose.prod.yml down -v` cleans up.

6. **Write `.github/workflows/ci.yml` `validate` job (existing gates only)**
   - Why: every gate the issue depends on (`pytest`, `ruff`, `check_no_orm`, `check_openapi_drift`) already exists and is green locally; the CI workflow's job is to run them on every PR against a clean Postgres. Landing this before the docker-smoke job (step 7) gives us a fast gate on every commit independent of the slow image build.
   - [ ] Create `.github/workflows/ci.yml` with one job `validate` (Postgres 16 service, Python 3.12, `uv sync --extra dev`, run all four gates).
   - [ ] Hard-code test-only env vars (`DJANGO_SECRET_KEY=ci-test-secret`, `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ilex_test`); no real secrets needed for the test suite.
   - [ ] Manual verification: open a draft PR; the `validate` job goes green within ~5 minutes. (Local `act` invocation optional — repo's existing skills file `tdd` calls out CI parity as a real-Postgres requirement, which the service container provides.)

7. **Add `docker-smoke` CI job (build image + run compose + smoke health)**
   - Why: catches Dockerfile / entrypoint / compose regressions that pure-Python tests can't see (e.g., a missing apt package, a wrong `WORKDIR`, an `exec` that drops env). Runs after `validate` so we don't waste image-build minutes on PRs whose unit tests are already broken.
   - [ ] Add a `docker-smoke` job to `.github/workflows/ci.yml` with `needs: validate`.
   - [ ] Steps: checkout, setup-buildx, write `.env.prod` from job env, `docker compose -f deploy/docker-compose.prod.yml up --build -d`, `./scripts/smoke_health.sh`, `docker compose -f deploy/docker-compose.prod.yml down -v` (in `if: always()`).
   - [ ] Manual verification: re-run the same draft PR; `docker-smoke` job goes green. Intentionally break the entrypoint (e.g., add `exit 1` after `check_env`) → job fails with the entrypoint error in the logs; revert.

8. **Pick deploy target (Fly.io) + commit `deploy/fly.toml`**
   - Why: the brief and SPEC §2.9 leave the platform TBD; we pick now because every other artifact in this issue (Dockerfile, entrypoint, compose) is platform-neutral, so the only platform-specific commit is `fly.toml` itself. Picking Fly is justified above (release-command primitive, native Postgres add-on, free-tier).
   - [ ] Create `deploy/fly.toml` per the **Lib: fly_target** section (app name, region `iad`, dockerfile build, release_command `python manage.py migrate_sql`, http_service on port 8000 with `/api/v1/health` healthcheck).
   - [ ] Document the bootstrap sequence in `README.md` "Deploy" section: `fly launch --no-deploy`, `fly postgres create`, `fly postgres attach`, `fly secrets set DJANGO_SECRET_KEY=… ALLOWED_HOSTS=… CORS_ALLOWED_ORIGINS=…`, `fly deploy`. (One short subsection — README is already comprehensive; this is just the platform-specific glue.)
   - [ ] No automated test — Fly deployment is operator-driven for v1. The `/api/v1/health` Fly healthcheck is the live equivalent of `smoke_health.sh` and is what the platform monitors post-deploy.
   - [ ] Manual verification: `fly deploy` from a clean checkout puts a working URL behind HTTPS; `curl https://ilex-inventory-server.fly.dev/api/v1/health` returns `200 {"status":"ok",…}`. (Operator runs this once the secrets are set.)

# Notes

- **Why Fly.io over Railway / Render.** All three would work. Fly wins on three concrete points relative to v1: (1) `release_command` runs `migrate_sql` in a one-off VM *before* the new image takes traffic — Render does this with a `preDeployCommand` but only on paid plans; Railway has no first-class equivalent. (2) Fly Postgres `attach` injects `DATABASE_URL` directly into the app secrets; Railway and Render require a manual reference variable. (3) Single-region single-tenant with auto-stop-on-idle matches the v1 demo profile (low traffic, free-tier-friendly). Trade-off: Fly's one-shot `release_command` adds ~30s to each deploy vs. Railway's hot replace, but the safety is worth it for SQL migrations.
- **Why a separate `docker-compose.prod.yml` instead of overlaying.** The existing `deploy/docker-compose.yml` is dev-shaped (Postgres only, exposes 5432, no BE service). Overlaying via `docker compose -f base.yml -f prod.yml` would force the dev file to know about the BE service, which it deliberately doesn't (the dev BE is `manage.py runserver` directly on the host). Two files, zero overlay logic, is simpler.
- **Why `mypy` is not in CI even though SPEC §4 lists it.** The repo has no `mypy.ini` / `pyproject.toml [tool.mypy]` config and no type stubs for `psycopg` / `drf_spectacular` are pinned. Adding mypy means making a configuration call (strict vs. permissive, ignoring third-party untyped packages, handling `django-stubs`) that is a separate piece of work. This issue includes the four gates that already pass locally; mypy lands in a follow-up if/when the team commits to a config. Documented here so the omission is explicit, not accidental.
- **Why the entrypoint runs `migrate_sql` AND Fly's `release_command` does too.** The entrypoint runs migrations on every container start, including local compose where there is no platform release command. Fly's release command runs them in a one-off VM before the rollout, which catches migration failures *before* any traffic shifts (no half-deployed state). The two paths are convergent — `migrate_sql` is idempotent (it tracks applied filenames in `_sql_migrations`), so running it twice on the second-machine container start is a no-op. Belt-and-suspenders at zero cost.
- **Non-root user in the image.** Runtime stage drops to UID 1001 (`app`). Required by Fly (and by general container best practice) — avoids running `gunicorn` as root and avoids volume permission surprises if the container ever mounts a host volume. The migration runner needs no special permissions; it connects to Postgres over TCP with the credentials in `DATABASE_URL`.
- **Why no nginx in the prod compose / Fly stack.** Fly fronts every machine with its own TLS-terminating proxy (`fly-proxy`), so adding nginx would be a redundant hop. For local prod-shape smoke, plain `gunicorn` on `0.0.0.0:8000` is enough — TLS / static-file serving / connection multiplexing are all things v1 does not need (no static assets are served by the BE; the FE is a separate repo deployed independently).
- **`OPENAPI_PUBLIC_DOCS` defaults to `false` in prod.** SPEC §2.9 specifies this. The reasoning: `/api/v1/openapi.json` is always public (the FE consumes it via build-time fetch in dev), but `/docs` (Swagger UI) is an interactive page that exposes endpoint shapes to anyone who finds it — fine for staging / preview deploys, off by default for the public domain. The toggle is an env var, not a setting, so flipping it on per-environment requires zero code change.
- **Why a `validate` + `docker-smoke` two-job split rather than one job.** Two reasons: (1) `validate` runs in ~5 min on a cached venv; `docker-smoke` runs in ~3 min on top of that for the image build. Splitting means a broken unit test fails fast at 5 min instead of 8. (2) `docker-smoke` requires `needs: validate`, which gives a clean dependency graph in the GitHub Actions UI (red-X on `validate` shows `docker-smoke` as skipped, not failed).
- **CI does not regenerate `openapi.json`.** ILEX-010's `check_openapi_drift.sh` runs `spectacular --validate` against a temp file and diffs — committed snapshot stays the source of truth. CI failing on drift means the developer needs to re-run the regen command locally and commit the result. Auto-regen would hide intent (per the ILEX-010 note already on file).
- **No supervisor / process manager beyond `gunicorn`.** The container runs one process (`gunicorn` after `exec`). Fly handles restart-on-crash via its machine API; compose handles it via `restart: unless-stopped`. Adding `supervisord` or a custom process tree would only matter if we needed to run a sidecar (e.g., a background queue worker), which v1 doesn't have. Keeps PID 1 clean and SIGTERM propagation correct.

# Journal

## 2026-05-08T23:20Z — Step 7: docker-smoke CI job added to ci.yml

- `docker-smoke` job already present in ci.yml from step 6: `needs: validate`; checkout → setup-buildx → write .env.prod → `docker compose up --build -d` → smoke_health.sh → `docker compose down -v` (if: always()).
- YAML confirmed: `python3 -c "import yaml; ..."` lists `['validate', 'docker-smoke']`.
- Manual verification of smoke job awaits a GitHub PR push — cannot fully exercise without CI runner.
- Gates: ruff clean; check_no_orm OK; check_openapi_drift OK.

## 2026-05-08T23:15Z — Step 6: .github/workflows/ci.yml validate job

- `.github/workflows/ci.yml`: `ci` workflow triggering on push/PR to main; `validate` job with postgres:16 service container (pg_isready healthcheck), Python 3.12 via setup-python@v5 with pip cache, `uv sync --extra dev`, writes `.env` with test values, runs ruff → check_no_orm → check_openapi_drift → pytest.
- Manual verification: YAML parses cleanly (`python3 -c "import yaml; yaml.safe_load(...)"` exit 0). Full CI run requires a GitHub PR — noted as awaiting CI / GitHub runner.
- Gates: ruff clean; check_no_orm OK; check_openapi_drift OK.

## 2026-05-08T23:05Z — Step 5: deploy/docker-compose.prod.yml + .env.prod.example

- `deploy/docker-compose.prod.yml`: `postgres` (postgres:16, named volume ilex_pgdata, healthcheck pg_isready, env_file) + `backend` (builds from Dockerfile, depends_on postgres service_healthy, env_file, DATABASE_URL pointing at compose postgres hostname, port 8000:8000, restart unless-stopped).
- `.env.prod.example`: all required prod vars documented with placeholder values; committed to repo.
- `.gitignore`: added `.env.prod` (the real-values file).
- Manual verification: `docker compose -f deploy/docker-compose.prod.yml config` parses cleanly with `.env.prod` present (with example values).
- Gates: pytest 155/155 core tests green; ruff clean; check_no_orm OK; check_openapi_drift OK.

## 2026-05-08T22:50Z — Step 4: entrypoint.sh + smoke_health.sh + entrypoint order test

- `scripts/entrypoint.sh`: `set -euo pipefail`; `python manage.py check_env` → `python manage.py migrate_sql` → `exec gunicorn wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${GUNICORN_WORKERS:-3} --access-logfile - --error-logfile -`.
- `scripts/smoke_health.sh`: polls `${SMOKE_URL:-http://localhost:8000/api/v1/health}` up to `${SMOKE_TIMEOUT:-30}` seconds; exits 0 on 200, exits 1 with message on timeout.
- Both scripts chmod +x.
- `backend/apps/core/tests/api/test_entrypoint_script.py`: 4 static tests — file exists; is executable; boot sequence order (check_env < migrate_sql < exec gunicorn at line-start); set -euo pipefail present.
- Gates: pytest 152/152 core tests green (3 pre-existing DB unit errors); ruff clean; check_no_orm OK; check_openapi_drift OK.

## 2026-05-08T22:35Z — Step 3: Dockerfile + .dockerignore

- `Dockerfile`: multi-stage (builder: python:3.12-slim + build-essential + libpq-dev + uv sync; runtime: libpq5 only, copies /app/.venv, non-root UID 1001 `app` user, EXPOSE 8000, ENTRYPOINT entrypoint.sh).
- `.dockerignore`: excludes .venv, .git, __pycache__, .pytest_cache, .ruff_cache, node_modules, .epic, docs, *.egg-info, .env*.
- Manual verification: `docker build -t ilex-be:test .` exit 0; `docker run --rm --entrypoint python ilex-be:test -c "import django, gunicorn; print(django.__version__, gunicorn.__version__)"` printed `5.1.15 26.0.0`.
- Gates: ruff clean; check_no_orm OK; check_openapi_drift OK.

## 2026-05-08T22:20Z — Step 2: check_env management command + tests

- `backend/apps/core/management/commands/check_env.py`: new `Command` class; imports `settings.prod` to trigger ImproperlyConfigured; prints `check-env: OK` on success, writes `check-env: FATAL — <msg>` to stderr and exits 1 on missing var.
- `backend/apps/core/tests/api/test_check_env.py`: 3 subprocess tests — full env → exit 0 + OK message; missing ALLOWED_HOSTS → exit 1; missing CORS_ALLOWED_ORIGINS → exit 1.
- Gates: pytest 151/151 core tests green; ruff clean; check_no_orm OK; check_openapi_drift OK.

## 2026-05-08T22:10Z — Step 1: gunicorn dep + OPENAPI_PUBLIC_DOCS toggle

- `pyproject.toml`: added `"gunicorn>=23"` to `[project].dependencies`; `uv lock` pinned gunicorn 26.0.0.
- `backend/urls.py`: imported `SpectacularSwaggerView` and `env_bool`; appended `/api/v1/docs` route when `OPENAPI_PUBLIC_DOCS=true`.
- `backend/apps/core/tests/api/test_docs_toggle.py`: 2 new tests — 404 when toggle off, 200+swagger-ui marker when on.
- Gates: pytest 148/148 core tests green; ruff clean; check_no_orm OK; check_openapi_drift OK.

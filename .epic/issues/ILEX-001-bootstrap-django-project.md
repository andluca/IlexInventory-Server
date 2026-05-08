---
id: ILEX-001
github_id: null
status: open
assignee: null
state: Executing
type: item
depends_on: []
---

# ILEX-001 Bootstrap Django project

Stand up the Django + DRF + drf-spectacular skeleton so the server boots, `GET /api/v1/health` returns 200 with `postgres: ok`, and the frontend can begin consuming OpenAPI. Today the repo has `pyproject.toml` (psycopg + pytest + ruff), Postgres docker-compose, `.env` template, and the `db_test` library in `apps/core/tests/` — but no Django, no DRF, no `manage.py`, no `apps/core/apis.py`. This issue installs the framework end-to-end with a single live operation (health) so every later issue (auth, catalog, etc.) plugs into a working app.

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.1 (framework + runtime), §2.6 (API contract), §2.9 (config), §3.9 (health endpoint).


# Specification

## Operation: health
File: `backend/apps/core/apis.py`

Liveness probe with Postgres reachability check. Consumed by the FE app shell on boot to gate routing, by ops dashboards for uptime, and by deploy smoke tests. Anonymous (no auth required — listed in SPEC §2.4 as one of three unauthenticated endpoints alongside `/openapi.json` and `/docs`).

### Preconditions

* Django settings are loaded (`DJANGO_SETTINGS_MODULE` resolves to `backend.settings.dev` or `.prod`)
* `DATABASE_URL` env var is set and points to a reachable Postgres
* `apps.core` is in `INSTALLED_APPS`
* `apps.core.urls` is mounted under `/api/v1/`

### Healthy response

#### Input
```
GET /api/v1/health
```

#### Workflow
* DRF dispatches to `HealthView.get`
* View opens a short-lived psycopg connection using `DATABASE_URL`
* Executes `SELECT 1` with a 1s statement timeout
* On success: returns `{"status": "ok", "checks": {"postgres": "ok"}}` with HTTP 200
* No auth, no CSRF, no session — anonymous

#### Output
```json
{
  "status": "ok",
  "checks": { "postgres": "ok" }
}
```

### Postgres unreachable

#### Workflow
* `SELECT 1` raises `psycopg.OperationalError` (connection refused, timeout, auth failure)
* View catches the exception, logs at WARNING with the exception class
* Returns `{"status": "degraded", "checks": {"postgres": "down"}}` with HTTP 503
* Process keeps running (degraded ≠ crash — load balancer drains; `/health` itself stays answerable)

#### Output (status 503)
```json
{
  "status": "degraded",
  "checks": { "postgres": "down" }
}
```

## Operation: openapi-schema
File: `backend/urls.py` (mounted via `drf_spectacular.views.SpectacularAPIView`)

OpenAPI 3.1 schema endpoint. Consumed by the FE's `openapi-typescript` codegen (per SPEC §2.7). Required from this issue forward so every later endpoint flows into a single source of truth without manual schema upkeep.

### Preconditions

* `drf_spectacular` is in `INSTALLED_APPS`
* `SPECTACULAR_SETTINGS` is configured (title, version, security scheme = session cookie)
* `DEFAULT_SCHEMA_CLASS = "drf_spectacular.openapi.AutoSchema"` is set

### Primary response

#### Input
```
GET /api/v1/openapi.json
```

#### Workflow
* DRF dispatches to `SpectacularAPIView`
* drf-spectacular walks the URL conf and `@extend_schema`-annotated views
* Emits OpenAPI 3.1 JSON
* Anonymous; no auth

#### Output
* HTTP 200, `application/vnd.oai.openapi+json`
* Body is a valid OpenAPI 3.1 document with at minimum `paths./api/v1/health` documented and `info.version = "0.1.0"`

## Function: HealthView.get
File: `backend/apps/core/apis.py`
Input: `(self, request: Request) -> Response`
Returns: `rest_framework.response.Response` (status 200 or 503)

DRF `APIView` subclass with one `get` handler. Single responsibility: probe Postgres and shape the response.

### Implementation

* Read `DATABASE_URL` from settings (`django.conf.settings.DATABASE_URL`)
* Open a psycopg connection inside a `try` with `connect_timeout=1`
* Execute `SELECT 1` and fetch
* On success: `Response({"status": "ok", "checks": {"postgres": "ok"}}, status=200)`
* On `psycopg.OperationalError` (or `Exception` as a backstop): log + `Response({"status": "degraded", "checks": {"postgres": "down"}}, status=503)`
* Decorate with `@extend_schema(responses={200: HealthOk, 503: HealthDegraded}, auth=[])` for OpenAPI

## Utils: env helpers
File: `backend/settings/_env.py`

Tiny shared helpers used across the three settings modules to read env vars consistently and fail fast when required vars are missing (per SPEC §2.9).

### Functions

* `env(name: str) -> str`: required env var; raises `ImproperlyConfigured` on miss
* `env_optional(name: str, default: str) -> str`: optional with default
* `env_csv(name: str, default: list[str] | None = None) -> list[str]`: comma-split env (used for `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`)
* `env_bool(name: str, default: bool) -> bool`: `"true"`/`"false"`/`"1"`/`"0"` parser

## Lib: backend settings split
File: `backend/settings/{__init__.py,base.py,dev.py,prod.py}`

Three-environment settings layout per SPEC §2.9. `base.py` owns everything shared; `dev.py` and `prod.py` override only what differs (debug flag, secure cookies, allowed hosts).

### Modules

* `base.py`: `INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "rest_framework", "drf_spectacular", "corsheaders", "apps.core"]`; MIDDLEWARE with `corsheaders.middleware.CorsMiddleware` ahead of `CommonMiddleware`; `DATABASES = {}` (left empty — psycopg connections are opened directly, ORM is unused per BE-D14 with the `auth.User` exception); `REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"], "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"], "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema"}`; `SPECTACULAR_SETTINGS` with title/version/security; `SECRET_KEY = env("DJANGO_SECRET_KEY")`; `DATABASE_URL = env("DATABASE_URL")`
* `dev.py`: `DEBUG = True`, `ALLOWED_HOSTS = ["*"]`, `CORS_ALLOW_ALL_ORIGINS = True`, `SESSION_COOKIE_SECURE = False`
* `prod.py`: `DEBUG = False`, `ALLOWED_HOSTS = env_csv("ALLOWED_HOSTS")`, `CORS_ALLOWED_ORIGINS = env_csv("CORS_ALLOWED_ORIGINS")`, `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`, `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`
* `__init__.py`: empty (settings module is selected via `DJANGO_SETTINGS_MODULE`, not auto-imported)

## External Dependencies

### Django 5.x
Used for: web framework, URL routing, sessions, contrib.auth (BE-D14 — only ORM-managed model in v1)
Pin: `django>=5.0,<5.2`

* Loaded by `manage.py` via `DJANGO_SETTINGS_MODULE=backend.settings.dev`
* `django.contrib.auth` and `sessions` only — no `admin`, no `staticfiles` until needed

### djangorestframework
Used for: API view base class, request/response, `SessionAuthentication`, content negotiation
Pin: `djangorestframework>=3.15`

### drf-spectacular
Used for: OpenAPI 3.1 schema generation (SPEC §2.7)
Pin: `drf-spectacular>=0.27`

* `SpectacularAPIView` mounted at `/api/v1/openapi.json`
* `@extend_schema` on every API class going forward

### django-cors-headers
Used for: cross-origin requests from the FE during dev and from the deployed FE host in prod (SPEC §2.6)
Pin: `django-cors-headers>=4.4`

### python-decouple
Used for: env var loading from `.env` and process env (SPEC §2.9)
Pin: `python-decouple>=3.8`

* Wraps the `_env.py` helpers; chosen over `pydantic-settings` to keep the dependency surface minimal

### pytest-django
Used for: DRF test client, settings module setup in tests
Pin: `pytest-django>=4.8`

* Note: `db_test` (already shipped) does NOT depend on Django — keep it that way per the existing decision. `pytest-django` is only used for the API test client + settings shim


# Plan

Each step is independently shippable: after step N, the test suite passes and `python manage.py check` exits 0. Steps are ordered to minimize backtracking; tests are written FIRST inside each step (TDD red → green → refactor).

1. **Add framework dependencies to `pyproject.toml`**
   - Why: nothing else compiles without these. Cleanest first commit; isolates a dependency bump from any code change.
   - [ ] Add `django>=5.0,<5.2`, `djangorestframework>=3.15`, `drf-spectacular>=0.27`, `django-cors-headers>=4.4`, `python-decouple>=3.8` to `[project].dependencies`
   - [ ] Add `pytest-django>=4.8` to `[project.optional-dependencies].dev`
   - [ ] Run `pip install -e .[dev]` and confirm a clean import: `python -c "import django, rest_framework, drf_spectacular, corsheaders, decouple"`
   - [ ] Add `DJANGO_SETTINGS_MODULE = "backend.settings.dev"` to `[tool.pytest.ini_options]` so pytest auto-loads settings

2. **Settings split (`backend/settings/{__init__.py,_env.py,base.py,dev.py,prod.py}`)**
   - Why: every later step (urls, manage.py, wsgi, health view) imports from settings. Build it once, fail fast on missing env vars, never refactor settings mid-feature.
   - [ ] Write env-helper unit tests in `backend/apps/core/tests/unit/test_env.py`: `env` raises on missing, `env_csv` splits on comma, `env_bool` accepts `"true"/"false"`
   - [ ] Implement `_env.py` to make those tests pass
   - [ ] Write `base.py` with `INSTALLED_APPS`, MIDDLEWARE (CORS first), `REST_FRAMEWORK`, `SPECTACULAR_SETTINGS`, `DATABASE_URL`, `SECRET_KEY`
   - [ ] Write `dev.py` (DEBUG=True, CORS open, insecure cookies)
   - [ ] Write `prod.py` (DEBUG=False, CORS from env, secure cookies, proxy SSL header)
   - [ ] Smoke: `python -c "from django.conf import settings; settings.INSTALLED_APPS"` with `DJANGO_SETTINGS_MODULE=backend.settings.dev` succeeds
   - [ ] Smoke: importing `backend.settings.prod` without `ALLOWED_HOSTS` raises `ImproperlyConfigured`

3. **Project entry points (`backend/manage.py`, `backend/urls.py`, `backend/wsgi.py`, `backend/asgi.py`)**
   - Why: makes Django runnable. After this step, `python manage.py check` passes and `runserver` starts (even though no endpoints are wired yet — root URL conf is empty).
   - [ ] `manage.py` at repo root pointing at `backend.settings.dev` by default
   - [ ] `backend/urls.py` with empty `urlpatterns = []` (real routes added in step 4)
   - [ ] `backend/wsgi.py` and `backend/asgi.py` with the standard Django stubs
   - [ ] Smoke test in `backend/apps/core/tests/unit/test_django_check.py`: subprocess `python manage.py check` exits 0
   - [ ] Manual smoke: `python manage.py runserver` boots without error and serves 404 on `/`

4. **Health endpoint (`backend/apps/core/apis.py` + `backend/apps/core/urls.py`)**
   - Why: minimum testable HTTP surface. Without it, the FE can't gate boot. Wired through `apps.core.urls` mounted at `/api/v1/` so every later app slots in the same way (`/api/v1/auth`, `/api/v1/products`, etc.).
   - [ ] Write API tests in `backend/apps/core/tests/api/test_health.py`:
     - `GET /api/v1/health` with Postgres up returns 200 and `{"status": "ok", "checks": {"postgres": "ok"}}`
     - `GET /api/v1/health` with `DATABASE_URL` pointing at an unreachable port returns 503 and `{"status": "degraded", "checks": {"postgres": "down"}}`
   - [ ] Implement `HealthView` in `apps/core/apis.py` using a short-lived psycopg connection (no Django ORM, no service-layer call — health is a leaf)
   - [ ] Wire `apps/core/urls.py` with `path("health", HealthView.as_view(), name="health")`
   - [ ] Mount in `backend/urls.py` with `path("api/v1/", include("apps.core.urls"))`
   - [ ] Verify response `Content-Type: application/json` and that `auth=[]` is reflected in the OpenAPI schema

5. **OpenAPI schema endpoint (drf-spectacular wiring)**
   - Why: unblocks FE type generation from this issue forward. Mounting it now means every later issue's endpoints flow into the schema automatically with no extra wiring.
   - [ ] Write API test in `backend/apps/core/tests/api/test_openapi.py`:
     - `GET /api/v1/openapi.json` returns 200 with `Content-Type: application/vnd.oai.openapi+json`
     - Body is valid JSON with `openapi: "3.1.0"`, `info.title`, `info.version`, and `paths."/api/v1/health"` present
   - [ ] Mount `SpectacularAPIView.as_view()` at `/api/v1/openapi.json` in `backend/urls.py`
   - [ ] Decorate `HealthView.get` with `@extend_schema(...)` so the response shape is documented (HealthOk + HealthDegraded inline serializers)
   - [ ] Confirm `drf-spectacular --validate` (via `python manage.py spectacular --validate --file /tmp/schema.json`) exits 0


# Notes

- **db_test stays Django-free.** SPEC §2.1 says the `db_test` library is independent of Django ORM. After this issue adds `pytest-django`, pytest will auto-load Django settings — but the existing `db` fixture in `backend/conftest.py` opens a raw psycopg connection without going through Django. Keep it that way; do NOT switch to `django_db` fixtures.
- **No DATABASES = {...} in base.py for now.** Per BE-D14, only `auth.User` uses the ORM. Until ILEX-003 (auth) introduces the `auth_user` table via `migrate`, `DATABASES` can stay empty. When auth lands, add a single Postgres entry then. The `migrate_sql` runner (ILEX-002) operates on raw psycopg and doesn't need `DATABASES` either.
- **Health view doesn't go through services/queries layers.** It's a leaf operation that opens its own connection — the four-layer rule (APIs → Services → Queries → Schema) doesn't apply because there's no business logic and no owner-scoped data. Document this exception in `apps/core/apis.py` with a one-line comment so reviewers don't flag it.
- **CSRF on `/health` and `/openapi.json`.** Both are GET-only and anonymous; CSRF doesn't apply. No special handling needed beyond DRF's defaults.
- **No `SECRET_KEY` fallback in dev.** Even `dev.py` reads from env. The `.env.example` will need a new line `DJANGO_SECRET_KEY=dev-secret-do-not-use-in-prod` added in step 2; document the change in the commit message so anyone pulling the branch knows to refresh their `.env`.
- **`DATABASE_URL` collision with `db_test`.** The existing `conftest.py` reads `DATABASE_URL` and points at `ilex_test`. Settings will read the same var. In CI and local dev, both should point at the same Postgres instance; the test fixture drops + recreates the `ilex_test` database per session, while the runserver uses whatever DB the URL names. Add `.env.example` line `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ilex_dev` so dev and test databases are distinct on the same instance.
- **Out of scope for this issue:** auth (ILEX-003), CSV renderer registration (ILEX-009), `DATABASES` ORM entry (ILEX-003 when `auth.User` lands), migration runner (`migrate_sql` is ILEX-002).


# Journal

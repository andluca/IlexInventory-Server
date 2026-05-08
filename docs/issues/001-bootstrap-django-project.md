# 001 — Bootstrap Django project

## Overview

Stand up the Django project skeleton. Today the repo has `pyproject.toml` (psycopg + pytest + ruff), Postgres docker-compose, `.env` template, and the `db_test` library — but no Django, no DRF, no `manage.py`. This issue boots the framework end-to-end so the server runs, `/api/v1/health` returns 200, and the FE can start consuming OpenAPI.

**Scope:**
- Add `django>=5.0`, `djangorestframework`, `drf-spectacular`, `django-cors-headers`, `python-decouple` (or `pydantic-settings`) to `pyproject.toml`
- `backend/manage.py`
- `backend/settings/{base,dev,prod}.py` — split per environment; `DATABASE_URL` from env; `SESSION_COOKIE_SECURE` toggle; `INSTALLED_APPS = ['django.contrib.auth', ..., 'rest_framework', 'drf_spectacular', 'apps.core']`
- `backend/urls.py`, `backend/wsgi.py`, `backend/asgi.py`
- DRF settings: `SessionAuthentication` only (no token auth v1), `DEFAULT_RENDERER_CLASSES` includes JSON + CSV (CSV renderer registered later in Issue 009)
- CORS settings: `CORS_ALLOWED_ORIGINS` from env; `django.middleware.security.SecurityMiddleware` + `corsheaders.middleware.CorsMiddleware` in MIDDLEWARE
- `drf-spectacular` settings: title, version, description; security scheme = session cookie
- `apps/core/apis.py` with `HealthView` returning `{ status, checks: { postgres } }`
- `apps/core/urls.py` mounted at `/api/v1/`
- Smoke test: `python manage.py runserver` boots; `GET /api/v1/health` returns 200 with `postgres: ok`
- Django not running on the test database — keep `db_test` independent of Django ORM

**Reference:** SPEC §2.1, §2.6, §2.9, §3.9.

**Depends on:** Phase 0 (already done).

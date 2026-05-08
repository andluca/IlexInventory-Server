---
id: ILEX-003
github_id: null
status: open
assignee: null
state: Queued
type: item
depends_on: [ILEX-002]
---

# ILEX-003 Implement auth in apps/core

Sign-up, login, logout, `/auth/me`. Cookie session via DRF `SessionAuthentication`. Simplest possible: email + password, no email verification, no password reset.

This issue is the **only** place where Django ORM is allowed (BE-D14): `apps/core/auth.py` may import from `django.contrib.auth` and use `User.objects.create_user`, `authenticate`, `login`, `logout`. Every other module remains raw psycopg. The CI grep gate has a narrow allowlist for this file.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §3.1; X1 + X2 flows; BE-D14.

## Scope

- `apps/core/apis.py` — auth endpoints (signup, login, logout, me)
- `apps/core/serializers.py` — `SignupRequest`, `LoginRequest`, `UserResponse`
- `apps/core/auth.py` — only file allowed to import Django ORM auth; wraps `signup_user(email, password)` (creates `auth.User`, sets password via Django hasher, logs in)
- `apps/core/urls.py` — routes mounted under `/api/v1/auth/`
- DRF: CSRF middleware enabled for state-changing calls; signup and login may be CSRF-exempt for the initial call (then session sets the token)
- Django's standard `python manage.py migrate auth` provisions the `auth_user` table; our raw-SQL migrations reference `auth_user(id)` via FK

## Endpoints

| Method | Route | Auth | Description |
|---|---|---|---|
| POST | `/auth/signup` | None | Create account: email + password. Returns 200 + session cookie set |
| POST | `/auth/login` | None | Set session cookie. 401 on bad credentials |
| POST | `/auth/logout` | Session | Clear session |
| GET | `/auth/me` | Session | Current user info |

## Tests

- Unit: email validation, password length validation
- API: signup happy path; duplicate email returns 409; login/logout cycles; `/auth/me` returns current user; cross-account access (other users' resources) returns 404

## Dependencies

1. ILEX-002 (foundation helpers + 0001_init must exist before auth uses owner injection from session)

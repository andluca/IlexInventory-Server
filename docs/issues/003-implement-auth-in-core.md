# 003 — Implement auth in apps/core

## Overview

Sign-up, login, logout, `/auth/me`. Cookie session via DRF `SessionAuthentication`. Simplest possible: email + password, no email verification, no password reset.

This issue is the **one place** where Django ORM is allowed (BE-D14): `apps/core/auth.py` may `from django.contrib.auth import ...` and use `User.objects.create_user`, `authenticate`, `login`, `logout`. Every other module remains raw psycopg. The CI grep gate has a narrow allowlist for this file.

**Scope:**
- `apps/core/apis.py` — auth endpoints (signup, login, logout, me)
- `apps/core/serializers.py` — `SignupRequest`, `LoginRequest`, `UserResponse`
- `apps/core/services.py` — `signup_user(email, password)` creates `auth.User`, sets password (Django hasher), logs in
- `apps/core/urls.py` — routes mounted under `/api/v1/auth/`
- DRF: CSRF middleware enabled for state-changing calls
- Tests:
  - Unit: email validation, password length validation
  - API: signup happy path; duplicate email returns 409; login/logout cycles; `/auth/me` returns current user; cross-account access (other users' resources) returns 404

**Endpoints:** POST `/auth/signup`, POST `/auth/login`, POST `/auth/logout`, GET `/auth/me`

**Reference:** SPEC §3.1, X1 + X2 flows. BE-D14 (Django ORM exception for `auth.User`).

**Depends on:** 002.

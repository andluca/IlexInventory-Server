---
id: ILEX-003
github_id: null
status: completed
assignee: null
state: Done
type: item
depends_on: [ILEX-002]
---

# ILEX-003 Implement auth in apps/core

Sign-up, login, logout, `/auth/me`. Cookie session via DRF `SessionAuthentication`. Simplest possible: email + password, no email verification, no password reset.

This issue is the **only** place where Django ORM is allowed (BE-D14): `apps/core/auth.py` may import from `django.contrib.auth` and use `User.objects.create_user`, `authenticate`, `login`, `logout`. Every other module remains raw psycopg. The CI grep gate has a narrow allowlist for this file.

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.4, §3.1; X1 + X2 flows; BE-D14.


# Specification

## Operation: signup
File: `backend/apps/core/apis.py`

Create an account with email + password. No email verification, no password reset (v1). On success, sets the session cookie so the client is logged in immediately.

### Preconditions

* No active session (anonymous request)
* Postgres reachable; `auth_user` table exists (post-`migrate auth`)
* `0001_init.sql` and `0002_auth_fk.sql` applied

### Primary Use Case — happy path

#### Input
```
POST /api/v1/auth/signup
Content-Type: application/json

{ "email": "alice@example.com", "password": "correct horse battery" }
```

#### Workflow
* CLI/client POSTs `{ email, password }`
* Serializer validates: email format (RFC-ish), password length ≥ 8, both non-empty
* `apps/core/auth.signup_user(email, password)` creates `auth.User` (username = email) with hashed password
* Django `login(request, user)` sets the session cookie
* Response: 200 with `{ user: { id, email, created_at } }`

#### Output
```
HTTP/1.1 200 OK
Set-Cookie: sessionid=...; HttpOnly; SameSite=Lax
Content-Type: application/json

{ "user": { "id": "8b3f...", "email": "alice@example.com", "created_at": "2026-05-08T12:00:00Z" } }
```

### Duplicate email

#### Workflow
* Client POSTs an email already present in `auth_user`
* `signup_user` raises `Conflict("EmailAlreadyExists")`
* API maps to 409 with envelope `{"error": "Conflict", "detail": "Email already registered"}`

### Validation failure

#### Workflow
* Missing `email` or `password`, malformed email, or `len(password) < 8`
* Serializer emits DRF `ValidationError` → API returns 400 with envelope
  `{"error": "ValidationError", "fields": { "email": ["..."] }}`

## Operation: login
File: `backend/apps/core/apis.py`

Authenticate an existing user; set session cookie on success. Standard Django session login.

### Preconditions

* No active session (anonymous request)
* User exists in `auth_user`

### Primary Use Case — happy path

#### Input
```
POST /api/v1/auth/login
Content-Type: application/json

{ "email": "alice@example.com", "password": "correct horse battery" }
```

#### Workflow
* Serializer validates non-empty `email`, `password`
* `apps/core/auth.authenticate_user(request, email, password)` calls `django.contrib.auth.authenticate` then `login`
* On success: 200 with `{ user: { id, email, created_at } }` and session cookie set
* On failure: raises `Unauthorized("InvalidCredentials")` → 401 envelope (no leak: same error for unknown email vs wrong password)

#### Output
```
HTTP/1.1 200 OK
Set-Cookie: sessionid=...; HttpOnly; SameSite=Lax
{ "user": { "id": "...", "email": "...", "created_at": "..." } }
```

### Bad credentials

#### Workflow
* Wrong password, or email not in `auth_user`
* Returns 401 with `{"error": "Unauthorized", "detail": "Invalid credentials"}`

## Operation: logout
File: `backend/apps/core/apis.py`

Clear the session. No-op for already-anonymous requests (idempotent).

### Preconditions

* Active session cookie present (otherwise 401 from `IsAuthenticated`)

### Primary Use Case

#### Input
```
POST /api/v1/auth/logout
Cookie: sessionid=...
X-CSRFToken: ...
```

#### Workflow
* DRF auth class resolves the session to a User
* `apps/core/auth.logout_user(request)` calls `django.contrib.auth.logout`
* Response: 204 No Content; session cookie cleared

#### Output
```
HTTP/1.1 204 No Content
Set-Cookie: sessionid=; expires=...; Max-Age=0
```

## Operation: me
File: `backend/apps/core/apis.py`

Returns the current user. Consumed by FE app shell, ⌘K, agent context.

### Preconditions

* Active session cookie present (otherwise 401)

### Primary Use Case

#### Input
```
GET /api/v1/auth/me
Cookie: sessionid=...
```

#### Workflow
* `IsAuthenticated` permission resolves the session
* View serializes `request.user` via `UserResponse` (id, email, created_at)
* Response: 200

#### Output
```
HTTP/1.1 200 OK
{ "user": { "id": "...", "email": "alice@example.com", "created_at": "..." } }
```

### Anonymous

#### Workflow
* No session cookie
* DRF returns 401 (handled by `IsAuthenticated`)

## Function: signup_user
File: `backend/apps/core/auth.py`
Input: `(request: HttpRequest, email: str, password: str) -> User`
Returns: the newly created `auth.User` (also logs them in via `login(request, user)`)

The single chokepoint where Django ORM auth is invoked. Wraps `User.objects.create_user` so the rest of the codebase never imports from `django.contrib.auth.models`.

### Implementation

* Reject duplicates: `User.objects.filter(username=email).exists()` → raise `Conflict(detail="Email already registered")`
* `User.objects.create_user(username=email, email=email, password=password)` (Django hashes password via `set_password`)
* `django.contrib.auth.login(request, user)` to set the session cookie
* Return the user

## Function: authenticate_user
File: `backend/apps/core/auth.py`
Input: `(request: HttpRequest, email: str, password: str) -> User`
Returns: the authenticated `auth.User`; raises `Unauthorized` on bad credentials

### Implementation

* `user = django.contrib.auth.authenticate(request, username=email, password=password)`
* If `user is None`: raise `Unauthorized(detail="Invalid credentials")`
* `django.contrib.auth.login(request, user)` to set the session cookie
* Return the user

## Function: logout_user
File: `backend/apps/core/auth.py`
Input: `(request: HttpRequest) -> None`

### Implementation

* `django.contrib.auth.logout(request)` (clears session, fires `user_logged_out` signal)

## Lib: Auth serializers
File: `backend/apps/core/serializers.py`

Request/response shapes for the auth endpoints. Drives both DRF validation and the OpenAPI schema (`drf-spectacular` reads these).

### Classes

* `SignupRequest`: `email: EmailField(required=True)`, `password: CharField(min_length=8, write_only=True)`
* `LoginRequest`: `email: EmailField(required=True)`, `password: CharField(write_only=True)` (no min_length — login accepts pre-existing users whose passwords pre-date a length policy change)
* `UserResponse`: `id: UUIDField` (read-only), `email: EmailField`, `date_joined: DateTimeField(source="date_joined")` exposed as `created_at`. Matches X2 step 5.

## Lib: Unauthorized error
File: `backend/apps/core/errors.py`

### Functions

* Add `Unauthorized(DomainError)` with `code = "Unauthorized"` and HTTP 401 in `_HTTP_STATUS`. Used by `authenticate_user` and any future "session required but missing" path.

## Lib: 0002_auth_fk schema
File: `backend/migrations/0002_auth_fk.sql`

Adds the deferred FK on `idempotency_keys.owner_id` → `auth_user(id)` now that `auth_user` exists. Also adds the same column type on later owner-scoped tables (none yet — this issue only patches `idempotency_keys`).

### Contents

* `ALTER TABLE idempotency_keys ADD CONSTRAINT idempotency_keys_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth_user(id) ON DELETE CASCADE;`

Note: `auth_user.id` is `INT` by default in Django (not UUID). Two options at execution time:
* (a) keep `idempotency_keys.owner_id UUID` and **skip the FK** (safety net loses the table-link guarantee but the service-layer guard remains). Document the gap.
* (b) change `idempotency_keys.owner_id` to `INT` to match `auth_user.id`. Requires altering the column type and adjusting `apps/core/idempotency.py` to pass `int(request.user.id)`.

**Decision:** option (b). Composite FKs in later issues (D4) reference `auth_user.id` everywhere; storing it as `INT` keeps every owner-scoped column type-consistent and the FK enforceable.

`0002_auth_fk.sql` therefore performs:
* `ALTER TABLE idempotency_keys ALTER COLUMN owner_id TYPE INT USING NULL;` (acceptable: table is empty post-migration; in practice we `TRUNCATE idempotency_keys` first since no production data exists yet)
* Adds the FK constraint.

## Lib: Settings update
File: `backend/settings/base.py`

### Changes

* Populate `DATABASES["default"]` with the Postgres connection (engine `django.db.backends.postgresql`, parsed from `DATABASE_URL`) so `manage.py migrate auth` can run. ORM is **only** used for `auth.User` and session storage; every other module stays on raw psycopg.
* Add `django.contrib.contenttypes` migrations (already in `INSTALLED_APPS`) — they ride along with `migrate auth`.
* Add `LOGIN_URL` (unused but expected by Django) and `AUTH_USER_MODEL` default.
* CSRF settings: `CSRF_COOKIE_SAMESITE = "Lax"`, `SESSION_COOKIE_SAMESITE = "Lax"`. CSRF middleware already enabled in §base.
* DRF default permissions: `"DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"]`. Auth endpoints (`signup`, `login`) override with `permission_classes = []`. Health/openapi/docs already override.

## Lib: CI grep gate
File: `pyproject.toml` (or a new `scripts/check_no_orm.sh` invoked by CI)

### Functions

* Lint task: `grep -RE "from django\.db\.models|from django\.contrib\.auth" backend/apps/` returns only matches inside `apps/core/auth.py`. Any other match fails CI.
* Add a `make check-no-orm` target (or pyproject script) that runs the grep and exits non-zero on violation.

## URL routes
File: `backend/apps/core/urls.py`

### Changes

* Add `path("auth/signup", SignupView.as_view(), name="auth-signup")`
* Add `path("auth/login", LoginView.as_view(), name="auth-login")`
* Add `path("auth/logout", LogoutView.as_view(), name="auth-logout")`
* Add `path("auth/me", MeView.as_view(), name="auth-me")`
* Existing `health` route untouched

## External Dependencies

### django.contrib.auth (Django built-in)
Used for: password hashing (`set_password`), session login/logout (`login`, `logout`, `authenticate`), `auth_user` table

* No new dependency — Django ships with it
* CI grep gate enforces that only `apps/core/auth.py` imports from it


# Plan

Each step is independently shippable: after step N, `pytest` is green, `ruff check backend/` clean, `python manage.py check` exits 0.

1. **Wire DATABASES + run `migrate auth`; idempotency `owner_id` becomes `INT`**
   - Why: every later step depends on `auth_user` existing in the DB and on `idempotency_keys.owner_id` matching its FK target type. Land the schema substrate first so all subsequent tests run against a realistic, FK-enforced DB.
   - [ ] Update `backend/settings/base.py`: populate `DATABASES["default"]` from `DATABASE_URL` (parse with `urllib.parse.urlsplit`); add `"django.contrib.auth"` already present, add `"django.contrib.contenttypes"` already present (no change), add CSRF/session sameSite settings
   - [ ] Add DRF `DEFAULT_PERMISSION_CLASSES = ["IsAuthenticated"]` to base settings
   - [ ] Write `backend/migrations/0002_auth_fk.sql`: `TRUNCATE idempotency_keys`, `ALTER COLUMN owner_id TYPE INT USING NULL`, add FK to `auth_user(id)` with `ON DELETE CASCADE`
   - [ ] Update `apps/core/idempotency.py` to pass `int(owner_id)` (was `str(owner_id)`); update existing `test_idempotency.py` fakes to use `id=<int>` instead of `uuid.uuid4()` (smallest possible diff: `_fake_user(uid: int)` returns `SimpleNamespace(id=uid)`, default to a unique int per test)
   - [ ] Update `tests/api/conftest.py` (api conftest): in addition to `migrate_sql`, run `python manage.py migrate auth contenttypes sessions` before `migrate_sql` so `auth_user` exists before 0002 references it. Verify ordering: `migrate auth` → `migrate_sql` (which applies 0001 and 0002 in lex order).
   - [ ] Write API test `tests/api/test_auth_fk.py`: insert into `idempotency_keys` with `owner_id` not in `auth_user` raises `psycopg.errors.ForeignKeyViolation`; insert with a real `auth_user.id` (created via raw SQL, not ORM, in the test) succeeds
   - [ ] Verify all existing tests still pass (idempotency tests now create a real `auth_user` row before the test or use a known-existing id from a session-scoped fixture)

2. **Add `Unauthorized` to `apps/core/errors.py`**
   - Why: `authenticate_user` and any later "session required" service path need an HTTP-401 mapper. Land the error class before the auth endpoints reference it so step 3 can raise it.
   - [ ] Write unit test in `tests/unit/test_errors.py`: `to_response(Unauthorized(detail="Invalid credentials"))` returns `({"error": "Unauthorized", "detail": "Invalid credentials"}, 401)`
   - [ ] Add `class Unauthorized(DomainError): code = "Unauthorized"` and `Unauthorized: 401` to `_HTTP_STATUS`

3. **`apps/core/auth.py` — the ORM chokepoint**
   - Why: this file is the **only** place Django ORM auth is allowed (BE-D14). Land it standalone with unit tests so the API layer in step 4 can import a tested function.
   - [ ] Write API test `tests/api/test_auth_unit.py` (DB-touching but framework-light): `signup_user(request, email, password)` creates exactly one `auth_user` row with the given email and a hashed password (assert `password.startswith("pbkdf2_")`); duplicate email raises `Conflict`; `authenticate_user` returns the user on correct creds; raises `Unauthorized` on wrong password; `logout_user` clears `request.session` (use `RequestFactory` + `SessionMiddleware`)
   - [ ] Write `apps/core/auth.py`: 3 functions (`signup_user`, `authenticate_user`, `logout_user`); only file in the repo importing from `django.contrib.auth`
   - [ ] One-line top-of-file comment: "ORM allowlist file (BE-D14). Do not import django.contrib.auth elsewhere."

4. **Serializers + 4 API views + URL routes**
   - Why: ships the complete public surface in one go — the four endpoints share the same serializers and the same view conventions, so splitting them across steps would only churn imports.
   - [ ] Write `apps/core/serializers.py`: `SignupRequest`, `LoginRequest`, `UserResponse`
   - [ ] Write `apps/core/apis.py` additions: `SignupView`, `LoginView`, `LogoutView`, `MeView`. Use `@extend_schema` for OpenAPI. Signup/Login: `authentication_classes = []`, `permission_classes = []`. Logout/Me: rely on default `IsAuthenticated`. Catch `DomainError` → `to_response`.
   - [ ] Update `apps/core/urls.py`: register the four routes
   - [ ] Write API test `tests/api/test_auth_api.py` with these cases (taking the SPEC X2 example as the happy-path shape):
     - signup happy path: 200, response body matches `{"user": {"id", "email": "alice@example.com", "created_at"}}`, session cookie set
     - signup duplicate email: 409, `{"error": "Conflict"}`
     - signup malformed email: 400 with `fields.email`
     - signup short password (< 8): 400 with `fields.password`
     - login happy path → /auth/me → returns the same user
     - login bad password: 401, `{"error": "Unauthorized"}`
     - login unknown email: 401 (same envelope — no enumeration leak)
     - /auth/me without session: 401
     - logout → /auth/me returns 401
     - two users have isolated sessions: signup user A, signup user B in a fresh `APIClient`; A's `/auth/me` returns A's id, B's returns B's. (Cross-account 404 on owner-scoped resources is verified in later issues that own those resources.)

5. **CSRF policy for auth endpoints**
   - Why: SPEC §3.1 says CSRF is enabled for state-changing calls but signup/login may be CSRF-exempt for the initial call (since the client has no token yet). Lock the policy explicitly so it doesn't drift.
   - [ ] Decorate `SignupView` and `LoginView` with `@method_decorator(csrf_exempt, name="dispatch")` (or set `authentication_classes = []` which already disables DRF's CSRF check for SessionAuthentication)
   - [ ] `LogoutView` requires CSRF token (default behavior with `SessionAuthentication`)
   - [ ] Write API test `tests/api/test_auth_csrf.py`: a `Client(enforce_csrf_checks=True)` POST to `/auth/logout` without `X-CSRFToken` returns 403; with the token, returns 204. Signup/login work without a CSRF token regardless.

6. **CI grep gate: ORM allowlist**
   - Why: D14 declares `apps/core/auth.py` the only ORM-permitted file. Without an automated check, future contributions can quietly add ORM elsewhere. Add the gate now while the allowlist has exactly one entry.
   - [ ] Add a `pyproject.toml` `[tool.ilex.checks]` entry or `scripts/check_no_orm.sh`: greps `from django.db.models|from django.contrib.auth` across `backend/apps/`, fails if any match is outside `backend/apps/core/auth.py`
   - [ ] Wire the script into the test/CI command (e.g., `pyproject.toml` script entry `check-no-orm = "scripts.check_no_orm:main"` or a `Makefile` target invoked alongside pytest)
   - [ ] Write a meta-test `tests/unit/test_no_orm.py`: runs the same grep in-process and asserts the only allowed match is in `apps/core/auth.py`. (Belt-and-suspenders so the gate runs on every `pytest` even before CI is wired.)


# Notes

- **Why DATABASES had to land here.** `DATABASES = {}` worked through ILEX-002 because we never invoked the ORM. The moment `manage.py migrate auth` runs (step 1), Django needs a real default connection. The ORM stays scoped to `auth_user` + sessions + contenttypes — no business entities migrate to ORM.
- **`auth_user.id` is an INT, not a UUID.** Django's default User PK is `AutoField` (BIGINT in Django 5). Every later owner-scoped column (`products.owner_id`, `batches.owner_id`, etc.) will therefore be `INT`/`BIGINT`, not UUID. UUIDv7 stays the PK type for **business entities** (D5); only the owner reference is `INT`. We do not switch Django User to a UUID PK — it's not on the v1 critical path and would invalidate every Django auth test fixture.
- **`idempotency_keys.owner_id` retype.** Step 1 truncates and retypes the column. Acceptable because no production data exists yet (still pre-deploy). After this issue, the migration is forward-only like every other.
- **No email verification, no password reset.** Per SPEC §1.3 and §2.4. If a user forgets their password in v1, the recovery story is "create a new account" — explicitly out of scope.
- **Login does not reveal email enumeration.** Both "unknown email" and "wrong password" return the same 401 envelope (`{"error": "Unauthorized", "detail": "Invalid credentials"}`). Tested in step 4.
- **Cross-account 404 is mostly out of scope here.** ILEX-003's surface has no owner-scoped resources yet. The cross-owner-returns-404 contract (D4) is enforced in later issues (catalog, inventory, sales) where actual resources exist. This issue only verifies that two simultaneous sessions don't leak each other's identity through `/auth/me`.
- **`UserResponse.created_at`.** Django's User model stores it as `date_joined`. We expose it as `created_at` to match the SPEC X2 step 5 shape (`{ id, email, created_at }`). The serializer aliases via `source="date_joined"`.
- **CSRF on logout.** Logout is the first state-changing endpoint behind a session; verifying CSRF works here proves the middleware is wired correctly for every later state-changing endpoint.
- **`@idempotent` is not used by auth endpoints.** Signup/login/logout/me are not in SPEC §2.6's idempotency-key list. Retrying a signup is a genuine duplicate (correctly returns 409); retrying a login is harmless (re-authenticates); logout is naturally idempotent.
- **Out of scope:** rate limiting, password reset, email verification, social login, 2FA, account deletion, password change endpoint, session expiry tuning, CSRF token refresh endpoint, agent OAuth wiring (deferred to phase 3).


# Journal

## Step 1 — 2026-05-08

Wire `DATABASES["default"]`, apply Django auth/sessions migrations, retype `idempotency_keys.owner_id` to `INT` and add FK.

Files changed:
- `backend/settings/base.py` — parse `DATABASE_URL` via `urllib.parse.urlsplit`; populate `DATABASES["default"]`; add `CSRF_COOKIE_SAMESITE`, `SESSION_COOKIE_SAMESITE`, `LOGIN_URL`, `DEFAULT_PERMISSION_CLASSES`
- `backend/migrations/0002_auth_fk.sql` — new; TRUNCATE + `ALTER COLUMN owner_id TYPE INT USING NULL` + FK to `auth_user(id)`
- `backend/apps/core/idempotency.py` — `str(owner_id)` → `int(owner_id)` throughout
- `backend/apps/core/tests/api/conftest.py` — run `migrate contenttypes/auth/sessions` before `migrate_sql`
- `backend/apps/core/tests/api/test_auth_fk.py` — new; 3 integration tests for FK contract
- `backend/apps/core/tests/api/test_idempotency.py` — `_fake_user` now uses `int` ids + inserts `auth_user` row
- `backend/apps/core/tests/api/test_migrate_sql.py` — `_EXPECTED_MIGRATIONS = 2` (was hardcoded `1`)
- `backend/apps/core/tests/unit/conftest.py` — run ORM migrations before `migrate_sql`
- `backend/apps/core/tests/unit/test_uuidv7_sql.py` — `test_idempotency_keys_pk_rejects_duplicate` uses INT owner_id + auth_user fixture row

Gates: 85/85 pytest green; `python manage.py check` 0 issues.

## Step 2 — 2026-05-08

Add `Unauthorized` to `apps/core/errors.py`.

Files changed:
- `backend/apps/core/errors.py` — added `class Unauthorized(DomainError): code = "Unauthorized"` + `Unauthorized: 401` in `_HTTP_STATUS`
- `backend/apps/core/tests/unit/test_errors.py` — added `test_unauthorized_to_response` and `test_unauthorized_default_code`

Gates: 87/87 pytest green (11 unit error tests).

## Step 3 — 2026-05-08

`apps/core/auth.py` — the ORM chokepoint (BE-D14).

Files changed:
- `backend/apps/core/auth.py` — new; `signup_user`, `authenticate_user`, `logout_user`; only file importing from `django.contrib.auth`
- `backend/apps/core/tests/api/test_auth_unit.py` — new; 7 tests (`signup_user` creates row + hashes pwd + raises Conflict; `authenticate_user` happy path + wrong pwd + unknown email; `logout_user` clears session); marked `django_db`

Gates: 94/94 pytest green.

## Step 4 — 2026-05-08

Serializers + 4 API views + URL routes.

Files changed:
- `backend/apps/core/serializers.py` — new; `SignupRequest`, `LoginRequest`, `UserResponse`
- `backend/apps/core/apis.py` — added `SignupView`, `LoginView`, `LogoutView`, `MeView`
- `backend/apps/core/exceptions.py` — new; custom DRF exception handler mapping `NotAuthenticated` → 401 (DRF default is 403 for session-only auth)
- `backend/apps/core/urls.py` — registered four auth routes
- `backend/settings/base.py` — added `EXCEPTION_HANDLER` pointing to `apps.core.exceptions.exception_handler`
- `backend/apps/core/tests/api/test_auth_api.py` — new; 10 API tests (signup happy/dup/malformed/short; login+me; bad-pwd; unknown-email; me-401; logout+me-401; session isolation)

Gates: 104/104 pytest green; ruff clean; `manage.py check` 0 issues.

## Step 5 — 2026-05-08

CSRF policy verification.

Files changed:
- `backend/apps/core/tests/api/test_auth_csrf.py` — new; 4 tests: signup/login work without CSRF token; logout without CSRF token → 403; logout with CSRF token → 204

CSRF policy was already correct (no implementation change needed): `authentication_classes=[]` on `SignupView`/`LoginView` skips DRF's CSRF check; `LogoutView` retains `SessionAuthentication` which enforces CSRF for authenticated POSTs.

Gates: 108/108 pytest green.

## Step 6 — 2026-05-08

CI grep gate — ORM allowlist.

Files changed:
- `scripts/check_no_orm.sh` — new; shell script that greps `backend/apps/` for ORM imports, exits non-zero on any match outside `apps/core/auth.py`
- `pyproject.toml` — added `[tool.ilex.checks]` section documenting the allowlist
- `backend/apps/core/tests/unit/test_no_orm.py` — new; 2 tests: `test_no_orm_outside_allowlist` (scans all `.py` files, fails on any import-line match outside `auth.py`); `test_allowlist_file_has_orm_import` (sanity check that allowlist isn't stale)
- `backend/conftest.py` — added `django_db_setup` no-op fixture so pytest-django does not try to create/drop the test database (our custom `db` fixture owns the lifecycle)
- `backend/settings/base.py` — added `TEST.NAME` to `DATABASES["default"]` so pytest-django targets `ilex_test` not `test_ilex_test`
- `backend/apps/core/tests/api/test_auth_unit.py` — removed `from django.contrib.auth import get_user_model` (ORM allowlist violation); verification now uses the returned user object directly + `pytestmark = pytest.mark.django_db`
- `backend/apps/core/exceptions.py` — new; custom DRF exception handler mapping `NotAuthenticated` → 401

Gates: 110/110 pytest green; ruff clean; `manage.py check` 0 issues; `./scripts/check_no_orm.sh` exits 0.

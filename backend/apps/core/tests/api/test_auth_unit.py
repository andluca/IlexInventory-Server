"""DB-touching unit tests for apps.core.auth — the ORM chokepoint (BE-D14).

Uses RequestFactory + a DB-backed session to get a real request with a session.
No DRF APIClient — these are pure function tests, not endpoint tests.

All tests are marked django_db to allow ORM access via pytest-django.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory

from apps.core.errors import Conflict, Unauthorized

pytestmark = pytest.mark.django_db


def _db_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _fetch_auth_user(email: str) -> dict | None:
    """Fetch an auth_user row by email using raw psycopg (not ORM)."""
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        cur = conn.execute(
            "SELECT id, username, email, password FROM auth_user WHERE email = %s",
            (email,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "email": row[2], "password": row[3]}


def _make_request(path: str = "/") -> object:
    """Return a request with a real DB-backed session attached."""
    factory = RequestFactory()
    request = factory.post(path)

    session = SessionStore()
    session.create()
    request.session = session
    return request


def _unique_email(prefix: str = "auth_unit") -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.invalid"


# ---------------------------------------------------------------------------
# signup_user
# ---------------------------------------------------------------------------

def test_signup_user_creates_auth_user_row():
    """signup_user creates exactly one auth_user row with the given email."""
    from apps.core.auth import signup_user

    email = _unique_email("signup_creates")
    request = _make_request()

    user = signup_user(request, email=email, password="hunter2hunter")

    # Verify via the returned ORM user object (no cross-connection psycopg query
    # needed — ORM and test share the same transaction under pytest.mark.django_db).
    assert user.id is not None
    assert user.email == email
    assert user.username == email


def test_signup_user_hashes_password():
    """signup_user stores a hashed password, not plaintext."""
    from apps.core.auth import signup_user

    email = _unique_email("signup_hash")
    request = _make_request()

    user = signup_user(request, email=email, password="correct horse battery")

    # Django hashes with PBKDF2 by default (prefix "pbkdf2_")
    assert user.password.startswith("pbkdf2_"), (
        f"Expected PBKDF2 hash, got: {user.password[:20]!r}"
    )


def test_signup_user_duplicate_email_raises_conflict():
    """signup_user raises Conflict on duplicate email."""
    from apps.core.auth import signup_user

    email = _unique_email("signup_dup")
    request = _make_request()

    signup_user(request, email=email, password="first-password1")

    with pytest.raises(Conflict):
        signup_user(request, email=email, password="second-password2")


# ---------------------------------------------------------------------------
# authenticate_user
# ---------------------------------------------------------------------------

def test_authenticate_user_returns_user_on_correct_creds():
    """authenticate_user returns the User on correct email + password."""
    from apps.core.auth import authenticate_user, signup_user

    email = _unique_email("auth_ok")
    password = "correct-horse-battery"
    request = _make_request()

    # Create the user first.
    signup_user(request, email=email, password=password)

    # Re-authenticate with fresh request.
    request2 = _make_request()
    user = authenticate_user(request2, email=email, password=password)
    assert user.email == email


def test_authenticate_user_wrong_password_raises_unauthorized():
    """authenticate_user raises Unauthorized on wrong password."""
    from apps.core.auth import authenticate_user, signup_user

    email = _unique_email("auth_badpwd")
    request = _make_request()

    signup_user(request, email=email, password="right-password-123")

    request2 = _make_request()
    with pytest.raises(Unauthorized):
        authenticate_user(request2, email=email, password="wrong-password-456")


def test_authenticate_user_unknown_email_raises_unauthorized():
    """authenticate_user raises Unauthorized for unknown email (no enumeration)."""
    from apps.core.auth import authenticate_user

    request = _make_request()
    with pytest.raises(Unauthorized):
        authenticate_user(request, email="nobody@test.invalid", password="any-password")


# ---------------------------------------------------------------------------
# logout_user
# ---------------------------------------------------------------------------

def test_logout_user_clears_session():
    """logout_user calls django.contrib.auth.logout, clearing the session."""
    from apps.core.auth import logout_user, signup_user

    email = _unique_email("logout")
    request = _make_request()

    signup_user(request, email=email, password="logout-password1")

    # Confirm session has auth data before logout.
    assert "_auth_user_id" in request.session

    logout_user(request)

    assert "_auth_user_id" not in request.session

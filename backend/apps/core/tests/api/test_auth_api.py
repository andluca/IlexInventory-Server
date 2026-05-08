"""API tests for auth endpoints: signup, login, logout, me.

All tests use DRF's APIClient against the real test database.
Session cookies are managed by the test client.
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


_SIGNUP_URL = "/api/v1/auth/signup"
_LOGIN_URL = "/api/v1/auth/login"
_LOGOUT_URL = "/api/v1/auth/logout"
_ME_URL = "/api/v1/auth/me"


def _unique_email(prefix: str = "api") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.invalid"


# ---------------------------------------------------------------------------
# signup
# ---------------------------------------------------------------------------

def test_signup_happy_path():
    """POST /auth/signup with valid data returns 200 with user body + session cookie."""
    client = APIClient()
    email = _unique_email("signup_ok")

    resp = client.post(_SIGNUP_URL, {"email": email, "password": "validpass1"}, format="json")

    assert resp.status_code == 200
    data = resp.json()
    assert "user" in data
    assert data["user"]["email"] == email
    assert "id" in data["user"]
    assert "created_at" in data["user"]

    # Session cookie must be set.
    assert "sessionid" in resp.cookies


def test_signup_duplicate_email_returns_409():
    """Duplicate email signup returns 409 Conflict."""
    client = APIClient()
    email = _unique_email("signup_dup")

    client.post(_SIGNUP_URL, {"email": email, "password": "firstpassword"}, format="json")
    resp = client.post(_SIGNUP_URL, {"email": email, "password": "secondpassword"}, format="json")

    assert resp.status_code == 409
    data = resp.json()
    assert data["error"] == "Conflict"


def test_signup_malformed_email_returns_400():
    """Malformed email returns 400 with fields.email."""
    client = APIClient()

    resp = client.post(_SIGNUP_URL, {"email": "not-an-email", "password": "validpass1"}, format="json")

    assert resp.status_code == 400
    data = resp.json()
    assert "fields" in data
    assert "email" in data["fields"]


def test_signup_short_password_returns_400():
    """Password shorter than 8 chars returns 400 with fields.password."""
    client = APIClient()

    resp = client.post(_SIGNUP_URL, {"email": _unique_email("signup_short"), "password": "short"}, format="json")

    assert resp.status_code == 400
    data = resp.json()
    assert "fields" in data
    assert "password" in data["fields"]


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

def test_login_then_me_returns_same_user():
    """Login happy path: POST /auth/login then GET /auth/me returns same user."""
    client = APIClient()
    email = _unique_email("login_me")
    password = "correctpassword1"

    # First signup to create the user.
    client.post(_SIGNUP_URL, {"email": email, "password": password}, format="json")
    client.post(_LOGOUT_URL, format="json")  # clear signup session

    # Login.
    login_resp = client.post(_LOGIN_URL, {"email": email, "password": password}, format="json")
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["user"]["email"] == email

    # Me.
    me_resp = client.get(_ME_URL)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["user"]["id"] == login_data["user"]["id"]


def test_login_bad_password_returns_401():
    """Wrong password returns 401 Unauthorized."""
    client = APIClient()
    email = _unique_email("login_bad")

    client.post(_SIGNUP_URL, {"email": email, "password": "rightpassword"}, format="json")
    client.post(_LOGOUT_URL, format="json")

    resp = client.post(_LOGIN_URL, {"email": email, "password": "wrongpassword"}, format="json")

    assert resp.status_code == 401
    data = resp.json()
    assert data["error"] == "Unauthorized"


def test_login_unknown_email_returns_401():
    """Unknown email returns 401 — same envelope as wrong password (no enumeration)."""
    client = APIClient()

    resp = client.post(_LOGIN_URL, {"email": "nobody@test.invalid", "password": "anypassword"}, format="json")

    assert resp.status_code == 401
    data = resp.json()
    assert data["error"] == "Unauthorized"


# ---------------------------------------------------------------------------
# me
# ---------------------------------------------------------------------------

def test_me_without_session_returns_401():
    """GET /auth/me without a session cookie returns 401."""
    client = APIClient()

    resp = client.get(_ME_URL)

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------

def test_logout_then_me_returns_401():
    """After logout, GET /auth/me returns 401."""
    client = APIClient()
    email = _unique_email("logout_me")

    client.post(_SIGNUP_URL, {"email": email, "password": "logoutpass1"}, format="json")
    assert client.get(_ME_URL).status_code == 200

    client.post(_LOGOUT_URL, format="json")
    assert client.get(_ME_URL).status_code == 401


# ---------------------------------------------------------------------------
# session isolation
# ---------------------------------------------------------------------------

def test_two_users_have_isolated_sessions():
    """User A and user B have isolated sessions; /auth/me returns each user's own id."""
    client_a = APIClient()
    client_b = APIClient()

    email_a = _unique_email("isolation_a")
    email_b = _unique_email("isolation_b")

    resp_a = client_a.post(_SIGNUP_URL, {"email": email_a, "password": "passA12345"}, format="json")
    resp_b = client_b.post(_SIGNUP_URL, {"email": email_b, "password": "passB12345"}, format="json")

    id_a = resp_a.json()["user"]["id"]
    id_b = resp_b.json()["user"]["id"]

    me_a = client_a.get(_ME_URL).json()["user"]["id"]
    me_b = client_b.get(_ME_URL).json()["user"]["id"]

    assert me_a == id_a
    assert me_b == id_b
    assert id_a != id_b

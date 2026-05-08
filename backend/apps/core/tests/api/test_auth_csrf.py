"""CSRF policy tests for auth endpoints.

Verifies:
- signup and login are CSRF-exempt (no authentication_classes → no CSRF check)
- logout requires CSRF token (SessionAuthentication enforces it)

Uses Django's test Client with enforce_csrf_checks=True.

Note: DRF's SessionAuthentication checks CSRF for authenticated sessions.
For logout, the client must first obtain a CSRF token via cookie (set by
Django's CsrfViewMiddleware on any response), then pass it as X-CSRFToken.
"""

from __future__ import annotations

import uuid

import pytest
from django.test import Client
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


_SIGNUP_URL = "/api/v1/auth/signup"
_LOGIN_URL = "/api/v1/auth/login"
_LOGOUT_URL = "/api/v1/auth/logout"


def _unique_email(prefix: str = "csrf") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.invalid"


def test_signup_works_without_csrf_token():
    """POST /auth/signup succeeds with enforce_csrf_checks=True and no CSRF token."""
    client = Client(enforce_csrf_checks=True)
    email = _unique_email("signup_csrf")

    resp = client.post(
        _SIGNUP_URL,
        data={"email": email, "password": "validpass1"},
        content_type="application/json",
    )

    # 200 = CSRF not required (authentication_classes=[])
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.content}"


def test_login_works_without_csrf_token():
    """POST /auth/login succeeds with enforce_csrf_checks=True and no CSRF token."""
    # First create the user via the standard client (no CSRF enforcement).
    setup_client = APIClient()
    email = _unique_email("login_csrf")
    password = "validpass1"
    setup_client.post(_SIGNUP_URL, {"email": email, "password": password}, format="json")

    # Now test login without CSRF token.
    client = Client(enforce_csrf_checks=True)
    resp = client.post(
        _LOGIN_URL,
        data={"email": email, "password": password},
        content_type="application/json",
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.content}"


def test_logout_without_csrf_token_returns_403():
    """POST /auth/logout without CSRF token returns 403 (CSRF check enforced)."""
    # Signup + get session via normal client.
    setup_client = APIClient()
    email = _unique_email("logout_nocsrf")
    setup_client.post(_SIGNUP_URL, {"email": email, "password": "validpass1"}, format="json")

    # Use a Django test Client with CSRF enforcement; copy the session cookie.
    client = Client(enforce_csrf_checks=True)
    # Log in to get a session.
    client.post(
        _LOGIN_URL,
        data={"email": email, "password": "validpass1"},
        content_type="application/json",
    )

    # Logout without X-CSRFToken — must be rejected.
    resp = client.post(
        _LOGOUT_URL,
        content_type="application/json",
    )

    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.content}"


def test_logout_with_csrf_token_returns_204():
    """POST /auth/logout with X-CSRFToken returns 204."""
    client = Client(enforce_csrf_checks=True)
    email = _unique_email("logout_withcsrf")

    # Signup (CSRF-exempt → sets csrftoken cookie in response).
    resp = client.post(
        _SIGNUP_URL,
        data={"email": email, "password": "validpass1"},
        content_type="application/json",
    )

    # The CSRF cookie is set by Django's CsrfViewMiddleware on any response.
    # Retrieve it from the client's cookie jar.
    csrf_token = client.cookies.get("csrftoken")
    assert csrf_token is not None, "csrftoken cookie was not set after signup"

    resp = client.post(
        _LOGOUT_URL,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token.value,
    )

    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.content}"

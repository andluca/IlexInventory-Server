# ORM allowlist file (BE-D14). Do not import django.contrib.auth elsewhere.
"""Auth service functions — the single ORM chokepoint.

All three functions call into django.contrib.auth.  No other module in the
Ilex codebase may import from django.contrib.auth; the CI grep gate enforces
this constraint (see scripts/check_no_orm.sh and tests/unit/test_no_orm.py).
"""

from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import HttpRequest

from apps.core.errors import Conflict, Unauthorized


def signup_user(request: HttpRequest, email: str, password: str) -> User:
    """Create a new auth.User, log them in, and return the User.

    Raises:
        Conflict: if a User with the given email already exists.
    """
    if User.objects.filter(username=email).exists():
        raise Conflict(detail="Email already registered")

    user = User.objects.create_user(username=email, email=email, password=password)
    login(request, user)
    return user


def authenticate_user(request: HttpRequest, email: str, password: str) -> User:
    """Authenticate via email + password, log them in, and return the User.

    Raises:
        Unauthorized: if credentials are invalid (unknown email or wrong password).
        The same error is raised for both cases to prevent email enumeration.
    """
    user = authenticate(request, username=email, password=password)
    if user is None:
        raise Unauthorized(detail="Invalid credentials")

    login(request, user)
    return user  # type: ignore[return-value]


def logout_user(request: HttpRequest) -> None:
    """Clear the session via django.contrib.auth.logout."""
    logout(request)

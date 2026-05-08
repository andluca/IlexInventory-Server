"""Core API views.

Health is a leaf endpoint: it opens its own raw psycopg connection directly
instead of going through the services layer.  This is intentional — health
has no business logic and no owner-scoped data; routing it through a service
function would add indirection with zero benefit.  All other views MUST use
the services layer.

Auth views (signup, login, logout, me) delegate to apps.core.auth — the ORM
allowlist file (BE-D14).  Views catch DomainError and map to HTTP via
to_response().
"""

from __future__ import annotations

import logging

import psycopg
from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.auth import authenticate_user, logout_user, signup_user
from apps.core.errors import DomainError, to_response
from apps.core.serializers import LoginRequest, SignupRequest, UserResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Inline response serializers (for OpenAPI schema only — not used for parsing)
# ---------------------------------------------------------------------------

_HealthChecksSerializer = inline_serializer(
    name="HealthChecks",
    fields={"postgres": serializers.CharField()},
)

_HealthOkSerializer = inline_serializer(
    name="HealthOk",
    fields={
        "status": serializers.CharField(),
        "checks": _HealthChecksSerializer,
    },
)

_HealthDegradedSerializer = inline_serializer(
    name="HealthDegraded",
    fields={
        "status": serializers.CharField(),
        "checks": _HealthChecksSerializer,
    },
)


class HealthView(APIView):
    """Liveness probe with Postgres reachability check.

    Anonymous — no auth, no CSRF (GET only).
    """

    authentication_classes = []
    permission_classes = []

    @extend_schema(
        tags=["meta"],
        responses={
            200: _HealthOkSerializer,
            503: _HealthDegradedSerializer,
        },
        auth=[],
        summary="Liveness probe with Postgres reachability check",
    )
    def get(self, request: Request) -> Response:
        try:
            with psycopg.connect(
                settings.DATABASE_URL,
                connect_timeout=1,
                options="-c statement_timeout=1000",
            ) as conn:
                conn.execute("SELECT 1")
            return Response(
                {"status": "ok", "checks": {"postgres": "ok"}},
                status=status.HTTP_200_OK,
            )
        except psycopg.OperationalError as exc:
            logger.warning("Health check: Postgres unreachable (%s)", type(exc).__name__)
            return Response(
                {"status": "degraded", "checks": {"postgres": "down"}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:  # noqa: BLE001 — backstop; keeps the process alive
            logger.warning(
                "Health check: unexpected error (%s)", type(exc).__name__, exc_info=True
            )
            return Response(
                {"status": "degraded", "checks": {"postgres": "down"}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------


class SignupView(APIView):
    """Create a new account and log in immediately.

    CSRF-exempt: client cannot have a CSRF token before first login.
    Achieved by setting authentication_classes=[] which disables DRF's
    SessionAuthentication CSRF enforcement.
    """

    authentication_classes = []
    permission_classes = []

    @extend_schema(
        tags=["auth"],
        request=None,
        responses={200: None},
        auth=[],
        summary="Sign up a new account",
    )
    def post(self, request: Request) -> Response:
        serializer = SignupRequest(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "ValidationError", "fields": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = signup_user(
                request._request,
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response({"user": UserResponse(user).data}, status=status.HTTP_200_OK)


class LoginView(APIView):
    """Authenticate an existing user and set session cookie.

    CSRF-exempt: same reasoning as SignupView.
    """

    authentication_classes = []
    permission_classes = []

    @extend_schema(
        tags=["auth"],
        request=None,
        responses={200: None},
        auth=[],
        summary="Log in with email and password",
    )
    def post(self, request: Request) -> Response:
        serializer = LoginRequest(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "ValidationError", "fields": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = authenticate_user(
                request._request,
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response({"user": UserResponse(user).data}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """Clear the session. Requires an active session (IsAuthenticated).

    CSRF token required (default SessionAuthentication behavior).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["auth"],
        responses={204: None},
        summary="Log out the current session",
    )
    def post(self, request: Request) -> Response:
        logout_user(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Return the currently authenticated user.

    Returns 401 when no session is present (IsAuthenticated default).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["auth"],
        responses={200: None},
        summary="Return the current authenticated user",
    )
    def get(self, request: Request) -> Response:
        return Response({"user": UserResponse(request.user).data}, status=status.HTTP_200_OK)

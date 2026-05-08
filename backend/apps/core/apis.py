"""Core API views.

Health is a leaf endpoint: it opens its own raw psycopg connection directly
instead of going through the services layer.  This is intentional — health
has no business logic and no owner-scoped data; routing it through a service
function would add indirection with zero benefit.  All other views MUST use
the services layer.
"""

from __future__ import annotations

import logging

import psycopg
from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

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
        responses={
            200: _HealthOkSerializer,
            503: _HealthDegradedSerializer,
        },
        auth=[],
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

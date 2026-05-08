"""Custom DRF exception handler.

Converts DRF's default 403 "not authenticated" response to 401, matching
SPEC §2.4 which specifies HTTP 401 for missing/invalid session credentials.

DRF returns 403 by default when:
  - All authentication classes return None (anonymous request)
  - IsAuthenticated rejects the request
  - No WWW-Authenticate header is set (SessionAuthentication has none)

This handler intercepts that case and maps it to 401.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF exception handler that maps unauthenticated access to 401."""
    response = drf_exception_handler(exc, context)

    if response is not None and isinstance(exc, NotAuthenticated):
        response.status_code = status.HTTP_401_UNAUTHORIZED

    return response

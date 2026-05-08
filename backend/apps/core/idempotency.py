"""Idempotency-Key view decorator.

Reads the ``Idempotency-Key`` header from the request, looks up
``(owner_id, key, endpoint)`` in the ``idempotency_keys`` table, and:

  - Cache hit  → return the cached (status, body) without running the view.
  - Cache miss → run the view, then INSERT the (status, body) before returning.
    Uses ``ON CONFLICT DO NOTHING`` so concurrent retries are race-safe.
  - Missing header → 400 ValidationError.

``owner_id`` is taken from ``request.user.id``.

Endpoints that require this decorator (SPEC §2.6):
  - POST /purchase-orders/{id}/receive       → "purchase_orders.receive"
  - POST /sales-orders/{id}/commit           → "sales_orders.commit"
  - POST /batches                            → "batches.create"
  - POST /batches/{id}/movements (write_off) → "batches.write_off"
  - POST /batches/{id}/recall                → "batches.recall"
  - POST /batches/{id}/un-recall             → "batches.un_recall"
  - POST /sales-orders/{id}/void             → "sales_orders.void"
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Any

import psycopg
from django.conf import settings
from rest_framework.request import Request
from rest_framework.response import Response


def idempotent(endpoint: str) -> Callable:
    """View decorator — enforces Idempotency-Key caching on mutating endpoints.

    ``endpoint`` is the route identifier string (e.g. ``"purchase_orders.receive"``),
    NOT the URL path — keeps the cache key stable across URL refactors.
    """

    def decorator(view_method: Callable) -> Callable:
        @functools.wraps(view_method)
        def wrapper(self_or_view, request: Request, *args: Any, **kwargs: Any) -> Response:
            idempotency_key = request.META.get("HTTP_IDEMPOTENCY_KEY")
            if not idempotency_key:
                from apps.core.errors import ValidationError, to_response

                body, status = to_response(
                    ValidationError(
                        detail="Idempotency-Key header required"
                    )
                )
                return Response(body, status=status)

            owner_id = request.user.id
            db_url = settings.DATABASE_URL

            # Check for a cached response.
            cached = _lookup_cache(db_url, owner_id, idempotency_key, endpoint)
            if cached is not None:
                cached_status, cached_body = cached
                return Response(cached_body, status=cached_status)

            # Cache miss — run the view.
            response = view_method(self_or_view, request, *args, **kwargs)

            # Persist the response before returning (race-safe with ON CONFLICT DO NOTHING).
            _store_cache(db_url, owner_id, idempotency_key, endpoint, response)

            return response

        return wrapper

    return decorator


def _lookup_cache(
    db_url: str,
    owner_id: Any,
    key: str,
    endpoint: str,
) -> tuple[int, Any] | None:
    """Return (status, body) from idempotency_keys, or None on cache miss."""
    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT response_status, response_body
                      FROM idempotency_keys
                     WHERE owner_id = %s AND key = %s AND endpoint = %s
                    """,
                    (str(owner_id), key, endpoint),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return row[0], row[1]
    except psycopg.Error:
        # Cache lookup failure: treat as miss so the view can still execute.
        return None


def _store_cache(
    db_url: str,
    owner_id: Any,
    key: str,
    endpoint: str,
    response: Response,
) -> None:
    """Persist (status, body) in idempotency_keys with ON CONFLICT DO NOTHING."""
    # Render the response to get the JSON body before storage.
    try:
        if hasattr(response, "data"):
            body = response.data
        else:
            body = {}
    except Exception:  # noqa: BLE001
        body = {}

    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO idempotency_keys
                           (owner_id, key, endpoint, response_status, response_body)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (owner_id, key, endpoint) DO NOTHING
                    """,
                    (
                        str(owner_id),
                        key,
                        endpoint,
                        response.status_code,
                        json.dumps(body),
                    ),
                )
    except psycopg.Error:
        # Storage failure is non-fatal: the view already ran successfully.
        # The next retry will re-execute the handler (cache miss again).
        pass

"""Idempotency-Key view decorator.

Reads the ``Idempotency-Key`` header from the request, looks up
``(owner_id, key, endpoint)`` in the ``idempotency_keys`` table, and:

  - Cache hit  → return the cached (status, body) without running the view.
  - Cache miss → run the view, then INSERT the (status, body) before returning.
    A transaction-scoped advisory lock keyed by (owner_id, endpoint, key)
    serializes concurrent requests for the same key, so the view body
    executes exactly once even under concurrent retries.
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
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import ValidationError, to_response
from apps.core.idempotency_queries import cache_insert, cache_lookup

_JSON_RENDERER = JSONRenderer()


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
                body, status = to_response(
                    ValidationError(
                        detail="Idempotency-Key header required"
                    )
                )
                return Response(body, status=status)

            owner_id = int(request.user.id)
            return _run_with_idempotency(
                view_method=view_method,
                self_or_view=self_or_view,
                request=request,
                args=args,
                kwargs=kwargs,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                endpoint=endpoint,
            )

        return wrapper

    return decorator


def _run_with_idempotency(
    *,
    view_method: Callable,
    self_or_view: Any,
    request: Request,
    args: tuple,
    kwargs: dict,
    owner_id: int,
    idempotency_key: str,
    endpoint: str,
) -> Response:
    """Atomic lookup → (view → insert) cycle under a per-key advisory lock.

    The lock is transaction-scoped, so the lookup and the subsequent
    insert (if any) run inside one transaction on one connection. Concurrent
    requests for the same (owner_id, endpoint, idempotency_key) block on the
    lock; the loser unblocks AFTER the winner commits, finds the cached
    response, and returns it without re-running the view.

    Lock acquisition failure or any other psycopg error falls back to
    executing the view without idempotency protection — matches the previous
    "permissive on cache failure" behaviour to avoid blocking writes when
    the cache table is unreachable.
    """
    db_url = settings.DATABASE_URL
    lock_payload = f"{owner_id}:{endpoint}:{idempotency_key}"

    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (lock_payload,),
                )

                cached = cache_lookup(
                    cur, owner_id=owner_id, key=idempotency_key, endpoint=endpoint
                )
                if cached is not None:
                    conn.commit()
                    cached_status, cached_body = cached
                    return Response(cached_body, status=cached_status)

            response = view_method(self_or_view, request, *args, **kwargs)
            body_text = _rendered_body_text(response)

            with conn.cursor() as cur:
                cache_insert(
                    cur,
                    owner_id=owner_id,
                    key=idempotency_key,
                    endpoint=endpoint,
                    status=response.status_code,
                    body_text=body_text,
                )
            conn.commit()
            return response
    except psycopg.Error:
        # Cache subsystem failure: fall back to unprotected execution so the
        # endpoint stays available. Matches the prior best-effort semantics.
        return view_method(self_or_view, request, *args, **kwargs)


def _rendered_body_text(response: Response) -> str:
    """Return the response body as JSON text, using DRF's renderer when needed.

    DRF's `Response.data` may contain Decimal/datetime/UUID instances; the
    standard `json.dumps` raises TypeError on those. Calling `render()` runs
    the configured renderer (typically `JSONRenderer`) which knows how to
    serialize them. For a 204 / no-data response, return "{}" so the column
    (typed `jsonb`) accepts it.
    """
    if not hasattr(response, "data") or response.data is None:
        return "{}"
    if not getattr(response, "is_rendered", False):
        try:
            response.accepted_renderer = response.accepted_renderer or _JSON_RENDERER
            response.accepted_media_type = "application/json"
            response.renderer_context = response.renderer_context or {}
            response.render()
        except Exception:  # noqa: BLE001 — fall back to permissive serialization
            return json.dumps(response.data, default=str)
    return response.content.decode("utf-8")

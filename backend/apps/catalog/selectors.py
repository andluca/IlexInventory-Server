"""Read-only selectors for apps.catalog.

Selectors open a connection, call query functions, close. They do not open
transactions (reads are non-mutating). They return plain dicts or None.
"""

from __future__ import annotations

import psycopg
from django.conf import settings

from apps.catalog.queries.products import (
    list_products as _list_products,
    select_product_by_id,
)


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.DATABASE_URL)


def list_products(
    *,
    owner_id: int,
    search: str | None = None,
    archived: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return a paginated list of products for the given owner.

    Returns:
        {
          "items": [ProductRow, ...],
          "total": int,
          "limit": int,
          "offset": int,
        }
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            rows, total = _list_products(
                cur,
                params={
                    "owner_id": owner_id,
                    "search": search,
                    "archived": archived,
                    "limit": limit,
                    "offset": offset,
                },
            )

    # Convert UUIDs to strings for serialisation.
    items = []
    for row in rows:
        r = dict(row)
        if "id" in r and not isinstance(r["id"], str):
            r["id"] = str(r["id"])
        items.append(r)

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def product_by_id(*, owner_id: int, product_id: str) -> dict | None:
    """Return a single product dict or None if not found / cross-owner.

    API layer maps None to 404 (D4 — 404 not 403).
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            row = select_product_by_id(
                cur, params={"id": str(product_id), "owner_id": owner_id}
            )

    if row is None:
        return None

    r = dict(row)
    if "id" in r and not isinstance(r["id"], str):
        r["id"] = str(r["id"])
    return r

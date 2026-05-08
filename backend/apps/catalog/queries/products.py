"""SQL query functions for the products aggregate.

Rules:
- One function = one SQL statement.
- Every owner-scoped function is decorated with @scoped.
- The caller (service) provides the cursor and owns the transaction.
- No business logic. No conditionals beyond parameterizing the SQL.
"""

from __future__ import annotations

from apps.core.owner_scope import scoped


def _row_to_dict(cur, row) -> dict:
    """Convert a cursor row to a dict using cursor.description column names."""
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


@scoped
def insert_product(cur, *, params: dict) -> dict:
    """INSERT a new product row. Returns the inserted row as a dict.

    Caller is responsible for catching psycopg.errors.UniqueViolation
    (constraint: products_owner_sku_unique) and mapping to DuplicateSKU.
    """
    cur.execute(
        """
        INSERT INTO products (owner_id, sku, name, description, base_unit)
        VALUES (%(owner_id)s, %(sku)s, %(name)s, %(description)s, %(base_unit)s)
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def select_product_by_id(cur, *, params: dict) -> dict | None:
    """SELECT a single product by (id, owner_id). Returns None on miss.

    Cross-owner access returns None — caller maps to 404 (D4).
    """
    cur.execute(
        """
        SELECT * FROM products
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def update_product_fields(cur, *, params: dict) -> dict | None:
    """UPDATE name and/or description on (id, owner_id). Returns updated row or None.

    Only the fields present in params (beyond id/owner_id) are updated.
    SQL is composed dynamically so a NULL value means "leave unchanged".
    Returns None if the product does not exist or belongs to another owner.
    """
    updates: list[str] = []
    if "name" in params and params["name"] is not None:
        updates.append("name = %(name)s")
    if "description" in params and params["description"] is not None:
        updates.append("description = %(description)s")

    if not updates:
        # Nothing to update — return the existing row unchanged.
        return select_product_by_id(cur, params=params)

    updates.append("updated_at = NOW()")
    set_clause = ", ".join(updates)

    cur.execute(
        f"""
        UPDATE products
           SET {set_clause}
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        RETURNING *
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def set_archived_at(cur, *, params: dict) -> dict | None:
    """UPDATE archived_at = NOW() on (id, owner_id) WHERE archived_at IS NULL.

    Idempotent: if already archived, the WHERE clause matches 0 rows and
    this returns None. Caller decides whether to re-select for the response.
    """
    cur.execute(
        """
        UPDATE products
           SET archived_at = NOW(), updated_at = NOW()
         WHERE id = %(id)s AND owner_id = %(owner_id)s
           AND archived_at IS NULL
        RETURNING *
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def delete_product(cur, *, params: dict) -> int:
    """DELETE a product by (id, owner_id). Returns rowcount (0 or 1)."""
    cur.execute(
        """
        DELETE FROM products
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        """,
        params,
    )
    return cur.rowcount


@scoped
def list_products(cur, *, params: dict) -> tuple[list[dict], int]:
    """Paginated SELECT with optional search (ILIKE on name/sku) and archived filter.

    params keys:
      owner_id  : int
      search    : str | None  — ILIKE match on name or sku
      archived  : bool | None — True=archived only, False=active only, None=all
      limit     : int
      offset    : int

    Returns (rows, total_count).
    """
    where_parts = ["owner_id = %(owner_id)s"]
    query_params: dict = {"owner_id": params["owner_id"]}

    if params.get("search"):
        where_parts.append("(name ILIKE %(search_pat)s OR sku ILIKE %(search_pat)s)")
        query_params["search_pat"] = f"%{params['search']}%"

    archived = params.get("archived")
    if archived is True:
        where_parts.append("archived_at IS NOT NULL")
    elif archived is False:
        where_parts.append("archived_at IS NULL")
    # None → no filter

    where_sql = " AND ".join(where_parts)

    # Count first
    cur.execute(f"SELECT COUNT(*) FROM products WHERE {where_sql}", query_params)
    total = cur.fetchone()[0]

    # Fetch page
    query_params["limit"] = params["limit"]
    query_params["offset"] = params["offset"]
    cur.execute(
        f"""
        SELECT * FROM products
         WHERE {where_sql}
         ORDER BY created_at DESC, id DESC
         LIMIT %(limit)s OFFSET %(offset)s
        """,
        query_params,
    )
    cols = [d.name for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    return rows, total


@scoped
def count_batches_for_product(cur, *, params: dict) -> int:
    """Return the number of batches referencing this product.

    STUB: the `batches` table does not exist until Issue 006.
    Probes information_schema.tables first; if absent returns 0.
    Issue 006 replaces this body with a real SELECT COUNT(*) FROM batches.

    params keys:
      owner_id   : int
      product_id : str (UUID)
    """
    cur.execute(
        """
        SELECT COUNT(*)
          FROM information_schema.tables
         WHERE table_schema = 'public'
           AND table_name = 'batches'
        """
    )
    batches_exists = cur.fetchone()[0] > 0
    if not batches_exists:
        return 0

    cur.execute(
        """
        SELECT COUNT(*)
          FROM batches
         WHERE product_id = %(product_id)s AND owner_id = %(owner_id)s
        """,
        params,
    )
    return cur.fetchone()[0]

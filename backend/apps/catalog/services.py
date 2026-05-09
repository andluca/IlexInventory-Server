"""Business-logic services for apps.catalog.

Rules:
- Kwarg-only functions (past owner_id). Type-annotated.
- Accept typed Python data; return typed Python data.
- Raise from apps.catalog.errors — never raw psycopg errors.
- Open their own psycopg connection; wrap mutations in a transaction.
- Never accept owner_id from the request body — API layer passes request.user.id.
"""

from __future__ import annotations

import csv
import io
from uuid import UUID

import psycopg
import psycopg.errors

from apps.core.db import connect as _connect

from apps.catalog.errors import (
    DuplicateSKU,
    ProductHasBatches,
    ProductHasNoBatches,
    ProductNotFound,
)
from apps.catalog.queries.products import (
    count_batches_for_product,
    delete_product as _delete_product,
    insert_product,
    select_product_by_id,
    set_archived_at,
    update_product_fields,
)
from apps.catalog.types import FailedRow, ImportReport, ProductRow

_VALID_BASE_UNITS = frozenset({"g", "ml", "unit"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_product(row: dict) -> ProductRow:
    """Coerce a query result dict to ProductRow, converting UUID to str."""
    row = dict(row)
    if "id" in row and not isinstance(row["id"], str):
        row["id"] = str(row["id"])
    return row  # type: ignore[return-value]


def _parse_csv_bytes(csv_bytes: bytes) -> list[dict[str, str]]:
    """Parse CSV bytes into a list of row dicts. Strips BOM, handles CRLF/LF."""
    text = csv_bytes.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        rows.append(dict(row))
    return rows


def _validate_csv_row(row: dict[str, str]) -> tuple[dict[str, str] | None, FailedRow | None]:
    """Validate a single CSV row. Returns (clean_row, None) or (None, FailedRow)."""
    fields: dict[str, list[str]] = {}

    sku = (row.get("sku") or "").strip()
    if not sku:
        fields["sku"] = ["This field may not be blank."]

    name = (row.get("name") or "").strip()
    if not name:
        fields["name"] = ["This field may not be blank."]

    base_unit = (row.get("base_unit") or "").strip()
    if base_unit not in _VALID_BASE_UNITS:
        fields["base_unit"] = [
            f'"{base_unit}" is not a valid base_unit. Must be one of: g, ml, unit.'
        ]

    if fields:
        return None, FailedRow(
            row_index=0,  # set by caller
            error="ValidationError",
            detail="Row validation failed.",
            fields=fields,
        )

    return {
        "sku": sku,
        "name": name,
        "description": (row.get("description") or "").strip(),
        "base_unit": base_unit,
    }, None


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def create_product(
    *,
    owner_id: int,
    sku: str,
    name: str,
    description: str = "",
    base_unit: str,
) -> ProductRow:
    """Insert a new product. Raises DuplicateSKU on constraint violation."""
    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                row = insert_product(
                    cur,
                    params={
                        "owner_id": owner_id,
                        "sku": sku,
                        "name": name,
                        "description": description,
                        "base_unit": base_unit,
                    },
                )
            conn.commit()
        except psycopg.errors.UniqueViolation as exc:
            conn.rollback()
            if "products_owner_sku_unique" in str(exc):
                raise DuplicateSKU(detail=f"SKU '{sku}' already exists for this owner.")
            raise

    return _row_to_product(row)


def update_product(
    *,
    owner_id: int,
    product_id: UUID,
    name: str | None = None,
    description: str | None = None,
) -> ProductRow:
    """Update name and/or description. Raises ProductNotFound on cross-owner or missing."""
    with _connect() as conn:
        with conn.cursor() as cur:
            row = update_product_fields(
                cur,
                params={
                    "id": str(product_id),
                    "owner_id": owner_id,
                    "name": name,
                    "description": description,
                },
            )
        conn.commit()

    if row is None:
        raise ProductNotFound(detail=f"Product {product_id} not found.")

    return _row_to_product(row)


def archive_product(*, owner_id: int, product_id: UUID) -> ProductRow:
    """Soft-delete a product by setting archived_at.

    Raises:
      ProductNotFound       — if product doesn't belong to owner.
      ProductHasNoBatches   — if the product has no batches (caller should DELETE).
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            # Existence check first.
            existing = select_product_by_id(
                cur, params={"id": str(product_id), "owner_id": owner_id}
            )
            if existing is None:
                raise ProductNotFound(detail=f"Product {product_id} not found.")

            batch_count = count_batches_for_product(
                cur, params={"product_id": str(product_id), "owner_id": owner_id}
            )
            if batch_count == 0:
                raise ProductHasNoBatches(
                    detail="Product has no batches. Use DELETE to remove it instead."
                )

            result = set_archived_at(
                cur, params={"id": str(product_id), "owner_id": owner_id}
            )
            # Idempotent: if already archived, re-read the current row.
            if result is None:
                result = select_product_by_id(
                    cur, params={"id": str(product_id), "owner_id": owner_id}
                )
        conn.commit()

    return _row_to_product(result)


def delete_product(*, owner_id: int, product_id: UUID) -> None:
    """Hard-delete a product. Product must have zero batches.

    Raises:
      ProductNotFound    — cross-owner or missing.
      ProductHasBatches  — batches exist; caller should archive instead.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            existing = select_product_by_id(
                cur, params={"id": str(product_id), "owner_id": owner_id}
            )
            if existing is None:
                raise ProductNotFound(detail=f"Product {product_id} not found.")

            batch_count = count_batches_for_product(
                cur, params={"product_id": str(product_id), "owner_id": owner_id}
            )
            if batch_count > 0:
                raise ProductHasBatches(
                    detail="Product has batches. Use archive instead."
                )

            _delete_product(cur, params={"id": str(product_id), "owner_id": owner_id})
        conn.commit()


def import_products_csv(*, owner_id: int, csv_bytes: bytes) -> ImportReport:
    """Parse a CSV file and import products row-by-row with per-row savepoints.

    Never raises for individual bad rows — they are collected in the returned
    ImportReport. Always returns ImportReport.
    """
    rows = _parse_csv_bytes(csv_bytes)
    imported = 0
    failed: list[FailedRow] = []

    with _connect() as conn:
        for idx, raw_row in enumerate(rows):
            clean_row, row_error = _validate_csv_row(raw_row)
            if row_error is not None:
                row_error = FailedRow(
                    row_index=idx,
                    error=row_error["error"],
                    detail=row_error.get("detail"),
                    fields=row_error.get("fields"),
                )
                failed.append(row_error)
                continue

            # Use a savepoint per row so a failure doesn't abort the whole batch.
            sp_name = f"sp_row_{idx}"
            try:
                conn.execute(f"SAVEPOINT {sp_name}")
                with conn.cursor() as cur:
                    insert_product(
                        cur,
                        params={
                            "owner_id": owner_id,
                            "sku": clean_row["sku"],
                            "name": clean_row["name"],
                            "description": clean_row["description"],
                            "base_unit": clean_row["base_unit"],
                        },
                    )
                conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                imported += 1
            except psycopg.errors.UniqueViolation:
                conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                failed.append(
                    FailedRow(
                        row_index=idx,
                        error="DuplicateSKU",
                        detail=f"SKU '{clean_row['sku']}' already exists.",
                        fields=None,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — unexpected errors become failed rows
                conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                failed.append(
                    FailedRow(
                        row_index=idx,
                        error="Error",
                        detail=str(exc),
                        fields=None,
                    )
                )

        conn.commit()

    return ImportReport(imported=imported, failed=failed)

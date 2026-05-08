"""Service tests for receive_purchase_order.

Behavioral: assert return values and post_db state. No mocking.

ILEX-005 scope:
- Tests assert the header transition (status='received', received_at non-null).
- Batch + movement assertions are deferred to ILEX-006 (inventory tables don't
  exist yet; create_receipt_batches is a no-op stub in this issue).

TODO(ILEX-006): Amend this file to add post_db assertions for batches and
stock_movements once 0005_inventory.sql and the real create_receipt_batches
implementation land.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import os

import psycopg
import pytest

from apps.procurement.errors import (
    PurchaseOrderAlreadyReceived,
    PurchaseOrderNotFound,
    ReceiveLinesMismatch,
)
from apps.procurement.services import (
    create_purchase_order_draft,
    receive_purchase_order,
)

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


def _seed_user(uid: int) -> None:
    email = f"svc_rcv_{uid}@test.invalid"
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO auth_user (id, username, email, password,
                                   is_superuser, is_staff, is_active,
                                   first_name, last_name, date_joined)
            VALUES (%s, %s, %s, 'unusable!', false, false, true, '', '', NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            (uid, email, email),
        )


def _seed_product(owner_id: int) -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, f"SKU-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


def _create_po(owner_id: int, product_id: str) -> dict:
    return create_purchase_order_draft(
        owner_id=owner_id,
        supplier_name="Supplier",
        supplier_contact=None,
        lines=[
            {"product_id": product_id, "quantity": Decimal("10.0000"), "unit_cost": Decimal("2.0000")}
        ],
    )


# ---------------------------------------------------------------------------
# Happy path — header flipped to received
# ---------------------------------------------------------------------------

def test_receive_po_happy_path():
    """Receive a draft PO; status flips to 'received', received_at populated.

    ILEX-005: Only asserts procurement-side state. Batch + movement assertions
    are added in ILEX-006 when inventory schema lands.
    """
    owner_id = 6301
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    po = _create_po(owner_id, product_id)
    po_id = uuid.UUID(str(po["id"]))
    line_id = str(po["lines"][0]["id"])

    result = receive_purchase_order(
        owner_id=owner_id,
        po_id=po_id,
        line_metadata=[
            {
                "line_id": line_id,
                "batch_code": "BATCH-2026-001",
                "expiration_date": "2027-12-31",
            }
        ],
    )

    assert result["status"] == "received"
    assert result["received_at"] is not None

    # Verify DB state directly
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        row = conn.execute(
            "SELECT status, received_at FROM purchase_orders WHERE id = %s",
            (str(po_id),),
        ).fetchone()
    assert row[0] == "received"
    assert row[1] is not None


# ---------------------------------------------------------------------------
# Receive on missing PO → PurchaseOrderNotFound
# ---------------------------------------------------------------------------

def test_receive_missing_po_raises_not_found():
    """Receive on non-existent PO → PurchaseOrderNotFound."""
    owner_id = 6302
    _seed_user(owner_id)
    phantom_id = uuid.uuid4()

    with pytest.raises(PurchaseOrderNotFound):
        receive_purchase_order(
            owner_id=owner_id,
            po_id=phantom_id,
            line_metadata=[],
        )


# ---------------------------------------------------------------------------
# Receive on already-received PO → PurchaseOrderAlreadyReceived
# ---------------------------------------------------------------------------

def test_receive_already_received_raises_conflict():
    """Receive on already-received PO → PurchaseOrderAlreadyReceived (409)."""
    owner_id = 6303
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    po = _create_po(owner_id, product_id)
    po_id = uuid.UUID(str(po["id"]))
    line_id = str(po["lines"][0]["id"])

    # First receive (success)
    receive_purchase_order(
        owner_id=owner_id,
        po_id=po_id,
        line_metadata=[
            {"line_id": line_id, "batch_code": "BATCH-001", "expiration_date": None}
        ],
    )

    # Second receive → conflict
    with pytest.raises(PurchaseOrderAlreadyReceived):
        receive_purchase_order(
            owner_id=owner_id,
            po_id=po_id,
            line_metadata=[
                {"line_id": line_id, "batch_code": "BATCH-001", "expiration_date": None}
            ],
        )


# ---------------------------------------------------------------------------
# Mismatched line_ids → ReceiveLinesMismatch
# ---------------------------------------------------------------------------

def test_receive_mismatched_line_ids_raises_mismatch():
    """line_metadata with wrong line_ids → ReceiveLinesMismatch (400)."""
    owner_id = 6304
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    po = _create_po(owner_id, product_id)
    po_id = uuid.UUID(str(po["id"]))
    wrong_line_id = str(uuid.uuid4())

    with pytest.raises(ReceiveLinesMismatch):
        receive_purchase_order(
            owner_id=owner_id,
            po_id=po_id,
            line_metadata=[
                {"line_id": wrong_line_id, "batch_code": "BATCH-001", "expiration_date": None}
            ],
        )


# ---------------------------------------------------------------------------
# Cross-owner receive → PurchaseOrderNotFound
# ---------------------------------------------------------------------------

def test_receive_cross_owner_raises_not_found():
    """Receive another owner's PO → PurchaseOrderNotFound (D4)."""
    owner_a = 6305
    owner_b = 6306
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)
    po = _create_po(owner_a, product_a)
    po_id = uuid.UUID(str(po["id"]))
    line_id = str(po["lines"][0]["id"])

    with pytest.raises(PurchaseOrderNotFound):
        receive_purchase_order(
            owner_id=owner_b,
            po_id=po_id,
            line_metadata=[
                {"line_id": line_id, "batch_code": "BATCH-001", "expiration_date": None}
            ],
        )

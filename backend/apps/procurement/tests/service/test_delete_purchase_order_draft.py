"""Service tests for delete_purchase_order_draft.

Behavioral: assert DB state after deletion. No mocking.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import psycopg
import pytest

from apps.procurement.errors import (
    PurchaseOrderNotDraft,
    PurchaseOrderNotFound,
)
from apps.procurement.services import (
    create_purchase_order_draft,
    delete_purchase_order_draft,
)

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


def _seed_user(uid: int) -> None:
    email = f"svc_del_{uid}@test.invalid"
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


def _create_po(owner_id: int, product_id: str) -> str:
    result = create_purchase_order_draft(
        owner_id=owner_id,
        supplier_name="Supplier",
        supplier_contact=None,
        lines=[
            {"product_id": product_id, "quantity": Decimal("1.0000"), "unit_cost": Decimal("1.0000")}
        ],
    )
    return str(result["id"])


# ---------------------------------------------------------------------------
# Happy path — delete draft; header and lines gone
# ---------------------------------------------------------------------------

def test_delete_draft_happy_path():
    """Delete a draft PO; header gone, lines cascaded."""
    owner_id = 6201
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    po_id_str = _create_po(owner_id, product_id)
    po_id = uuid.UUID(po_id_str)

    delete_purchase_order_draft(owner_id=owner_id, po_id=po_id)

    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE id = %s AND owner_id = %s",
            (po_id_str, owner_id),
        ).fetchone()[0]
        line_count = conn.execute(
            "SELECT COUNT(*) FROM purchase_order_lines WHERE purchase_order_id = %s",
            (po_id_str,),
        ).fetchone()[0]

    assert row == 0
    assert line_count == 0


# ---------------------------------------------------------------------------
# Delete received → PurchaseOrderNotDraft
# ---------------------------------------------------------------------------

def test_delete_received_po_raises_not_draft():
    """DELETE on received PO → PurchaseOrderNotDraft."""
    owner_id = 6202
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    po_id_str = _create_po(owner_id, product_id)

    # Manually receive
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            UPDATE purchase_orders
               SET status = 'received', received_at = NOW(), updated_at = NOW()
             WHERE id = %s
            """,
            (po_id_str,),
        )

    with pytest.raises(PurchaseOrderNotDraft):
        delete_purchase_order_draft(owner_id=owner_id, po_id=uuid.UUID(po_id_str))


# ---------------------------------------------------------------------------
# Cross-owner delete → PurchaseOrderNotFound; state unchanged
# ---------------------------------------------------------------------------

def test_delete_cross_owner_raises_not_found():
    """DELETE another owner's PO → PurchaseOrderNotFound (D4)."""
    owner_a = 6203
    owner_b = 6204
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)
    po_id_str = _create_po(owner_a, product_a)
    po_id = uuid.UUID(po_id_str)

    with psycopg.connect(_DB_URL, autocommit=True) as pre:
        pre_count = pre.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE id = %s", (po_id_str,)
        ).fetchone()[0]

    with pytest.raises(PurchaseOrderNotFound):
        delete_purchase_order_draft(owner_id=owner_b, po_id=po_id)

    with psycopg.connect(_DB_URL, autocommit=True) as post:
        post_count = post.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE id = %s", (po_id_str,)
        ).fetchone()[0]

    # State unchanged
    assert pre_count == post_count

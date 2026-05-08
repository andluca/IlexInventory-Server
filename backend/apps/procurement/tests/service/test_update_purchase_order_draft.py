"""Service tests for update_purchase_order_draft.

Behavioral: assert return values and post_db state. No mocking.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import psycopg
import pytest

from apps.procurement.errors import (
    ProductNotFound,
    PurchaseOrderNotDraft,
    PurchaseOrderNotFound,
    ValidationError,
)
from apps.procurement.services import (
    create_purchase_order_draft,
    receive_purchase_order,
    update_purchase_order_draft,
)

pytestmark = pytest.mark.django_db

import os
_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _seed_user(uid: int) -> None:
    email = f"svc_upd_{uid}@test.invalid"
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
        supplier_name="Original Supplier",
        supplier_contact=None,
        lines=[
            {"product_id": product_id, "quantity": Decimal("1.0000"), "unit_cost": Decimal("1.0000")}
        ],
    )
    return str(result["id"])


# ---------------------------------------------------------------------------
# Update supplier_name only — lines untouched
# ---------------------------------------------------------------------------

def test_update_supplier_name_only():
    """Updating supplier_name only leaves lines untouched."""
    owner_id = 6101
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    po_id = uuid.UUID(_create_po(owner_id, product_id))

    result = update_purchase_order_draft(
        owner_id=owner_id,
        po_id=po_id,
        supplier_name="Updated Supplier",
    )

    assert result["supplier_name"] == "Updated Supplier"
    assert len(result["lines"]) == 1  # Lines untouched


# ---------------------------------------------------------------------------
# Replace lines
# ---------------------------------------------------------------------------

def test_replace_lines():
    """Providing lines replaces ALL existing lines."""
    owner_id = 6102
    _seed_user(owner_id)
    p1 = _seed_product(owner_id)
    p2 = _seed_product(owner_id)
    po_id = uuid.UUID(_create_po(owner_id, p1))

    result = update_purchase_order_draft(
        owner_id=owner_id,
        po_id=po_id,
        lines=[
            {"product_id": p2, "quantity": Decimal("3.0000"), "unit_cost": Decimal("5.0000")},
        ],
    )

    assert len(result["lines"]) == 1
    assert str(result["lines"][0]["product_id"]) == p2


# ---------------------------------------------------------------------------
# Update on received PO → PurchaseOrderNotDraft
# ---------------------------------------------------------------------------

def test_update_received_po_raises_not_draft():
    """PATCH on received PO → PurchaseOrderNotDraft; state unchanged."""
    owner_id = 6103
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    po_id_str = _create_po(owner_id, product_id)
    po_id = uuid.UUID(po_id_str)

    # Manually receive the PO
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            UPDATE purchase_orders
               SET status = 'received', received_at = NOW(), updated_at = NOW()
             WHERE id = %s AND owner_id = %s
            """,
            (po_id_str, owner_id),
        )

    with pytest.raises(PurchaseOrderNotDraft):
        update_purchase_order_draft(
            owner_id=owner_id,
            po_id=po_id,
            supplier_name="Should Fail",
        )


# ---------------------------------------------------------------------------
# Cross-owner update → PurchaseOrderNotFound
# ---------------------------------------------------------------------------

def test_update_cross_owner_raises_not_found():
    """Updating another owner's PO → PurchaseOrderNotFound (D4)."""
    owner_a = 6104
    owner_b = 6105
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)
    po_id = uuid.UUID(_create_po(owner_a, product_a))

    with pytest.raises(PurchaseOrderNotFound):
        update_purchase_order_draft(
            owner_id=owner_b,
            po_id=po_id,
            supplier_name="Should Fail",
        )


# ---------------------------------------------------------------------------
# Replace with empty lines → ValidationError
# ---------------------------------------------------------------------------

def test_update_empty_lines_raises_validation_error():
    """Providing lines=[] → ValidationError."""
    owner_id = 6106
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    po_id = uuid.UUID(_create_po(owner_id, product_id))

    with pytest.raises(ValidationError):
        update_purchase_order_draft(
            owner_id=owner_id,
            po_id=po_id,
            lines=[],
        )


# ---------------------------------------------------------------------------
# Cross-owner product in replacement lines → ProductNotFound
# ---------------------------------------------------------------------------

def test_update_cross_owner_product_raises_product_not_found():
    """Replacement lines referencing another owner's product → ProductNotFound."""
    owner_a = 6107
    owner_b = 6108
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)
    product_b = _seed_product(owner_b)
    po_id = uuid.UUID(_create_po(owner_a, product_a))

    with pytest.raises(ProductNotFound):
        update_purchase_order_draft(
            owner_id=owner_a,
            po_id=po_id,
            lines=[
                {"product_id": product_b, "quantity": Decimal("1.0000"), "unit_cost": Decimal("1.0000")}
            ],
        )

"""Query-layer tests for purchase_order_lines aggregate.

Tests exercise the public query functions directly against real Postgres.
Behavioral assertions only: return values, DB state, constraint violations.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import psycopg
import psycopg.errors
import pytest

from apps.procurement.queries.purchase_order_lines import (
    delete_lines_for_purchase_order,
    insert_purchase_order_line,
    select_lines_for_purchase_order,
    select_lines_for_update,
)
from apps.procurement.queries.purchase_orders import (
    delete_purchase_order,
    insert_purchase_order,
)

pytestmark = pytest.mark.django_db

_USER_A_ID = 5011
_USER_B_ID = 5012


def _seed_user(conn, uid: int) -> None:
    email = f"pol_qtest_{uid}@test.invalid"
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


def _seed_product(conn, owner_id: int) -> str:
    """Insert a product and return its UUID as string."""
    product_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO products (id, owner_id, sku, name, description, base_unit)
        VALUES (%s, %s, %s, %s, '', 'unit')
        """,
        (product_id, owner_id, f"SKU-{product_id[:8]}", f"Prod {product_id[:8]}"),
    )
    return product_id


def _seed_po(cur, owner_id: int) -> str:
    row = insert_purchase_order(
        cur,
        params={
            "owner_id": owner_id,
            "supplier_name": "Test Supplier",
            "supplier_contact": None,
        },
    )
    return str(row["id"])


def _insert_line(cur, *, owner_id: int, po_id: str, product_id: str,
                 quantity=Decimal("10.0000"), unit_cost=Decimal("5.0000")) -> dict:
    return insert_purchase_order_line(
        cur,
        params={
            "owner_id": owner_id,
            "purchase_order_id": po_id,
            "product_id": product_id,
            "quantity": quantity,
            "unit_cost": unit_cost,
        },
    )


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_insert_line_round_trip(db):
    """Insert a line; verify round-trip; quantity/unit_cost are Decimal (no float)."""
    _seed_user(db, _USER_A_ID)
    product_id = _seed_product(db, _USER_A_ID)

    with db.cursor() as cur:
        po_id = _seed_po(cur, _USER_A_ID)
        row = _insert_line(
            cur,
            owner_id=_USER_A_ID,
            po_id=po_id,
            product_id=product_id,
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("2.5000"),
        )
    db.commit()

    assert row["purchase_order_id"] == uuid.UUID(po_id)
    assert row["product_id"] == uuid.UUID(product_id)
    # Decimal round-trip — must NOT be float
    assert isinstance(row["quantity"], Decimal)
    assert isinstance(row["unit_cost"], Decimal)
    assert row["quantity"] == Decimal("10.0000")
    assert row["unit_cost"] == Decimal("2.5000")
    db.rollback()


# ---------------------------------------------------------------------------
# D4 composite FK: (purchase_order_id, owner_id) → purchase_orders
# ---------------------------------------------------------------------------

def test_line_composite_fk_to_po_owner(db):
    """INSERT line where (purchase_order_id, owner_id) mismatches → ForeignKeyViolation.

    Substrate test for D4: line must be in same owner's PO.
    """
    _seed_user(db, _USER_A_ID)
    _seed_user(db, _USER_B_ID)
    product_b = _seed_product(db, _USER_B_ID)

    with db.cursor() as cur:
        # PO belongs to owner A
        po_id = _seed_po(cur, _USER_A_ID)

    db.commit()

    # Try to insert line with owner_id=B referencing owner A's PO
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as exc_info:
        with db.cursor() as cur:
            insert_purchase_order_line(
                cur,
                params={
                    "owner_id": _USER_B_ID,
                    "purchase_order_id": po_id,
                    "product_id": product_b,
                    "quantity": Decimal("1.0000"),
                    "unit_cost": Decimal("1.0000"),
                },
            )
    db.rollback()
    assert "pol_po_owner_fkey" in str(exc_info.value)


# ---------------------------------------------------------------------------
# D4 composite FK: (product_id, owner_id) → products
# ---------------------------------------------------------------------------

def test_line_composite_fk_to_product_owner(db):
    """INSERT line where (product_id, owner_id) is cross-owner → ForeignKeyViolation.

    Substrate test for D4: line's product must belong to same owner.
    """
    _seed_user(db, _USER_A_ID)
    _seed_user(db, _USER_B_ID)
    product_b = _seed_product(db, _USER_B_ID)

    with db.cursor() as cur:
        po_id = _seed_po(cur, _USER_A_ID)

    db.commit()

    # Try to insert line for owner A using owner B's product
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as exc_info:
        with db.cursor() as cur:
            insert_purchase_order_line(
                cur,
                params={
                    "owner_id": _USER_A_ID,
                    "purchase_order_id": po_id,
                    "product_id": product_b,    # B's product
                    "quantity": Decimal("1.0000"),
                    "unit_cost": Decimal("1.0000"),
                },
            )
    db.rollback()
    assert "pol_product_owner_fkey" in str(exc_info.value)


# ---------------------------------------------------------------------------
# quantity CHECK
# ---------------------------------------------------------------------------

def test_line_quantity_positive_chk(db):
    """quantity = 0 raises CheckViolation."""
    _seed_user(db, _USER_A_ID)
    product_id = _seed_product(db, _USER_A_ID)

    with db.cursor() as cur:
        po_id = _seed_po(cur, _USER_A_ID)
    db.commit()

    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            _insert_line(cur, owner_id=_USER_A_ID, po_id=po_id, product_id=product_id,
                         quantity=Decimal("0"), unit_cost=Decimal("1.0000"))
    db.rollback()


# ---------------------------------------------------------------------------
# unit_cost CHECK
# ---------------------------------------------------------------------------

def test_line_unit_cost_nonneg_chk(db):
    """unit_cost = -1 raises CheckViolation."""
    _seed_user(db, _USER_A_ID)
    product_id = _seed_product(db, _USER_A_ID)

    with db.cursor() as cur:
        po_id = _seed_po(cur, _USER_A_ID)
    db.commit()

    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            _insert_line(cur, owner_id=_USER_A_ID, po_id=po_id, product_id=product_id,
                         quantity=Decimal("1.0000"), unit_cost=Decimal("-1"))
    db.rollback()


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------

def test_delete_lines_cascade_via_po_delete(db):
    """Deleting a PO cascades to delete its lines."""
    _seed_user(db, _USER_A_ID)
    product_id = _seed_product(db, _USER_A_ID)

    with db.cursor() as cur:
        po_id = _seed_po(cur, _USER_A_ID)
        _insert_line(cur, owner_id=_USER_A_ID, po_id=po_id, product_id=product_id)
        delete_purchase_order(
            cur, params={"id": po_id, "owner_id": _USER_A_ID}
        )
    db.commit()

    # Lines must be gone
    with db.cursor() as cur:
        lines = select_lines_for_purchase_order(
            cur, params={"purchase_order_id": po_id, "owner_id": _USER_A_ID}
        )
    assert lines == []
    db.rollback()


# ---------------------------------------------------------------------------
# select_lines_for_purchase_order — owner isolation
# ---------------------------------------------------------------------------

def test_select_lines_returns_only_owner_scope(db):
    """select_lines for owner A's PO with owner B's credentials returns []."""
    _seed_user(db, _USER_A_ID)
    _seed_user(db, _USER_B_ID)
    product_a = _seed_product(db, _USER_A_ID)

    with db.cursor() as cur:
        po_id_a = _seed_po(cur, _USER_A_ID)
        _insert_line(cur, owner_id=_USER_A_ID, po_id=po_id_a, product_id=product_a)
    db.commit()

    # Owner B can't see owner A's lines
    with db.cursor() as cur:
        lines_as_b = select_lines_for_purchase_order(
            cur, params={"purchase_order_id": po_id_a, "owner_id": _USER_B_ID}
        )
    assert lines_as_b == []
    db.rollback()


# ---------------------------------------------------------------------------
# delete_lines_for_purchase_order
# ---------------------------------------------------------------------------

def test_delete_lines_for_purchase_order(db):
    """delete_lines_for_purchase_order removes all lines for the PO."""
    _seed_user(db, _USER_A_ID)
    product_id = _seed_product(db, _USER_A_ID)
    product_id2 = _seed_product(db, _USER_A_ID)

    with db.cursor() as cur:
        po_id = _seed_po(cur, _USER_A_ID)
        _insert_line(cur, owner_id=_USER_A_ID, po_id=po_id, product_id=product_id)
        _insert_line(cur, owner_id=_USER_A_ID, po_id=po_id, product_id=product_id2)
        delete_lines_for_purchase_order(
            cur, params={"purchase_order_id": po_id, "owner_id": _USER_A_ID}
        )
    db.commit()

    with db.cursor() as cur:
        lines = select_lines_for_purchase_order(
            cur, params={"purchase_order_id": po_id, "owner_id": _USER_A_ID}
        )
    assert lines == []
    db.rollback()


# ---------------------------------------------------------------------------
# select_lines_for_update
# ---------------------------------------------------------------------------

def test_select_lines_for_update_returns_rows(db):
    """FOR UPDATE on lines returns the correct rows."""
    _seed_user(db, _USER_A_ID)
    product_id = _seed_product(db, _USER_A_ID)

    with db.cursor() as cur:
        po_id = _seed_po(cur, _USER_A_ID)
        line = _insert_line(cur, owner_id=_USER_A_ID, po_id=po_id, product_id=product_id)
        locked_lines = select_lines_for_update(
            cur, params={"purchase_order_id": po_id, "owner_id": _USER_A_ID}
        )
    db.commit()

    assert len(locked_lines) == 1
    assert str(locked_lines[0]["id"]) == str(line["id"])
    db.rollback()

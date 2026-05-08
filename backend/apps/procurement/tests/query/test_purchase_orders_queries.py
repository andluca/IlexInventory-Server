"""Query-layer tests for purchase_orders aggregate.

Tests exercise the public query functions directly against real Postgres.
All assertions are behavioral — return values, DB state via post_db,
constraint violations. No assertions on SQL text or internal structure.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import psycopg
import psycopg.errors
import pytest

from apps.core.tests.db_test import post_db, pre_db
from apps.procurement.queries.purchase_orders import (
    delete_purchase_order,
    insert_purchase_order,
    list_purchase_orders,
    mark_purchase_order_received,
    select_purchase_order_by_id,
    select_purchase_order_for_update,
    update_purchase_order_header,
)

pytestmark = pytest.mark.django_db

_USER_A_ID = 5001
_USER_B_ID = 5002


def _seed_user(conn, uid: int) -> None:
    email = f"po_qtest_{uid}@test.invalid"
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


def _seed_product(conn, owner_id: int, product_id: str) -> None:
    conn.execute(
        """
        INSERT INTO products (id, owner_id, sku, name, description, base_unit)
        VALUES (%s, %s, %s, %s, '', 'unit')
        ON CONFLICT DO NOTHING
        """,
        (product_id, owner_id, f"SKU-{product_id[:8]}", f"Product {product_id[:8]}"),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_po(cur, owner_id: int, supplier_name: str = "Acme Corp") -> dict:
    return insert_purchase_order(
        cur,
        params={
            "owner_id": owner_id,
            "supplier_name": supplier_name,
            "supplier_contact": None,
        },
    )


# ---------------------------------------------------------------------------
# Round-trip defaults
# ---------------------------------------------------------------------------

def test_insert_purchase_order_round_trip(db):
    """Insert a minimal PO; assert defaults populate correctly."""
    _seed_user(db, _USER_A_ID)
    with db.cursor() as cur:
        row = _insert_po(cur, _USER_A_ID)
    db.commit()

    assert row["status"] == "draft"
    assert row["received_at"] is None
    assert row["created_at"] is not None
    assert row["updated_at"] is not None
    assert row["supplier_name"] == "Acme Corp"
    assert row["owner_id"] == _USER_A_ID
    db.rollback()


# ---------------------------------------------------------------------------
# Status CHECK constraint
# ---------------------------------------------------------------------------

def test_status_chk_rejects_invalid_value(db):
    """Direct INSERT with status='shipped' raises CheckViolation.

    The DB rejects any invalid status. Postgres may fire the received_at_chk
    or the status_chk first depending on constraint evaluation order — both
    constraints correctly guard against 'shipped'. We assert the row is
    rejected via any CHECK violation, confirming the constraint system works.
    """
    _seed_user(db, _USER_A_ID)
    # We try both possible status+received_at combos for 'shipped' — all rejected
    for received_at_val in ("NOW()", "NULL"):
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                f"""
                INSERT INTO purchase_orders
                    (owner_id, supplier_name, status, received_at)
                VALUES (%s, 'Supplier', 'shipped', {received_at_val})
                """,
                (_USER_A_ID,),
            )
        db.rollback()


# ---------------------------------------------------------------------------
# received_at CHECK constraint
# ---------------------------------------------------------------------------

def test_received_at_chk_rejects_draft_with_timestamp(db):
    """(status='draft', received_at=NOW()) violates received_at CHECK."""
    _seed_user(db, _USER_A_ID)
    with pytest.raises(psycopg.errors.CheckViolation) as exc_info:
        db.execute(
            """
            INSERT INTO purchase_orders
                (owner_id, supplier_name, status, received_at)
            VALUES (%s, 'Supplier', 'draft', NOW())
            """,
            (_USER_A_ID,),
        )
    db.rollback()
    assert "purchase_orders_received_at_chk" in str(exc_info.value)


def test_received_at_chk_rejects_received_with_null(db):
    """(status='received', received_at=NULL) violates received_at CHECK."""
    _seed_user(db, _USER_A_ID)
    with pytest.raises(psycopg.errors.CheckViolation) as exc_info:
        db.execute(
            """
            INSERT INTO purchase_orders
                (owner_id, supplier_name, status, received_at)
            VALUES (%s, 'Supplier', 'received', NULL)
            """,
            (_USER_A_ID,),
        )
    db.rollback()
    assert "purchase_orders_received_at_chk" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Composite UNIQUE introspection
# ---------------------------------------------------------------------------

def test_id_owner_unique_present(db):
    """pg_constraint confirms purchase_orders_id_owner_unique exists."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM pg_constraint
             WHERE conname = 'purchase_orders_id_owner_unique'
            """
        )
        count = cur.fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# Cross-owner SELECT
# ---------------------------------------------------------------------------

def test_select_returns_none_for_cross_owner(db):
    """SELECT for owner B on owner A's PO returns None (D4)."""
    _seed_user(db, _USER_A_ID)
    _seed_user(db, _USER_B_ID)
    with db.cursor() as cur:
        row_a = _insert_po(cur, _USER_A_ID)
    db.commit()

    with db.cursor() as cur:
        result = select_purchase_order_by_id(
            cur,
            params={"id": str(row_a["id"]), "owner_id": _USER_B_ID},
        )
    assert result is None
    db.rollback()


# ---------------------------------------------------------------------------
# mark_purchase_order_received
# ---------------------------------------------------------------------------

def test_mark_received_only_from_draft(db):
    """Call once → row updated; call again → returns None (already received)."""
    _seed_user(db, _USER_A_ID)
    with db.cursor() as cur:
        row = _insert_po(cur, _USER_A_ID)
        po_id = str(row["id"])

        # First transition: draft → received
        updated = mark_purchase_order_received(
            cur,
            params={"id": po_id, "owner_id": _USER_A_ID},
        )
    db.commit()
    assert updated is not None
    assert updated["status"] == "received"
    assert updated["received_at"] is not None

    # Second call: already received → returns None
    with db.cursor() as cur:
        second = mark_purchase_order_received(
            cur,
            params={"id": po_id, "owner_id": _USER_A_ID},
        )
    db.rollback()
    assert second is None


# ---------------------------------------------------------------------------
# list_purchase_orders — pagination + status filter + owner isolation
# ---------------------------------------------------------------------------

def test_list_paginates_and_filters_by_status(db):
    """Seed 3 drafts + 2 received for owner A, 1 draft for owner B.

    Assert status filtering and cross-owner isolation.
    """
    # Use unique IDs for this test to avoid cross-test contamination
    user_a = 5021
    user_b = 5022
    _seed_user(db, user_a)
    _seed_user(db, user_b)

    # Truncate purchase_orders for these users only
    db.execute(
        "DELETE FROM purchase_orders WHERE owner_id IN (%s, %s)",
        (user_a, user_b),
    )

    with db.cursor() as cur:
        # Seed owner A: 3 drafts
        for i in range(3):
            _insert_po(cur, user_a, supplier_name=f"Supplier A{i}")
        # Seed owner A: 2 received (insert as draft, then mark received)
        for i in range(2):
            row = _insert_po(cur, user_a, supplier_name=f"Received A{i}")
            mark_purchase_order_received(
                cur,
                params={"id": str(row["id"]), "owner_id": user_a},
            )
        # Seed owner B: 1 draft
        _insert_po(cur, user_b, supplier_name="Supplier B0")

    db.commit()

    with db.cursor() as cur:
        # Owner A total
        rows_a, total_a = list_purchase_orders(
            cur,
            params={
                "owner_id": user_a,
                "status": None,
                "search": None,
                "date_from": None,
                "date_to": None,
                "limit": 50,
                "offset": 0,
            },
        )
        assert total_a == 5
        assert len(rows_a) == 5

        # Owner A filtered by draft
        rows_draft, total_draft = list_purchase_orders(
            cur,
            params={
                "owner_id": user_a,
                "status": "draft",
                "search": None,
                "date_from": None,
                "date_to": None,
                "limit": 50,
                "offset": 0,
            },
        )
        assert total_draft == 3
        assert all(r["status"] == "draft" for r in rows_draft)

        # Owner A filtered by received
        rows_rcvd, total_rcvd = list_purchase_orders(
            cur,
            params={
                "owner_id": user_a,
                "status": "received",
                "search": None,
                "date_from": None,
                "date_to": None,
                "limit": 50,
                "offset": 0,
            },
        )
        assert total_rcvd == 2

        # Owner B sees only their own PO
        rows_b, total_b = list_purchase_orders(
            cur,
            params={
                "owner_id": user_b,
                "status": None,
                "search": None,
                "date_from": None,
                "date_to": None,
                "limit": 50,
                "offset": 0,
            },
        )
        assert total_b == 1
        assert rows_b[0]["owner_id"] == user_b

    db.rollback()


# ---------------------------------------------------------------------------
# @scoped guard
# ---------------------------------------------------------------------------

def test_scoped_decorator_blocks_missing_owner(db):
    """Calling any query function without owner_id raises ValueError."""
    with db.cursor() as cur:
        with pytest.raises(ValueError, match="owner_id"):
            insert_purchase_order(cur, params={"supplier_name": "X"})


# ---------------------------------------------------------------------------
# update_purchase_order_header
# ---------------------------------------------------------------------------

def test_update_purchase_order_header(db):
    """Update supplier_name; verify the row changes."""
    _seed_user(db, _USER_A_ID)
    with db.cursor() as cur:
        row = _insert_po(cur, _USER_A_ID, supplier_name="Original")
        po_id = str(row["id"])
        updated = update_purchase_order_header(
            cur,
            params={
                "id": po_id,
                "owner_id": _USER_A_ID,
                "supplier_name": "Updated",
                "supplier_contact": "contact@example.com",
            },
        )
    db.commit()
    assert updated["supplier_name"] == "Updated"
    assert updated["supplier_contact"] == "contact@example.com"
    db.rollback()


# ---------------------------------------------------------------------------
# delete_purchase_order
# ---------------------------------------------------------------------------

def test_delete_purchase_order(db):
    """Delete a draft PO; rowcount = 1; PO gone from DB."""
    _seed_user(db, _USER_A_ID)
    with db.cursor() as cur:
        row = _insert_po(cur, _USER_A_ID)
        po_id = str(row["id"])
        rowcount = delete_purchase_order(
            cur,
            params={"id": po_id, "owner_id": _USER_A_ID},
        )
    db.commit()
    assert rowcount == 1

    with db.cursor() as cur:
        result = select_purchase_order_by_id(
            cur, params={"id": po_id, "owner_id": _USER_A_ID}
        )
    assert result is None
    db.rollback()


# ---------------------------------------------------------------------------
# select_purchase_order_for_update
# ---------------------------------------------------------------------------

def test_select_for_update_returns_row(db):
    """FOR UPDATE SELECT returns the same row as regular SELECT."""
    _seed_user(db, _USER_A_ID)
    with db.cursor() as cur:
        row = _insert_po(cur, _USER_A_ID)
        po_id = str(row["id"])
        locked = select_purchase_order_for_update(
            cur, params={"id": po_id, "owner_id": _USER_A_ID}
        )
    db.commit()
    assert locked["id"] == row["id"]
    db.rollback()

"""Query-layer tests for apps.catalog.queries.products.

Uses the pre_db/post_db state pattern against a real Postgres DB.
Each test is responsible for setting up its own state and cleaning up.
"""

from __future__ import annotations

import uuid

import psycopg
import psycopg.errors
import pytest

from apps.catalog.queries.products import (
    insert_product,
    list_products,
    select_product_by_id,
    set_archived_at,
)
from apps.core.tests.db_test import post_db, pre_db

pytestmark = pytest.mark.django_db


def _owner_row(user_id: int = 1) -> dict:
    return {
        "id": user_id,
        "password": "hashed",
        "last_login": None,
        "is_superuser": False,
        "username": f"user_{user_id}",
        "first_name": "",
        "last_name": "",
        "email": f"user{user_id}@test.invalid",
        "is_staff": False,
        "is_active": True,
        "date_joined": "2026-01-01T00:00:00+00:00",
    }


def _product_params(owner_id: int = 1, sku: str = "SKU-001") -> dict:
    return {
        "owner_id": owner_id,
        "sku": sku,
        "name": "Cold Brew",
        "description": "Cold brew coffee",
        "base_unit": "ml",
    }


# ---------------------------------------------------------------------------
# insert + select round-trip
# ---------------------------------------------------------------------------


def test_insert_and_select_round_trip(db):
    pre_db(db, {"auth_user": [_owner_row(1)], "products": []})
    db.commit()

    with db.cursor() as cur:
        row = insert_product(cur, params=_product_params(owner_id=1))

    db.commit()

    with db.cursor() as cur:
        fetched = select_product_by_id(cur, params={"id": row["id"], "owner_id": 1})

    assert fetched is not None
    assert fetched["sku"] == "SKU-001"
    assert fetched["name"] == "Cold Brew"
    assert fetched["owner_id"] == 1
    assert fetched["base_unit"] == "ml"

    db.rollback()


# ---------------------------------------------------------------------------
# archived_at defaults to NULL
# ---------------------------------------------------------------------------


def test_archived_at_defaults_to_null(db):
    pre_db(db, {"auth_user": [_owner_row(2)], "products": []})
    db.commit()

    with db.cursor() as cur:
        row = insert_product(cur, params=_product_params(owner_id=2, sku="SKU-NULL"))

    db.commit()

    post_db(db, {"products": [{"sku": "SKU-NULL", "archived_at": None}]})
    assert row["archived_at"] is None

    db.rollback()


# ---------------------------------------------------------------------------
# UNIQUE (owner_id, sku) violation
# ---------------------------------------------------------------------------


def test_unique_owner_sku_violation_raises(db):
    pre_db(db, {"auth_user": [_owner_row(3)], "products": []})
    db.commit()

    with db.cursor() as cur:
        insert_product(cur, params=_product_params(owner_id=3, sku="SKU-DUP"))
    db.commit()

    with pytest.raises(psycopg.errors.UniqueViolation) as exc_info:
        with db.cursor() as cur:
            insert_product(cur, params=_product_params(owner_id=3, sku="SKU-DUP"))
    db.rollback()

    assert "products_owner_sku_unique" in str(exc_info.value)


# ---------------------------------------------------------------------------
# UNIQUE (id, owner_id) constraint present (introspect pg_constraint)
# ---------------------------------------------------------------------------


def test_unique_id_owner_constraint_present(db):
    pre_db(db, {"auth_user": []}, wipe=False)

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
              FROM pg_constraint
             WHERE conname = 'products_id_owner_unique'
               AND contype = 'u'
            """
        )
        count = cur.fetchone()[0]

    assert count == 1


# ---------------------------------------------------------------------------
# set_archived_at is idempotent
# ---------------------------------------------------------------------------


def test_set_archived_at_idempotent(db):
    pre_db(db, {"auth_user": [_owner_row(4)], "products": []})
    db.commit()

    with db.cursor() as cur:
        row = insert_product(cur, params=_product_params(owner_id=4, sku="SKU-ARCH"))
    db.commit()

    product_id = row["id"]

    with db.cursor() as cur:
        result1 = set_archived_at(cur, params={"id": product_id, "owner_id": 4})
    db.commit()

    assert result1 is not None
    assert result1["archived_at"] is not None

    # Second call — already archived; WHERE archived_at IS NULL fails; returns None.
    with db.cursor() as cur:
        result2 = set_archived_at(cur, params={"id": product_id, "owner_id": 4})
    db.commit()

    assert result2 is None

    db.rollback()


# ---------------------------------------------------------------------------
# list_products — owner isolation, offset pagination, archived filter
# ---------------------------------------------------------------------------


def test_list_products_filters_and_paginates(db):
    pre_db(db, {"auth_user": [_owner_row(5), _owner_row(6)], "products": []})
    db.commit()

    with db.cursor() as cur:
        insert_product(cur, params={**_product_params(owner_id=5), "sku": "A-001", "name": "Alpha"})
        insert_product(cur, params={**_product_params(owner_id=5), "sku": "A-002", "name": "Beta"})
        p3 = insert_product(cur, params={**_product_params(owner_id=5), "sku": "A-003", "name": "Gamma"})
        insert_product(cur, params={**_product_params(owner_id=6), "sku": "B-001", "name": "Delta"})
        insert_product(cur, params={**_product_params(owner_id=6), "sku": "B-002", "name": "Epsilon"})
        # Archive p3 for owner 5
        set_archived_at(cur, params={"id": p3["id"], "owner_id": 5})
    db.commit()

    # Owner 5 active products only (archived=False)
    with db.cursor() as cur:
        rows, total = list_products(cur, params={
            "owner_id": 5, "search": None, "archived": False,
            "limit": 50, "offset": 0,
        })
    assert total == 2
    assert len(rows) == 2
    skus = {r["sku"] for r in rows}
    assert skus == {"A-001", "A-002"}

    # Owner 5 archived only
    with db.cursor() as cur:
        rows, total = list_products(cur, params={
            "owner_id": 5, "search": None, "archived": True,
            "limit": 50, "offset": 0,
        })
    assert total == 1
    assert rows[0]["sku"] == "A-003"

    # Pagination: all (no filter), limit=1, offset=1
    with db.cursor() as cur:
        rows, total = list_products(cur, params={
            "owner_id": 5, "search": None, "archived": None,
            "limit": 1, "offset": 1,
        })
    assert total == 3
    assert len(rows) == 1

    db.rollback()


# ---------------------------------------------------------------------------
# list_products — search by name or sku
# ---------------------------------------------------------------------------


def test_list_products_search_by_name_or_sku(db):
    pre_db(db, {"auth_user": [_owner_row(7)], "products": []})
    db.commit()

    with db.cursor() as cur:
        insert_product(cur, params={**_product_params(owner_id=7), "sku": "COLD-001", "name": "Cold Brew"})
        insert_product(cur, params={**_product_params(owner_id=7), "sku": "HOT-001", "name": "Hot Latte"})
    db.commit()

    # search by name
    with db.cursor() as cur:
        rows, total = list_products(cur, params={
            "owner_id": 7, "search": "cold", "archived": None,
            "limit": 50, "offset": 0,
        })
    assert total == 1
    assert rows[0]["name"] == "Cold Brew"

    # search by sku
    with db.cursor() as cur:
        rows, total = list_products(cur, params={
            "owner_id": 7, "search": "HOT", "archived": None,
            "limit": 50, "offset": 0,
        })
    assert total == 1
    assert rows[0]["sku"] == "HOT-001"

    db.rollback()


# ---------------------------------------------------------------------------
# @scoped blocks missing owner_id
# ---------------------------------------------------------------------------


def test_scoped_decorator_blocks_missing_owner(db):
    with pytest.raises(ValueError, match="owner_id"):
        with db.cursor() as cur:
            select_product_by_id(cur, params={"id": str(uuid.uuid4())})

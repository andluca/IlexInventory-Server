"""API tests — POST /products/import (CSV, multipart, idempotency)."""

from __future__ import annotations

import io
import itertools
import os
import types
import uuid

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_IMPORT_URL = "/api/v1/products/import"
_uid_counter = itertools.count(start=4000)


def _db_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _make_auth_user(uid: int) -> None:
    email = f"imp_{uid}@test.invalid"
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO auth_user
                (id, username, email, password,
                 is_superuser, is_staff, is_active,
                 first_name, last_name, date_joined)
            VALUES (%s, %s, %s, 'unusable!', false, false, true, '', '', NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            (uid, email, email),
        )


def _fake_user() -> types.SimpleNamespace:
    uid = next(_uid_counter)
    _make_auth_user(uid)
    return types.SimpleNamespace(id=uid, is_authenticated=True, is_active=True)


def _authed_client() -> APIClient:
    user = _fake_user()
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _csv_file(content: str) -> io.BytesIO:
    f = io.BytesIO(content.encode())
    f.name = "products.csv"
    return f


def _idempotency_key() -> str:
    return str(uuid.uuid4())


def test_import_all_valid_rows():
    client = _authed_client()
    key = _idempotency_key()

    valid_csv = "name,sku,description,base_unit\nCold Brew,IMP-001,,ml\nHot Latte,IMP-002,,g\n"
    resp = client.post(
        _IMPORT_URL,
        data={"file": _csv_file(valid_csv)},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY=key,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 2
    assert data["failed"] == []


def test_import_mixed_valid_invalid():
    client = _authed_client()
    key = _idempotency_key()

    mixed_csv = "name,sku,description,base_unit\nCold Brew,MIX-001,,ml\nBad,MIX-002,,GALLON\n"
    resp = client.post(
        _IMPORT_URL,
        data={"file": _csv_file(mixed_csv)},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY=key,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 1
    assert len(data["failed"]) == 1
    assert data["failed"][0]["row_index"] == 1


def test_import_missing_idempotency_key_returns_400():
    client = _authed_client()

    valid_csv = "name,sku,description,base_unit\nTest,TST-001,,ml\n"
    resp = client.post(
        _IMPORT_URL,
        data={"file": _csv_file(valid_csv)},
        format="multipart",
    )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "ValidationError"


def test_import_same_key_second_call_is_cached():
    """Second call with same Idempotency-Key returns cached response without re-executing."""
    client = _authed_client()
    key = _idempotency_key()

    valid_csv = "name,sku,description,base_unit\nCold Brew,CACHE-001,,ml\nHot Latte,CACHE-002,,g\n"

    # First call: import 2 rows.
    resp1 = client.post(
        _IMPORT_URL,
        data={"file": _csv_file(valid_csv)},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert resp1.status_code == 200
    assert resp1.json()["imported"] == 2

    # Second call with same key: should return cached response.
    resp2 = client.post(
        _IMPORT_URL,
        data={"file": _csv_file(valid_csv)},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert resp2.status_code == 200
    assert resp2.json()["imported"] == 2

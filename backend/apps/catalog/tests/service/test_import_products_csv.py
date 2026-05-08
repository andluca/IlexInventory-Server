"""Service tests — import_products_csv."""

from __future__ import annotations

import pytest

from apps.catalog.services import import_products_csv
from apps.core.tests.db_test import post_db, pre_db

pytestmark = pytest.mark.django_db


def _owner_row(user_id: int) -> dict:
    return {
        "id": user_id,
        "password": "hashed",
        "last_login": None,
        "is_superuser": False,
        "username": f"imp_user_{user_id}",
        "first_name": "",
        "last_name": "",
        "email": f"impuser{user_id}@test.invalid",
        "is_staff": False,
        "is_active": True,
        "date_joined": "2026-01-01T00:00:00+00:00",
    }


_VALID_CSV = b"name,sku,description,base_unit\nCold Brew,SKU-1,desc,ml\nHot Latte,SKU-2,,g\n"
_MIXED_CSV = b"name,sku,description,base_unit\nCold Brew,SKU-1,,ml\nBad Product,SKU-2,,GALLON\n"
_DUPE_CSV = b"name,sku,description,base_unit\nFirst,DUPE,,g\nSecond,DUPE,,ml\n"
_EMPTY_CSV = b""
_HEADER_ONLY_CSV = b"name,sku,description,base_unit\n"


def test_all_rows_valid_imports_all(db):
    """All valid rows → imported=N, failed=[]."""
    pre_db(db, {"auth_user": [_owner_row(50)], "products": []})
    db.commit()

    report = import_products_csv(owner_id=50, csv_bytes=_VALID_CSV)

    assert report["imported"] == 2
    assert report["failed"] == []

    post_db(db, {"products": [
        {"sku": "SKU-1", "owner_id": 50},
        {"sku": "SKU-2", "owner_id": 50},
    ]})
    db.rollback()


def test_mixed_valid_invalid_partial_success(db):
    """2 valid + 1 bad base_unit → imported=1, failed=[{row_index: 1, ...}]."""
    pre_db(db, {"auth_user": [_owner_row(51)], "products": []})
    db.commit()

    report = import_products_csv(owner_id=51, csv_bytes=_MIXED_CSV)

    assert report["imported"] == 1
    assert len(report["failed"]) == 1
    assert report["failed"][0]["row_index"] == 1
    assert report["failed"][0]["error"] == "ValidationError"
    assert "base_unit" in (report["failed"][0].get("fields") or {}) or \
           "base_unit" in (report["failed"][0].get("detail") or "")

    # Valid row persisted; bad row absent.
    post_db(db, {"products": [{"sku": "SKU-1", "owner_id": 51}]})
    db.rollback()


def test_duplicate_sku_within_import_second_fails(db):
    """Duplicate SKU within same import: second row reported as failed with DuplicateSKU."""
    pre_db(db, {"auth_user": [_owner_row(52)], "products": []})
    db.commit()

    report = import_products_csv(owner_id=52, csv_bytes=_DUPE_CSV)

    assert report["imported"] == 1
    assert len(report["failed"]) == 1
    assert report["failed"][0]["row_index"] == 1
    assert report["failed"][0]["error"] == "DuplicateSKU"

    post_db(db, {"products": [{"sku": "DUPE", "owner_id": 52}]})
    db.rollback()


def test_empty_csv_returns_zero(db):
    """Empty CSV → imported=0, failed=[]."""
    pre_db(db, {"auth_user": [_owner_row(53)], "products": []})
    db.commit()

    report = import_products_csv(owner_id=53, csv_bytes=_EMPTY_CSV)

    assert report["imported"] == 0
    assert report["failed"] == []
    db.rollback()


def test_header_only_csv_returns_zero(db):
    """Header-only CSV → imported=0, failed=[]."""
    pre_db(db, {"auth_user": [_owner_row(54)], "products": []})
    db.commit()

    report = import_products_csv(owner_id=54, csv_bytes=_HEADER_ONLY_CSV)

    assert report["imported"] == 0
    assert report["failed"] == []
    db.rollback()


def test_csv_with_utf8_bom_imports_first_row(db):
    """A leading UTF-8 BOM (\\xef\\xbb\\xbf) must not poison the first column name."""
    pre_db(db, {"auth_user": [_owner_row(55)], "products": []})
    db.commit()

    csv_with_bom = b"\xef\xbb\xbfname,sku,description,base_unit\nBOM Brew,SKU-BOM,,unit\n"
    report = import_products_csv(owner_id=55, csv_bytes=csv_with_bom)

    assert report["imported"] == 1
    assert report["failed"] == []
    post_db(db, {"products": [{"sku": "SKU-BOM", "name": "BOM Brew", "owner_id": 55}]})
    db.rollback()


def test_csv_with_crlf_line_endings_imports(db):
    """Windows-style CRLF line endings parse the same as LF."""
    pre_db(db, {"auth_user": [_owner_row(56)], "products": []})
    db.commit()

    csv_crlf = b"name,sku,description,base_unit\r\nCRLF Brew,SKU-CRLF,,ml\r\n"
    report = import_products_csv(owner_id=56, csv_bytes=csv_crlf)

    assert report["imported"] == 1
    assert report["failed"] == []
    post_db(db, {"products": [{"sku": "SKU-CRLF", "name": "CRLF Brew", "owner_id": 56}]})
    db.rollback()


def test_csv_blank_sku_rejects_row(db):
    """A row with empty `sku` lands in `failed` with a sku field error."""
    pre_db(db, {"auth_user": [_owner_row(57)], "products": []})
    db.commit()

    csv_blank = b"name,sku,description,base_unit\nNo SKU,,,g\n"
    report = import_products_csv(owner_id=57, csv_bytes=csv_blank)

    assert report["imported"] == 0
    assert len(report["failed"]) == 1
    assert report["failed"][0]["row_index"] == 0
    assert report["failed"][0]["error"] == "ValidationError"
    assert "sku" in (report["failed"][0].get("fields") or {})

    post_db(db, {"products": []})
    db.rollback()

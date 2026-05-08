"""Unit tests for procurement serializers — pure logic, no DB.

Tests exercise the public serializer classes' validation behavior.
"""

from __future__ import annotations

from decimal import Decimal


from apps.procurement.serializers import (
    LineCreateRequest,
    PurchaseOrderCreateRequest,
    PurchaseOrderReceiveRequest,
    PurchaseOrderResponse,
    PurchaseOrderUpdateRequest,
    ReceiveLineRequest,
)


# ---------------------------------------------------------------------------
# LineCreateRequest
# ---------------------------------------------------------------------------

def test_line_create_rejects_quantity_zero():
    """quantity = 0 fails validation."""
    s = LineCreateRequest(data={
        "product_id": "00000000-0000-0000-0000-000000000001",
        "quantity": "0",
        "unit_cost": "5.00",
    })
    assert not s.is_valid()
    assert "quantity" in s.errors


def test_line_create_rejects_quantity_negative():
    """quantity = -1 fails validation."""
    s = LineCreateRequest(data={
        "product_id": "00000000-0000-0000-0000-000000000001",
        "quantity": "-1",
        "unit_cost": "5.00",
    })
    assert not s.is_valid()
    assert "quantity" in s.errors


def test_line_create_rejects_unit_cost_negative():
    """unit_cost = -0.01 fails validation."""
    s = LineCreateRequest(data={
        "product_id": "00000000-0000-0000-0000-000000000001",
        "quantity": "1.0000",
        "unit_cost": "-0.01",
    })
    assert not s.is_valid()
    assert "unit_cost" in s.errors


def test_line_create_accepts_zero_unit_cost():
    """unit_cost = 0 is valid (free sample etc.)."""
    s = LineCreateRequest(data={
        "product_id": "00000000-0000-0000-0000-000000000001",
        "quantity": "1.0000",
        "unit_cost": "0",
    })
    assert s.is_valid(), s.errors


# ---------------------------------------------------------------------------
# PurchaseOrderCreateRequest
# ---------------------------------------------------------------------------

def test_po_create_rejects_empty_lines():
    """Empty lines list → invalid."""
    s = PurchaseOrderCreateRequest(data={
        "supplier_name": "Acme",
        "supplier_contact": None,
        "lines": [],
    })
    assert not s.is_valid()
    assert "lines" in s.errors


def test_po_create_rejects_missing_lines():
    """Absent lines key → invalid."""
    s = PurchaseOrderCreateRequest(data={
        "supplier_name": "Acme",
    })
    assert not s.is_valid()
    assert "lines" in s.errors


def test_po_create_happy_path():
    """Valid PO create request passes."""
    s = PurchaseOrderCreateRequest(data={
        "supplier_name": "Acme Corp",
        "supplier_contact": "acme@example.com",
        "lines": [
            {
                "product_id": "00000000-0000-0000-0000-000000000001",
                "quantity": "10.0000",
                "unit_cost": "2.5000",
            }
        ],
    })
    assert s.is_valid(), s.errors


# ---------------------------------------------------------------------------
# PurchaseOrderUpdateRequest
# ---------------------------------------------------------------------------

def test_po_update_rejects_unknown_key_status():
    """'status' is not an allowed field in PATCH body."""
    s = PurchaseOrderUpdateRequest(data={"status": "received"})
    assert not s.is_valid()
    assert "status" in s.errors


def test_po_update_rejects_unknown_key_received_at():
    """'received_at' is not an allowed field in PATCH body."""
    s = PurchaseOrderUpdateRequest(data={"received_at": "2026-01-01T00:00:00Z"})
    assert not s.is_valid()
    assert "received_at" in s.errors


def test_po_update_rejects_empty_lines():
    """lines=[] is invalid when provided."""
    s = PurchaseOrderUpdateRequest(data={"lines": []})
    assert not s.is_valid()
    assert "lines" in s.errors


def test_po_update_accepts_partial():
    """Only supplier_name update is valid."""
    s = PurchaseOrderUpdateRequest(data={"supplier_name": "New Name"})
    assert s.is_valid(), s.errors


def test_po_update_accepts_lines_replace():
    """lines provided with valid content is accepted."""
    s = PurchaseOrderUpdateRequest(data={
        "lines": [
            {
                "product_id": "00000000-0000-0000-0000-000000000001",
                "quantity": "5.0000",
                "unit_cost": "1.0000",
            }
        ]
    })
    assert s.is_valid(), s.errors


# ---------------------------------------------------------------------------
# ReceiveLineRequest
# ---------------------------------------------------------------------------

def test_receive_line_rejects_blank_batch_code():
    """Empty batch_code is invalid."""
    s = ReceiveLineRequest(data={
        "line_id": "00000000-0000-0000-0000-000000000001",
        "batch_code": "",
        "expiration_date": None,
    })
    assert not s.is_valid()
    assert "batch_code" in s.errors


def test_receive_line_accepts_null_expiration():
    """expiration_date=null is valid."""
    s = ReceiveLineRequest(data={
        "line_id": "00000000-0000-0000-0000-000000000001",
        "batch_code": "BATCH-001",
        "expiration_date": None,
    })
    assert s.is_valid(), s.errors


def test_receive_line_rejects_invalid_date():
    """Malformed expiration_date string is invalid."""
    s = ReceiveLineRequest(data={
        "line_id": "00000000-0000-0000-0000-000000000001",
        "batch_code": "BATCH-001",
        "expiration_date": "not-a-date",
    })
    assert not s.is_valid()
    assert "expiration_date" in s.errors


# ---------------------------------------------------------------------------
# PurchaseOrderReceiveRequest
# ---------------------------------------------------------------------------

def test_po_receive_rejects_empty_lines():
    """lines=[] in receive body → invalid."""
    s = PurchaseOrderReceiveRequest(data={"lines": []})
    assert not s.is_valid()
    assert "lines" in s.errors


# ---------------------------------------------------------------------------
# PurchaseOrderResponse — money fields serialize as strings
# ---------------------------------------------------------------------------

def test_po_response_serializes_decimals_as_strings():
    """quantity and unit_cost serialize as strings (SPEC §2.5)."""
    data = {
        "id": "00000000-0000-0000-0000-000000000001",
        "owner_id": 1,
        "supplier_name": "Acme",
        "supplier_contact": None,
        "status": "draft",
        "received_at": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "lines": [
            {
                "id": "00000000-0000-0000-0000-000000000002",
                "purchase_order_id": "00000000-0000-0000-0000-000000000001",
                "product_id": "00000000-0000-0000-0000-000000000003",
                "quantity": Decimal("10.0000"),
                "unit_cost": Decimal("2.5000"),
                "created_at": "2026-01-01T00:00:00Z",
            }
        ],
    }
    s = PurchaseOrderResponse(data)
    result = s.data
    line = result["lines"][0]
    assert isinstance(line["quantity"], str), f"Expected str, got {type(line['quantity'])}"
    assert isinstance(line["unit_cost"], str), f"Expected str, got {type(line['unit_cost'])}"
    assert line["quantity"] == "10.0000"
    assert line["unit_cost"] == "2.5000"

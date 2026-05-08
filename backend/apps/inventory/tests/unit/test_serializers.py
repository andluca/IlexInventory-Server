"""Unit tests for apps.inventory.serializers — allowlist behavior and sign rules."""

from __future__ import annotations



from apps.inventory.serializers import (
    BatchCreateRequest,
    BatchPatchMetadataRequest,
    MovementCreateRequest,
    RecallRequest,
)


# ---------------------------------------------------------------------------
# BatchPatchMetadataRequest — strict allowlist
# ---------------------------------------------------------------------------

def test_patch_request_rejects_disallowed_field():
    """BatchPatchMetadataRequest rejects unknown fields like unit_cost."""
    ser = BatchPatchMetadataRequest(data={"unit_cost": "99.0"})
    assert not ser.is_valid()
    # Validation error should mention 'unit_cost'
    errors = ser.errors
    assert "unit_cost" in str(errors) or "non_field_errors" in errors


def test_patch_request_accepts_allowed_fields():
    """BatchPatchMetadataRequest accepts batch_code and expiration_date."""
    ser = BatchPatchMetadataRequest(data={"batch_code": "NEW-001", "expiration_date": None})
    assert ser.is_valid(), ser.errors


def test_patch_request_accepts_clear_expiration():
    """BatchPatchMetadataRequest accepts clear_expiration=True."""
    ser = BatchPatchMetadataRequest(data={"clear_expiration": True})
    assert ser.is_valid(), ser.errors


# ---------------------------------------------------------------------------
# MovementCreateRequest — kind allowlist
# ---------------------------------------------------------------------------

def test_movement_request_rejects_sale_kind():
    """MovementCreateRequest rejects kind='sale'."""
    ser = MovementCreateRequest(data={"kind": "sale", "signed_quantity": "-1.0000"})
    assert not ser.is_valid()


def test_movement_request_rejects_recall_block_kind():
    """MovementCreateRequest rejects kind='recall_block'."""
    ser = MovementCreateRequest(data={"kind": "recall_block", "signed_quantity": "0"})
    assert not ser.is_valid()


def test_movement_request_accepts_adjustment():
    ser = MovementCreateRequest(data={"kind": "adjustment", "signed_quantity": "5.0", "notes": "test"})
    assert ser.is_valid(), ser.errors


def test_movement_request_accepts_write_off():
    ser = MovementCreateRequest(data={"kind": "write_off", "signed_quantity": "-3.0"})
    assert ser.is_valid(), ser.errors


# ---------------------------------------------------------------------------
# BatchCreateRequest — quantity min_value
# ---------------------------------------------------------------------------

def test_batch_create_rejects_zero_initial_quantity():
    """BatchCreateRequest rejects initial_quantity=0 (min_value=0.0001)."""
    ser = BatchCreateRequest(data={
        "product_id": "00000000-0000-0000-0000-000000000001",
        "batch_code": "TEST",
        "unit_cost": "1.0",
        "initial_quantity": "0",
    })
    assert not ser.is_valid()
    assert "initial_quantity" in ser.errors


# ---------------------------------------------------------------------------
# RecallRequest
# ---------------------------------------------------------------------------

def test_recall_request_requires_reason():
    ser = RecallRequest(data={})
    assert not ser.is_valid()
    assert "reason" in ser.errors

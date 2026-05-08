"""Request/response serializers for apps.inventory.

Naming convention: *Request for input validation, *Response for output shaping.
Money/qty: DecimalField(coerce_to_string=True) — wire format is string per SPEC §2.5.
PATCH metadata uses strict allowlist; unknown fields raise ValidationError at the
serializer layer (test_patch_with_disallowed_field_returns_400).
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers


# ---------------------------------------------------------------------------
# Batch response
# ---------------------------------------------------------------------------

class BatchResponse(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    owner_id = serializers.IntegerField(read_only=True)
    product_id = serializers.UUIDField(read_only=True)
    purchase_order_line_id = serializers.UUIDField(allow_null=True, read_only=True)
    batch_code = serializers.CharField(read_only=True)
    expiration_date = serializers.DateField(allow_null=True, read_only=True)
    unit_cost = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    on_hand = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    is_recalled = serializers.BooleanField(read_only=True)
    recall_reason = serializers.CharField(allow_null=True, read_only=True)
    recalled_at = serializers.DateTimeField(allow_null=True, read_only=True)
    archived_at = serializers.DateTimeField(allow_null=True, read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class BatchListResponse(serializers.Serializer):
    items = BatchResponse(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    limit = serializers.IntegerField(read_only=True)
    offset = serializers.IntegerField(read_only=True)


# ---------------------------------------------------------------------------
# Batch create request (POST /batches — manual entry)
# ---------------------------------------------------------------------------

class BatchCreateRequest(serializers.Serializer):
    product_id = serializers.UUIDField()
    batch_code = serializers.CharField(min_length=1, max_length=255)
    expiration_date = serializers.DateField(
        required=False,
        allow_null=True,
        input_formats=["%Y-%m-%d", "iso-8601"],
    )
    unit_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0"),
        coerce_to_string=False,
    )
    initial_quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        coerce_to_string=False,
    )


# ---------------------------------------------------------------------------
# Batch PATCH metadata request (PATCH /batches/{id})
# Strict allowlist: only batch_code and expiration_date are permitted.
# ---------------------------------------------------------------------------

class BatchPatchMetadataRequest(serializers.Serializer):
    batch_code = serializers.CharField(min_length=1, max_length=255, required=False)
    expiration_date = serializers.DateField(
        required=False,
        allow_null=True,
        input_formats=["%Y-%m-%d", "iso-8601"],
    )
    clear_expiration = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict) -> dict:
        allowed = {"batch_code", "expiration_date", "clear_expiration"}
        unknown = set(self.initial_data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["This field is not allowed in PATCH."] for k in unknown}
            )
        return attrs


# ---------------------------------------------------------------------------
# Movement create request (POST /batches/{id}/movements)
# kind must be adjustment or write_off (sale + recall kinds are rejected here)
# ---------------------------------------------------------------------------

class MovementCreateRequest(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["adjustment", "write_off"])
    signed_quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        coerce_to_string=False,
    )
    notes = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
    )


# ---------------------------------------------------------------------------
# Recall request (POST /batches/{id}/recall)
# ---------------------------------------------------------------------------

class RecallRequest(serializers.Serializer):
    reason = serializers.CharField(min_length=1)


# ---------------------------------------------------------------------------
# Movement response
# ---------------------------------------------------------------------------

class MovementResponse(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    owner_id = serializers.IntegerField(read_only=True)
    batch_id = serializers.UUIDField(read_only=True)
    kind = serializers.CharField(read_only=True)
    signed_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    notes = serializers.CharField(allow_null=True, read_only=True)
    reference_type = serializers.CharField(allow_null=True, read_only=True)
    reference_id = serializers.UUIDField(allow_null=True, read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class MovementListResponse(serializers.Serializer):
    items = MovementResponse(many=True, read_only=True)
    next_cursor = serializers.CharField(allow_null=True, read_only=True)

"""Request/response serializers for apps.procurement.

Naming convention: *Request for input validation, *Response for output shaping.
DRF strict mode: unknown body keys are rejected via validate() in update/receive.
Money/qty: DecimalField(coerce_to_string=True) — wire format is string per SPEC §2.5.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers


# ---------------------------------------------------------------------------
# Nested: Line request (create / replace)
# ---------------------------------------------------------------------------

class LineCreateRequest(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        coerce_to_string=False,
    )
    unit_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0"),
        coerce_to_string=False,
    )


# ---------------------------------------------------------------------------
# PO create request
# ---------------------------------------------------------------------------

class PurchaseOrderCreateRequest(serializers.Serializer):
    supplier_name = serializers.CharField(max_length=500)
    supplier_contact = serializers.CharField(
        max_length=500,
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
    )
    lines = serializers.ListField(
        child=LineCreateRequest(),
        min_length=1,
    )


# ---------------------------------------------------------------------------
# PO update request (PATCH — replace-style for lines if provided)
# ---------------------------------------------------------------------------

class PurchaseOrderUpdateRequest(serializers.Serializer):
    supplier_name = serializers.CharField(max_length=500, required=False)
    supplier_contact = serializers.CharField(
        max_length=500,
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    lines = serializers.ListField(
        child=LineCreateRequest(),
        min_length=1,
        required=False,
    )

    def validate(self, attrs: dict) -> dict:
        allowed = {"supplier_name", "supplier_contact", "lines"}
        unknown = set(self.initial_data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["This field is not allowed in PATCH."] for k in unknown}
            )
        return attrs


# ---------------------------------------------------------------------------
# Receive request
# ---------------------------------------------------------------------------

class ReceiveLineRequest(serializers.Serializer):
    line_id = serializers.UUIDField()
    batch_code = serializers.CharField(min_length=1)
    expiration_date = serializers.DateField(
        required=False,
        allow_null=True,
        input_formats=["%Y-%m-%d", "iso-8601"],
    )


class PurchaseOrderReceiveRequest(serializers.Serializer):
    lines = serializers.ListField(
        child=ReceiveLineRequest(),
        min_length=1,
    )


# ---------------------------------------------------------------------------
# Response serializers
# ---------------------------------------------------------------------------

class PurchaseOrderLineResponse(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    purchase_order_id = serializers.UUIDField(read_only=True)
    product_id = serializers.UUIDField(read_only=True)
    quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        coerce_to_string=True,
        read_only=True,
    )
    unit_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        coerce_to_string=True,
        read_only=True,
    )
    created_at = serializers.DateTimeField(read_only=True)


class PurchaseOrderResponse(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    supplier_name = serializers.CharField(read_only=True)
    supplier_contact = serializers.CharField(allow_null=True, read_only=True)
    status = serializers.CharField(read_only=True)
    received_at = serializers.DateTimeField(allow_null=True, read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    lines = PurchaseOrderLineResponse(many=True, read_only=True)


class PurchaseOrderListResponse(serializers.Serializer):
    items = PurchaseOrderResponse(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    limit = serializers.IntegerField(read_only=True)
    offset = serializers.IntegerField(read_only=True)

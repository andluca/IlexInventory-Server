"""Request/response serializers for apps.sales.

Naming convention: *Request for input validation, *Response for output shaping.
Money/qty: DecimalField(coerce_to_string=True) — wire format is string per SPEC §2.5.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers


# ---------------------------------------------------------------------------
# Line serializers
# ---------------------------------------------------------------------------

class SalesOrderLineResponse(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    sales_order_id = serializers.UUIDField(read_only=True)
    product_id = serializers.UUIDField(read_only=True)
    quantity = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    sell_price = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    created_at = serializers.DateTimeField(read_only=True)


class SalesOrderLineRequest(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        coerce_to_string=False,
    )
    sell_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0"),
        coerce_to_string=False,
    )


# ---------------------------------------------------------------------------
# Allocation serializers
# ---------------------------------------------------------------------------

class AllocationResponse(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    sales_order_line_id = serializers.UUIDField(read_only=True)
    batch_id = serializers.UUIDField(read_only=True)
    allocated_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    unit_cost = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    created_at = serializers.DateTimeField(read_only=True)


class ProposedAllocationResponse(serializers.Serializer):
    line_id = serializers.UUIDField(read_only=True)
    batch_id = serializers.UUIDField(read_only=True)
    batch_code = serializers.CharField(read_only=True)
    quantity = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    unit_cost = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    expiration_date = serializers.DateField(allow_null=True, read_only=True)


class ExplicitAllocationRequest(serializers.Serializer):
    line_id = serializers.UUIDField()
    batch_id = serializers.UUIDField()
    quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        coerce_to_string=False,
    )


# ---------------------------------------------------------------------------
# Sales order response
# ---------------------------------------------------------------------------

class SalesOrderResponse(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    owner_id = serializers.IntegerField(read_only=True)
    customer_name = serializers.CharField(read_only=True)
    customer_contact = serializers.CharField(allow_null=True, read_only=True)
    status = serializers.CharField(read_only=True)
    committed_at = serializers.DateTimeField(allow_null=True, read_only=True)
    voided_at = serializers.DateTimeField(allow_null=True, read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    lines = SalesOrderLineResponse(many=True, read_only=True)
    allocations = AllocationResponse(many=True, read_only=True)


class SalesOrderListResponse(serializers.Serializer):
    items = SalesOrderResponse(many=True, read_only=True)
    next_cursor = serializers.CharField(allow_null=True, read_only=True)


# ---------------------------------------------------------------------------
# Create / update requests
# ---------------------------------------------------------------------------

class SalesOrderCreateRequest(serializers.Serializer):
    customer_name = serializers.CharField(min_length=1, max_length=255)
    customer_contact = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=None
    )
    lines = serializers.ListField(
        child=SalesOrderLineRequest(),
        min_length=1,
    )


class SalesOrderUpdateRequest(serializers.Serializer):
    customer_name = serializers.CharField(min_length=1, max_length=255, required=False)
    customer_contact = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    lines = serializers.ListField(
        child=SalesOrderLineRequest(),
        required=False,
        allow_empty=False,
    )


# ---------------------------------------------------------------------------
# Commit request (optional explicit allocations for D11 admin override)
# ---------------------------------------------------------------------------

class SalesOrderCommitRequest(serializers.Serializer):
    allocations = serializers.ListField(
        child=ExplicitAllocationRequest(),
        required=False,
        allow_null=True,
        allow_empty=False,
    )


# ---------------------------------------------------------------------------
# Preview response
# ---------------------------------------------------------------------------

class SalesOrderPreviewResponse(serializers.Serializer):
    allocations = ProposedAllocationResponse(many=True, read_only=True)


# ---------------------------------------------------------------------------
# Recall report response
# ---------------------------------------------------------------------------

class RecallReportItemResponse(serializers.Serializer):
    sale_order_id = serializers.UUIDField(read_only=True)
    customer_name = serializers.CharField(read_only=True)
    customer_contact = serializers.CharField(allow_null=True, read_only=True)
    quantity_received = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    sale_committed_at = serializers.DateTimeField(read_only=True)


class RecallReportResponse(serializers.Serializer):
    items = RecallReportItemResponse(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    limit = serializers.IntegerField(read_only=True)
    offset = serializers.IntegerField(read_only=True)

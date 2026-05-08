"""Request/response serializers for apps.financials.

Naming convention: *Request for input validation, *Response for output shaping.
Money/qty: DecimalField(coerce_to_string=True) — wire format is string per SPEC §2.5.
"""

from __future__ import annotations

from datetime import date, timedelta

from rest_framework import serializers


# ---------------------------------------------------------------------------
# Query parameter validation (shared by both endpoints)
# ---------------------------------------------------------------------------

class DateRangeQuery(serializers.Serializer):
    """Validates date-range query params.

    Input keys: 'from' and 'to' (query params). Validated in validate().
    - from <= to (400 if violated)
    - (to - from) <= 365 days (400 if violated)
    - defaults: last 30 days when from/to omitted

    validated_data keys: 'date_from' (date), 'date_to' (date).
    """

    date_from = serializers.DateField(
        input_formats=["%Y-%m-%d"], required=False, allow_null=True, default=None
    )
    date_to = serializers.DateField(
        input_formats=["%Y-%m-%d"], required=False, allow_null=True, default=None
    )

    def validate(self, attrs):
        today = date.today()
        date_from: date = attrs.get("date_from") or (today - timedelta(days=30))
        date_to: date = attrs.get("date_to") or today

        if date_from > date_to:
            raise serializers.ValidationError({"from": "from must be <= to"})

        if (date_to - date_from).days > 365:
            raise serializers.ValidationError({"date_range": "date range exceeds 1 year"})

        attrs["date_from"] = date_from
        attrs["date_to"] = date_to
        return attrs


# ---------------------------------------------------------------------------
# Dashboard response
# ---------------------------------------------------------------------------

class DashboardTotalsResponse(serializers.Serializer):
    revenue = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    cogs = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    profit = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    margin_pct = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True,
        allow_null=True, read_only=True
    )


class MarginRowResponse(serializers.Serializer):
    product_id = serializers.UUIDField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    units_sold = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    revenue = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    cogs = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    profit = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True, read_only=True
    )
    margin_pct = serializers.DecimalField(
        max_digits=14, decimal_places=4, coerce_to_string=True,
        allow_null=True, read_only=True
    )


class DashboardResponse(serializers.Serializer):
    date_from = serializers.DateField(read_only=True)
    date_to = serializers.DateField(read_only=True)
    totals = DashboardTotalsResponse(read_only=True)
    top_products = MarginRowResponse(many=True, read_only=True)


# ---------------------------------------------------------------------------
# Margin list response
# ---------------------------------------------------------------------------

class MarginListResponse(serializers.Serializer):
    items = MarginRowResponse(many=True, read_only=True)
    next_cursor = serializers.CharField(allow_null=True, read_only=True)

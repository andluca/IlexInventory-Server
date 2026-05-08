"""API views for apps.financials.

Architecture: one APIView class per resource scope.
Layer flow: API → Selector → Queries → Schema (no services.py — read-only app).
Views never import from queries/ directly; they call selectors.

Owner injection: all views read owner_id from request.user.id (set by
DRF SessionAuthentication). It is never accepted from the request body.
"""

from __future__ import annotations

from datetime import date

from drf_spectacular.utils import OpenApiParameter, extend_schema

from apps.core.openapi import CSV_FORMAT_PARAMETER
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.csv_export import format_decimal, stream_csv
from apps.financials.selectors import (
    dashboard_for_owner,
    list_margin_by_product,
    stream_margin_by_product,
)
from apps.financials.serializers import (
    DashboardResponse,
    DateRangeQuery,
    MarginListResponse,
)


class FinancialsDashboardApi(APIView):
    """GET /financials/dashboard — aggregated revenue/COGS/profit/margin totals."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["financials"],
        parameters=[
            OpenApiParameter("from", str, required=False, description="Date range start (YYYY-MM-DD)"),
            OpenApiParameter("to", str, required=False, description="Date range end (YYYY-MM-DD)"),
            OpenApiParameter("top", int, required=False, description="Top-N products (default 5, max 50)"),
            CSV_FORMAT_PARAMETER,
        ],
        responses={200: DashboardResponse},
        summary="Financial dashboard totals (JSON or CSV export)",
    )
    def get(self, request: Request):  # type: ignore[override]
        """GET /financials/dashboard — aggregated dashboard or CSV of top_products."""
        owner_id = request.user.id

        # Map URL params 'from'/'to' to serializer field names 'date_from'/'date_to'
        params_data = {
            "date_from": request.query_params.get("from"),
            "date_to": request.query_params.get("to"),
        }
        ser = DateRangeQuery(data=params_data)
        if not ser.is_valid():
            return Response({"error": "ValidationError", "fields": ser.errors}, status=400)

        v = ser.validated_data
        date_from: date = v["date_from"]
        date_to: date = v["date_to"]

        raw_top = request.query_params.get("top", "5")
        try:
            top_n = min(max(int(raw_top), 1), 50)
        except (ValueError, TypeError):
            top_n = 5

        result = dashboard_for_owner(
            owner_id=owner_id,
            date_from=date_from,
            date_to=date_to,
            top_n=top_n,
        )

        _CSV_HEADER = [
            "product_id", "product_name", "units_sold",
            "revenue", "cogs", "profit", "margin_pct",
        ]

        if request.query_params.get("format") == "csv":
            def _rows():
                for row in result["top_products"]:
                    yield [
                        str(row["product_id"]),
                        row["product_name"],
                        format_decimal(row["units_sold"]),
                        format_decimal(row["revenue"]),
                        format_decimal(row["cogs"]),
                        format_decimal(row["profit"]),
                        format_decimal(row["margin_pct"]),
                    ]

            return stream_csv(
                filename=f"dashboard-{date_from.isoformat()}-{date_to.isoformat()}.csv",
                header=_CSV_HEADER,
                rows=_rows(),
            )

        serialized = DashboardResponse({
            "date_from": result["date_from"],
            "date_to": result["date_to"],
            "totals": result["totals"],
            "top_products": result["top_products"],
        })
        return Response(serialized.data)


class FinancialsMarginListApi(APIView):
    """GET /financials/margin — cursor-paginated per-product margin detail."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["financials"],
        parameters=[
            OpenApiParameter("from", str, required=False, description="Date range start (YYYY-MM-DD)"),
            OpenApiParameter("to", str, required=False, description="Date range end (YYYY-MM-DD)"),
            OpenApiParameter("cursor", str, required=False, description="Opaque cursor for next page"),
            OpenApiParameter("limit", int, required=False, description="Page size (default 50, max 100)"),
            CSV_FORMAT_PARAMETER,
        ],
        responses={200: MarginListResponse},
        summary="Per-product margin list (JSON or CSV export)",
    )
    def get(self, request: Request):  # type: ignore[override]
        """GET /financials/margin — paginated per-product margin rows or CSV export."""
        owner_id = request.user.id

        params_data = {
            "date_from": request.query_params.get("from"),
            "date_to": request.query_params.get("to"),
        }
        ser = DateRangeQuery(data=params_data)
        if not ser.is_valid():
            return Response({"error": "ValidationError", "fields": ser.errors}, status=400)

        v = ser.validated_data
        date_from: date = v["date_from"]
        date_to: date = v["date_to"]

        _CSV_HEADER = [
            "product_id", "product_name", "units_sold",
            "revenue", "cogs", "profit", "margin_pct",
        ]

        if request.query_params.get("format") == "csv":
            def _rows():
                for row in stream_margin_by_product(
                    owner_id=owner_id,
                    date_from=date_from,
                    date_to=date_to,
                ):
                    yield [
                        str(row["product_id"]),
                        row["product_name"],
                        format_decimal(row["units_sold"]),
                        format_decimal(row["revenue"]),
                        format_decimal(row["cogs"]),
                        format_decimal(row["profit"]),
                        format_decimal(row["margin_pct"]),
                    ]

            return stream_csv(
                filename=f"margin-{date_from.isoformat()}-{date_to.isoformat()}.csv",
                header=_CSV_HEADER,
                rows=_rows(),
            )

        raw_limit = request.query_params.get("limit", "50")
        try:
            limit = min(max(int(raw_limit), 1), 100)
        except (ValueError, TypeError):
            limit = 50

        result = list_margin_by_product(
            owner_id=owner_id,
            date_from=date_from,
            date_to=date_to,
            cursor=request.query_params.get("cursor"),
            limit=limit,
        )

        return Response(MarginListResponse(result).data)

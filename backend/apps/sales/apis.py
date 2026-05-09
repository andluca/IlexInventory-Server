"""API views for apps.sales.

Architecture: one APIView class per resource scope.
Layer flow: API → Service | Selector → Queries → Schema.
Views never import from queries/ directly; they call services or selectors.

Owner injection: all views read owner_id from request.user.id (set by
DRF SessionAuthentication). It is never accepted from the request body.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.errors import DomainError, to_response
from apps.core.idempotency import idempotent
from apps.sales.errors import SalesOrderNotFound
from apps.sales.selectors import list_sales_orders, sales_order_by_id
from apps.sales.serializers import (
    SalesOrderCommitRequest,
    SalesOrderCreateRequest,
    SalesOrderListResponse,
    SalesOrderPreviewResponse,
    SalesOrderResponse,
    SalesOrderUpdateRequest,
)
from apps.sales.services import (
    commit_sales_order,
    create_sales_order_draft,
    delete_sales_order_draft,
    preview_so_allocations,
    update_sales_order_draft,
    void_sales_order,
)
from apps.sales.types import ExplicitAllocation, NewSaleLine


class SalesOrderListApi(APIView):
    """GET /sales-orders — list with filters + pagination.
    POST /sales-orders — create a draft SO.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["sales"],
        parameters=[
            OpenApiParameter("status", str, required=False, description="Filter by status (draft|committed)"),
            OpenApiParameter("voided", bool, required=False, description="Filter voided state"),
            OpenApiParameter("search", str, required=False, description="ILIKE on customer_name"),
            OpenApiParameter("from", str, required=False, description="created_at >= date"),
            OpenApiParameter("to", str, required=False, description="created_at <= date"),
            OpenApiParameter("cursor", str, required=False, description="Opaque cursor for next page"),
            OpenApiParameter("limit", int, required=False, description="Page size (default 50)"),
        ],
        responses={200: SalesOrderListResponse},
        summary="List sales orders",
    )
    def get(self, request: Request) -> Response:
        """GET /sales-orders — list sales orders for the authenticated owner."""
        owner_id = request.user.id
        voided_str = request.query_params.get("voided")
        voided = None
        if voided_str is not None:
            voided = voided_str.lower() in ("true", "1", "yes")

        result = list_sales_orders(
            owner_id=owner_id,
            status=request.query_params.get("status"),
            voided=voided,
            search=request.query_params.get("search"),
            date_from=request.query_params.get("from"),
            date_to=request.query_params.get("to"),
            cursor=request.query_params.get("cursor"),
            limit=int(request.query_params.get("limit", 50)),
        )
        return Response(SalesOrderListResponse(result).data)

    @extend_schema(
        tags=["sales"],
        request=SalesOrderCreateRequest,
        responses={201: SalesOrderResponse},
        summary="Create a draft sales order",
    )
    def post(self, request: Request) -> Response:
        """POST /sales-orders — create a draft sales order."""
        owner_id = request.user.id
        ser = SalesOrderCreateRequest(data=request.data)
        if not ser.is_valid():
            return Response({"error": "ValidationError", "fields": ser.errors}, status=400)

        v = ser.validated_data
        lines: list[NewSaleLine] = [
            {
                "product_id": str(ln["product_id"]),
                "quantity": ln["quantity"],
                "sell_price": ln["sell_price"],
            }
            for ln in v["lines"]
        ]

        try:
            so = create_sales_order_draft(
                owner_id=owner_id,
                customer_name=v["customer_name"],
                customer_contact=v.get("customer_contact"),
                lines=lines,
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(SalesOrderResponse(so).data, status=status.HTTP_201_CREATED)


class SalesOrderDetailApi(APIView):
    """GET /sales-orders/{id} — detail view.
    PATCH /sales-orders/{id} — update a draft.
    DELETE /sales-orders/{id} — delete a draft.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["sales"], responses={200: SalesOrderResponse}, summary="Get sales order by ID")
    def get(self, request: Request, so_id: str) -> Response:
        """GET /sales-orders/{id} — return SO with lines + allocations."""
        owner_id = request.user.id
        so = sales_order_by_id(owner_id=owner_id, so_id=so_id)
        if so is None:
            body, http_status = to_response(SalesOrderNotFound(detail=f"Sales order {so_id} not found."))
            return Response(body, status=http_status)
        return Response(SalesOrderResponse(so).data)

    @extend_schema(
        tags=["sales"],
        request=SalesOrderUpdateRequest,
        responses={200: SalesOrderResponse},
        summary="Update a draft sales order",
    )
    def patch(self, request: Request, so_id: str) -> Response:
        """PATCH /sales-orders/{id} — update a draft SO."""
        owner_id = request.user.id
        ser = SalesOrderUpdateRequest(data=request.data)
        if not ser.is_valid():
            return Response({"error": "ValidationError", "fields": ser.errors}, status=400)

        v = ser.validated_data
        lines: list[NewSaleLine] | None = None
        if "lines" in v:
            lines = [
                {
                    "product_id": str(ln["product_id"]),
                    "quantity": ln["quantity"],
                    "sell_price": ln["sell_price"],
                }
                for ln in v["lines"]
            ]

        # Detect whether customer_contact was explicitly sent
        customer_contact_set = "customer_contact" in request.data

        try:
            so = update_sales_order_draft(
                owner_id=owner_id,
                so_id=so_id,
                customer_name=v.get("customer_name"),
                customer_contact=v.get("customer_contact"),
                customer_contact_set=customer_contact_set,
                lines=lines,
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(SalesOrderResponse(so).data)

    @extend_schema(tags=["sales"], responses={204: None}, summary="Delete a draft sales order")
    def delete(self, request: Request, so_id: str) -> Response:
        """DELETE /sales-orders/{id} — hard-delete a draft SO."""
        owner_id = request.user.id
        try:
            delete_sales_order_draft(owner_id=owner_id, so_id=so_id)
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SalesOrderPreviewApi(APIView):
    """POST /sales-orders/{id}/preview — FEFO dry-run."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["sales"],
        responses={200: SalesOrderPreviewResponse},
        summary="Preview FEFO allocations for a sales order",
    )
    def post(self, request: Request, so_id: str) -> Response:
        """POST /sales-orders/{id}/preview — return proposed FEFO allocations."""
        owner_id = request.user.id
        try:
            proposed = preview_so_allocations(owner_id=owner_id, so_id=so_id)
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(SalesOrderPreviewResponse({"allocations": proposed}).data)


class SalesOrderCommitApi(APIView):
    """POST /sales-orders/{id}/commit — terminal commit with idempotency."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["sales"],
        request=SalesOrderCommitRequest,
        responses={200: SalesOrderResponse},
        summary="Commit a draft sales order",
    )
    @idempotent("sales_orders.commit")
    def post(self, request: Request, so_id: str) -> Response:
        """POST /sales-orders/{id}/commit — commit a draft SO."""
        owner_id = request.user.id
        ser = SalesOrderCommitRequest(data=request.data or {})
        if not ser.is_valid():
            return Response({"error": "ValidationError", "fields": ser.errors}, status=400)

        v = ser.validated_data
        explicit_allocs: list[ExplicitAllocation] | None = None
        raw_allocs = v.get("allocations")
        if raw_allocs is not None:
            explicit_allocs = [
                {
                    "line_id": str(a["line_id"]),
                    "batch_id": str(a["batch_id"]),
                    "quantity": a["quantity"],
                }
                for a in raw_allocs
            ]

        try:
            so = commit_sales_order(
                owner_id=owner_id,
                so_id=so_id,
                allocations=explicit_allocs,
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(SalesOrderResponse(so).data)


class SalesOrderVoidApi(APIView):
    """POST /sales-orders/{id}/void — void with idempotency."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["sales"], responses={200: SalesOrderResponse}, summary="Void a committed sales order")
    @idempotent("sales_orders.void")
    def post(self, request: Request, so_id: str) -> Response:
        """POST /sales-orders/{id}/void — void a committed SO."""
        owner_id = request.user.id
        try:
            so = void_sales_order(owner_id=owner_id, so_id=so_id)
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(SalesOrderResponse(so).data)

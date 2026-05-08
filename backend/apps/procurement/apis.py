"""API views for apps.procurement.

Architecture: one APIView class per resource scope.
Layer flow: API → Service | Selector → Queries → Schema.
Views never import from queries/ directly; they call services or selectors.

Owner injection: all views read owner_id from request.user.id (set by
DRF SessionAuthentication). It is never accepted from the request body.
"""

from __future__ import annotations

import uuid

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.errors import DomainError, to_response
from apps.core.idempotency import idempotent
from apps.procurement.errors import PurchaseOrderNotFound
from apps.procurement.selectors import (
    list_purchase_orders,
    purchase_order_by_id,
)
from apps.procurement.serializers import (
    PurchaseOrderCreateRequest,
    PurchaseOrderListResponse,
    PurchaseOrderReceiveRequest,
    PurchaseOrderResponse,
    PurchaseOrderUpdateRequest,
)
from apps.procurement.services import (
    create_purchase_order_draft,
    delete_purchase_order_draft,
    receive_purchase_order,
    update_purchase_order_draft,
)


class PurchaseOrderListApi(APIView):
    """GET /purchase-orders — list with filters + pagination.
    POST /purchase-orders — create a draft PO.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, required=False, description="Filter by status: draft or received"),
            OpenApiParameter("search", str, required=False, description="ILIKE on supplier_name"),
            OpenApiParameter("from", str, required=False, description="created_at >= date (ISO)"),
            OpenApiParameter("to", str, required=False, description="created_at <= date (ISO)"),
            OpenApiParameter("limit", int, required=False, description="Page size (default 50)"),
            OpenApiParameter("offset", int, required=False, description="Page offset (default 0)"),
        ],
        responses={200: PurchaseOrderListResponse},
        summary="List purchase orders",
    )
    def get(self, request: Request) -> Response:
        search = request.query_params.get("search") or None
        po_status = request.query_params.get("status") or None
        date_from = request.query_params.get("from") or None
        date_to = request.query_params.get("to") or None

        try:
            limit = int(request.query_params.get("limit", 50))
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            return Response(
                {"error": "ValidationError", "detail": "limit and offset must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = list_purchase_orders(
            owner_id=request.user.id,
            status=po_status,
            search=search,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )

        serializer = PurchaseOrderListResponse(result)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=PurchaseOrderCreateRequest,
        responses={200: PurchaseOrderResponse, 400: None, 404: None},
        summary="Create a draft purchase order",
    )
    def post(self, request: Request) -> Response:
        serializer = PurchaseOrderCreateRequest(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "ValidationError", "fields": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            po = create_purchase_order_draft(
                owner_id=request.user.id,
                supplier_name=serializer.validated_data["supplier_name"],
                supplier_contact=serializer.validated_data.get("supplier_contact"),
                lines=serializer.validated_data["lines"],
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(PurchaseOrderResponse(po).data, status=status.HTTP_200_OK)


class PurchaseOrderDetailApi(APIView):
    """GET / PATCH / DELETE /purchase-orders/{po_id}."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: PurchaseOrderResponse, 404: None},
        summary="Get a purchase order by ID",
    )
    def get(self, request: Request, po_id: uuid.UUID) -> Response:
        po = purchase_order_by_id(owner_id=request.user.id, po_id=str(po_id))
        if po is None:
            body, http_status = to_response(PurchaseOrderNotFound())
            return Response(body, status=http_status)

        return Response(PurchaseOrderResponse(po).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=PurchaseOrderUpdateRequest,
        responses={200: PurchaseOrderResponse, 400: None, 404: None, 409: None},
        summary="Update a draft purchase order",
    )
    def patch(self, request: Request, po_id: uuid.UUID) -> Response:
        serializer = PurchaseOrderUpdateRequest(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "ValidationError", "fields": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            po = update_purchase_order_draft(
                owner_id=request.user.id,
                po_id=po_id,
                supplier_name=serializer.validated_data.get("supplier_name"),
                supplier_contact=serializer.validated_data.get("supplier_contact"),
                lines=serializer.validated_data.get("lines"),
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(PurchaseOrderResponse(po).data, status=status.HTTP_200_OK)

    @extend_schema(
        responses={204: None, 404: None, 409: None},
        summary="Delete a draft purchase order",
    )
    def delete(self, request: Request, po_id: uuid.UUID) -> Response:
        try:
            delete_purchase_order_draft(
                owner_id=request.user.id,
                po_id=po_id,
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(status=status.HTTP_204_NO_CONTENT)


class PurchaseOrderReceiveApi(APIView):
    """POST /purchase-orders/{po_id}/receive — receive a draft PO."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PurchaseOrderReceiveRequest,
        responses={200: PurchaseOrderResponse, 400: None, 404: None, 409: None},
        summary="Receive a purchase order (requires Idempotency-Key header)",
    )
    @idempotent("purchase_orders.receive")
    def post(self, request: Request, po_id: uuid.UUID) -> Response:
        serializer = PurchaseOrderReceiveRequest(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "ValidationError", "fields": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        line_metadata = [
            {
                "line_id": str(ln["line_id"]),
                "batch_code": ln["batch_code"],
                "expiration_date": (
                    ln["expiration_date"].isoformat() if ln.get("expiration_date") else None
                ),
            }
            for ln in serializer.validated_data["lines"]
        ]

        try:
            po = receive_purchase_order(
                owner_id=request.user.id,
                po_id=po_id,
                line_metadata=line_metadata,
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(PurchaseOrderResponse(po).data, status=status.HTTP_200_OK)

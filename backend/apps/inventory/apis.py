"""API views for apps.inventory.

Architecture: one APIView class per resource scope.
Layer flow: API → Service | Selector → Queries → Schema.
Views never import from queries/ directly; they call services or selectors.

Owner injection: all views read owner_id from request.user.id (set by
DRF SessionAuthentication). It is never accepted from the request body.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema

from apps.core.openapi import CSV_FORMAT_PARAMETER
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.csv_export import format_datetime, format_decimal, stream_csv
from apps.core.errors import DomainError, to_response
from apps.core.idempotency import idempotent
from apps.inventory.errors import BatchNotFound
from apps.inventory.selectors import (
    batch_by_id,
    list_batches,
    list_movements,
    stream_movements_for_owner,
)
from apps.inventory.serializers import (
    BatchCreateRequest,
    BatchListResponse,
    BatchPatchMetadataRequest,
    BatchResponse,
    MovementCreateRequest,
    MovementListResponse,
    MovementResponse,
    RecallRequest,
)
from apps.inventory.services import (
    create_manual_batch,
    record_movement,
    recall_batch,
    un_recall_batch,
    update_batch_metadata,
)
from apps.sales.selectors import list_recall_report_for_batch, stream_recall_report_for_batch
from apps.sales.serializers import RecallReportResponse


class BatchListApi(APIView):
    """GET /batches — list with filters + pagination.
    POST /batches — create a manual batch.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["inventory"],
        parameters=[
            OpenApiParameter("product_id", str, required=False, description="Filter by product UUID"),
            OpenApiParameter("is_recalled", bool, required=False, description="Filter recalled only"),
            OpenApiParameter("expiring_within", int, required=False, description="Batches expiring within N days"),
            OpenApiParameter("limit", int, required=False, description="Page size (default 50)"),
            OpenApiParameter("offset", int, required=False, description="Page offset (default 0)"),
        ],
        responses={200: BatchListResponse},
        summary="List batches",
    )
    def get(self, request: Request) -> Response:
        """GET /batches — list batches for the authenticated owner."""
        owner_id = request.user.id
        product_id = request.query_params.get("product_id")
        is_recalled_str = request.query_params.get("is_recalled")
        is_recalled = None
        if is_recalled_str is not None:
            is_recalled = is_recalled_str.lower() in ("true", "1", "yes")
        expiring_within = request.query_params.get("expiring_within")
        if expiring_within is not None:
            try:
                expiring_within = int(expiring_within)
            except ValueError:
                expiring_within = None
        limit = int(request.query_params.get("limit", 50))
        offset = int(request.query_params.get("offset", 0))

        result = list_batches(
            owner_id=owner_id,
            product_id=product_id,
            is_recalled=is_recalled,
            expiring_within=expiring_within,
            limit=limit,
            offset=offset,
        )
        return Response(BatchListResponse(result).data)

    @extend_schema(
        tags=["inventory"],
        request=BatchCreateRequest,
        responses={201: BatchResponse},
        summary="Create a manual batch",
    )
    @idempotent("batches.create")
    def post(self, request: Request) -> Response:
        """POST /batches — create a manual batch (idempotency-keyed)."""
        owner_id = request.user.id
        ser = BatchCreateRequest(data=request.data)
        if not ser.is_valid():
            return Response({"error": "ValidationError", "fields": ser.errors}, status=400)

        v = ser.validated_data
        try:
            batch = create_manual_batch(
                owner_id=owner_id,
                product_id=str(v["product_id"]),
                batch_code=v["batch_code"],
                expiration_date=v.get("expiration_date"),
                unit_cost=v["unit_cost"],
                initial_quantity=v["initial_quantity"],
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(BatchResponse(batch).data, status=status.HTTP_201_CREATED)


class BatchDetailApi(APIView):
    """GET /batches/{id} — batch detail.
    PATCH /batches/{id} — update batch metadata.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["inventory"], responses={200: BatchResponse}, summary="Get batch by ID")
    def get(self, request: Request, batch_id: str) -> Response:
        """GET /batches/{id} — return batch with on_hand + recall state."""
        owner_id = request.user.id
        batch = batch_by_id(owner_id=owner_id, batch_id=batch_id)
        if batch is None:
            body, http_status = to_response(BatchNotFound(detail=f"Batch {batch_id} not found."))
            return Response(body, status=http_status)
        return Response(BatchResponse(batch).data)

    @extend_schema(
        tags=["inventory"],
        request=BatchPatchMetadataRequest,
        responses={200: BatchResponse},
        summary="Update batch metadata",
    )
    def patch(self, request: Request, batch_id: str) -> Response:
        """PATCH /batches/{id} — update batch_code and/or expiration_date."""
        owner_id = request.user.id
        ser = BatchPatchMetadataRequest(data=request.data)
        if not ser.is_valid():
            return Response({"error": "ValidationError", "fields": ser.errors}, status=400)

        v = ser.validated_data
        try:
            batch = update_batch_metadata(
                owner_id=owner_id,
                batch_id=batch_id,
                batch_code=v.get("batch_code"),
                expiration_date=v.get("expiration_date"),
                clear_expiration=v.get("clear_expiration", False),
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(BatchResponse(batch).data)


class BatchMovementsApi(APIView):
    """POST /batches/{id}/movements — record an adjustment or write-off.

    SPEC §2.6 mandates `Idempotency-Key` for write_off (a stock-debiting
    operation that is destructive on retry). Adjustment is a free-form audit
    correction and does not require the header. The view dispatches by `kind`:
    write_off goes through the `@idempotent`-decorated path, adjustment runs
    directly. Pre-ILEX-016, neither was decorated and a retried write_off
    could double-debit stock.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["inventory"],
        request=MovementCreateRequest,
        responses={200: MovementResponse},
        summary="Record a stock movement",
    )
    def post(self, request: Request, batch_id: str) -> Response:
        owner_id = request.user.id
        ser = MovementCreateRequest(data=request.data)
        if not ser.is_valid():
            return Response({"error": "ValidationError", "fields": ser.errors}, status=400)

        v = ser.validated_data
        if v["kind"] == "write_off":
            return self._post_write_off(request, batch_id, v, owner_id)
        return self._record(batch_id, v, owner_id)

    @idempotent("inventory.write_off")
    def _post_write_off(self, request: Request, batch_id: str, v: dict, owner_id: int) -> Response:
        """Idempotent path for `kind == "write_off"`. Wraps `_record`."""
        return self._record(batch_id, v, owner_id)

    def _record(self, batch_id: str, v: dict, owner_id: int) -> Response:
        try:
            movement = record_movement(
                owner_id=owner_id,
                batch_id=batch_id,
                kind=v["kind"],
                signed_quantity=v["signed_quantity"],
                notes=v.get("notes"),
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(MovementResponse(movement).data)


class BatchRecallApi(APIView):
    """POST /batches/{id}/recall — recall a batch (idempotency-keyed)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["inventory"],
        request=RecallRequest,
        responses={200: BatchResponse},
        summary="Recall a batch",
    )
    @idempotent("batches.recall")
    def post(self, request: Request, batch_id: str) -> Response:
        """POST /batches/{id}/recall."""
        owner_id = request.user.id
        ser = RecallRequest(data=request.data)
        if not ser.is_valid():
            return Response({"error": "ValidationError", "fields": ser.errors}, status=400)

        try:
            batch = recall_batch(
                owner_id=owner_id,
                batch_id=batch_id,
                reason=ser.validated_data["reason"],
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(BatchResponse(batch).data)


class BatchUnRecallApi(APIView):
    """POST /batches/{id}/un-recall — un-recall a batch (idempotency-keyed)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["inventory"], responses={200: BatchResponse}, summary="Un-recall a batch")
    @idempotent("batches.un_recall")
    def post(self, request: Request, batch_id: str) -> Response:
        """POST /batches/{id}/un-recall."""
        owner_id = request.user.id
        try:
            batch = un_recall_batch(owner_id=owner_id, batch_id=batch_id)
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(BatchResponse(batch).data)


class MovementsAuditApi(APIView):
    """GET /movements — cross-cutting movements audit with cursor pagination."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["inventory"],
        parameters=[
            OpenApiParameter("batch_id", str, required=False, description="Filter by batch UUID"),
            OpenApiParameter("product_id", str, required=False, description="Filter by product UUID (via batch join)"),
            OpenApiParameter("kind", str, required=False, description="Exact kind filter"),
            OpenApiParameter("from", str, required=False, description="created_at >= date"),
            OpenApiParameter("to", str, required=False, description="created_at <= date"),
            OpenApiParameter("cursor", str, required=False, description="Opaque cursor for next page"),
            OpenApiParameter("limit", int, required=False, description="Page size (default 50)"),
            CSV_FORMAT_PARAMETER,
        ],
        responses={200: MovementListResponse},
        summary="List stock movements (JSON or CSV export)",
    )
    def get(self, request: Request):  # type: ignore[override]
        """GET /movements — paginated audit log or CSV streaming export."""
        owner_id = request.user.id
        batch_id = request.query_params.get("batch_id")
        product_id = request.query_params.get("product_id")
        kind = request.query_params.get("kind")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")

        if request.query_params.get("format") == "csv":
            _CSV_HEADER = [
                "id", "owner_id", "batch_id", "kind", "signed_quantity",
                "notes", "reference_type", "reference_id", "created_at",
            ]

            def _rows():
                for row in stream_movements_for_owner(
                    owner_id=owner_id,
                    batch_id=batch_id,
                    product_id=product_id,
                    kind=kind,
                    date_from=date_from,
                    date_to=date_to,
                ):
                    yield [
                        str(row["id"]),
                        str(row["owner_id"]),
                        str(row["batch_id"]),
                        row["kind"],
                        format_decimal(row["signed_quantity"]),
                        row["notes"] or "",
                        row["reference_type"] or "",
                        str(row["reference_id"]) if row["reference_id"] else "",
                        format_datetime(row["created_at"]),
                    ]

            return stream_csv(
                filename=f"movements-{owner_id}.csv",
                header=_CSV_HEADER,
                rows=_rows(),
            )

        result = list_movements(
            owner_id=owner_id,
            batch_id=batch_id,
            product_id=product_id,
            kind=kind,
            date_from=date_from,
            date_to=date_to,
            cursor=request.query_params.get("cursor"),
            limit=int(request.query_params.get("limit", 50)),
        )
        return Response(MovementListResponse(result).data)


class BatchRecallReportApi(APIView):
    """GET /batches/{id}/recall-report — customers who received units from this batch."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["inventory"],
        parameters=[
            OpenApiParameter("limit", int, required=False, description="Page size (default 50)"),
            OpenApiParameter("offset", int, required=False, description="Page offset (default 0)"),
            CSV_FORMAT_PARAMETER,
        ],
        responses={200: RecallReportResponse},
        summary="Recall report for a batch (JSON or CSV export)",
    )
    def get(self, request: Request, batch_id: str):  # type: ignore[override]
        """GET /batches/{id}/recall-report — recall report for a batch (JSON or CSV)."""
        owner_id = request.user.id

        # Pre-check: batch must exist and belong to this owner (404 otherwise).
        batch = batch_by_id(owner_id=owner_id, batch_id=batch_id)
        if batch is None:
            body, http_status = to_response(BatchNotFound(detail=f"Batch {batch_id} not found."))
            return Response(body, status=http_status)

        _CSV_HEADER = [
            "sale_order_id", "customer_name", "customer_contact",
            "quantity_received", "sale_committed_at",
        ]

        if request.query_params.get("format") == "csv":
            def _rows():
                for row in stream_recall_report_for_batch(
                    owner_id=owner_id,
                    batch_id=batch_id,
                ):
                    yield [
                        str(row["sale_order_id"]),
                        row["customer_name"],
                        row["customer_contact"] or "",
                        format_decimal(row["quantity_received"]),
                        format_datetime(row["sale_committed_at"]),
                    ]

            return stream_csv(
                filename=f"recall-report-{batch_id}.csv",
                header=_CSV_HEADER,
                rows=_rows(),
            )

        limit = int(request.query_params.get("limit", 50))
        offset = int(request.query_params.get("offset", 0))

        result = list_recall_report_for_batch(
            owner_id=owner_id,
            batch_id=batch_id,
            limit=limit,
            offset=offset,
        )
        serialized = RecallReportResponse({
            "items": result["items"],
            "total": result["total"],
            "limit": result["limit"],
            "offset": result["offset"],
        })
        return Response(serialized.data)

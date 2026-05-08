"""Unit tests for procurement errors — pure logic, no DB."""

from __future__ import annotations

from apps.core.errors import to_response
from apps.procurement.errors import (
    ProductNotFound,
    PurchaseOrderAlreadyReceived,
    PurchaseOrderNotDraft,
    PurchaseOrderNotFound,
    ReceiveLinesMismatch,
)


def test_po_not_found_maps_to_404():
    body, status = to_response(PurchaseOrderNotFound())
    assert status == 404
    assert body["error"] == "PurchaseOrderNotFound"


def test_po_not_draft_maps_to_409():
    body, status = to_response(PurchaseOrderNotDraft())
    assert status == 409
    assert body["error"] == "PurchaseOrderNotDraft"


def test_po_already_received_maps_to_409():
    body, status = to_response(PurchaseOrderAlreadyReceived())
    assert status == 409
    assert body["error"] == "PurchaseOrderAlreadyReceived"


def test_product_not_found_maps_to_404():
    body, status = to_response(ProductNotFound())
    assert status == 404
    assert body["error"] == "ProductNotFound"


def test_receive_lines_mismatch_maps_to_400():
    body, status = to_response(ReceiveLinesMismatch())
    assert status == 400
    assert body["error"] == "ReceiveLinesMismatch"

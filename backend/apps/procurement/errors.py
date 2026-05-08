"""Domain errors for apps.procurement.

All error codes used by procurement services. The DRF exception handler maps:
  NotFound    → 404
  Conflict    → 409
  ValidationError → 400
"""

from __future__ import annotations

from apps.core.errors import Conflict, NotFound, ValidationError


class PurchaseOrderNotFound(NotFound):
    code = "PurchaseOrderNotFound"


class PurchaseOrderNotDraft(Conflict):
    code = "PurchaseOrderNotDraft"


class PurchaseOrderAlreadyReceived(Conflict):
    code = "PurchaseOrderAlreadyReceived"


class ProductNotFound(NotFound):
    """Re-raised when a line's product_id is unknown for the owner.

    NOTE: apps.catalog.errors also defines ProductNotFound with the same code.
    Both have code="ProductNotFound" so wire-level error envelopes are identical.
    Procurement defines its own to avoid a cross-app import from catalog.
    """
    code = "ProductNotFound"


class ReceiveLinesMismatch(ValidationError):
    """body's line_ids don't match the PO's lines exactly."""
    code = "ReceiveLinesMismatch"

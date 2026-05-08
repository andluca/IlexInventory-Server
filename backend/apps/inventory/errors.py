"""Domain errors for apps.inventory.

All error codes used by inventory services. The DRF exception handler maps:
  NotFound        → 404
  Conflict        → 409
  ValidationError → 400
  Unprocessable   → 422
"""

from __future__ import annotations

from apps.core.errors import Conflict, NotFound, Unprocessable, ValidationError


class BatchNotFound(NotFound):
    code = "BatchNotFound"


class ProductNotFound(NotFound):
    code = "ProductNotFound"


class BatchAlreadyRecalled(Conflict):
    """Reserved for callers that need an explicit conflict on recalled state.
    recall_batch itself is idempotent and does NOT raise this (D3).
    """

    code = "BatchAlreadyRecalled"


class BatchHasMovements(Conflict):
    """Raised when a service refuses an action because movements exist."""

    code = "BatchHasMovements"


class BatchExists(Conflict):
    """Duplicate (owner_id, product_id, batch_code)."""

    code = "BatchExists"


class WriteOffExceedsOnHand(Unprocessable):
    """write_off would drive on_hand negative."""

    code = "WriteOffExceedsOnHand"


class InvalidMovementKind(ValidationError):
    """kind value outside the public allowlist for record_movement."""

    code = "InvalidMovementKind"


class InvalidMetadataField(ValidationError):
    """PATCH attempted to update a non-allowlisted field."""

    code = "InvalidMetadataField"


class RecallReasonRequired(ValidationError):
    """recall_batch called with blank/empty reason."""

    code = "RecallReasonRequired"

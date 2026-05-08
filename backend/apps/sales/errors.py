"""Domain errors for apps.sales.

All error codes used by sales services. The DRF exception handler maps:
  NotFound        → 404
  Conflict        → 409
  ValidationError → 400
  Unprocessable   → 422
"""

from __future__ import annotations

from apps.core.errors import Conflict, NotFound, Unprocessable, ValidationError


class SalesOrderNotFound(NotFound):
    code = "SalesOrderNotFound"


class ProductNotFound(NotFound):
    code = "ProductNotFound"


class SalesOrderNotDraft(Conflict):
    """Raised when an operation requires draft status but SO is committed."""

    code = "SalesOrderNotDraft"


class SalesOrderNotCommitted(Conflict):
    """Raised when void requires committed status but SO is in draft."""

    code = "SalesOrderNotCommitted"


class InsufficientStock(Unprocessable):
    """FEFO walk could not satisfy the required quantity from eligible batches.

    The ``shortfall`` field contains the machine-readable payload:
        {"product_id": "...", "required": "...", "available": "..."}
    """

    code = "InsufficientStock"


class InvalidAllocation(Unprocessable):
    """Explicit allocations body fails validation (recalled/expired/cross-product/etc.)."""

    code = "InvalidAllocation"


class ValidationError(ValidationError):
    """Request payload failed validation."""

    code = "ValidationError"

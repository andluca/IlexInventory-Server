"""Domain errors for apps.catalog.

All error codes used by catalog services. The DRF exception handler maps:
  NotFound    → 404
  Conflict    → 409
  ValidationError → 400
"""

from __future__ import annotations

from apps.core.errors import Conflict, NotFound, ValidationError


class ProductNotFound(NotFound):
    code = "ProductNotFound"


class DuplicateSKU(Conflict):
    code = "DuplicateSKU"


class ProductHasBatches(Conflict):
    code = "ProductHasBatches"


class ProductHasNoBatches(Conflict):
    code = "ProductHasNoBatches"


class CsvParseError(ValidationError):
    code = "CsvParseError"

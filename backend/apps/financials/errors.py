"""Domain errors for apps.financials.

Date-range validation lives in the API layer (serializer).
This module re-exports ValidationError from core for use in the API layer.
"""

from __future__ import annotations

from apps.core.errors import ValidationError as ValidationError  # noqa: PLC0414

__all__ = ["ValidationError"]

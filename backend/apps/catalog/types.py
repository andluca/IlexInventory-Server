"""Shared typed data structures for apps.catalog."""

from __future__ import annotations

from typing import Any, TypedDict


class ProductRow(TypedDict):
    id: str  # UUID as string
    owner_id: int
    sku: str
    name: str
    description: str
    base_unit: str
    archived_at: Any  # datetime | None
    created_at: Any   # datetime
    updated_at: Any   # datetime


class FailedRow(TypedDict):
    row_index: int
    error: str
    detail: str | None
    fields: dict[str, Any] | None


class ImportReport(TypedDict):
    imported: int
    failed: list[FailedRow]

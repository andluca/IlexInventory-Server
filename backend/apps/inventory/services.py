"""Inventory services — stub for ILEX-005.

Issue 006 replaces the body of create_receipt_batches with real
batch + stock_movement inserts once 0005_inventory.sql lands.
"""

from __future__ import annotations

from typing import Any


def create_receipt_batches(
    *,
    owner_id: int,
    lines: list[dict[str, Any]],
) -> list[dict]:
    """Create one batch per line and one receipt movement per batch.

    Stub — returns [] until Issue 006 implements the inventory schema.
    Issue 006 replaces this body and adds the 0005_inventory.sql migration.
    """
    return []

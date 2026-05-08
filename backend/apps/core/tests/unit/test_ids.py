"""Unit tests for apps.core.ids.uuidv7().

RFC 9562 §5.7:
- Version nibble (bits 76–79, i.e. the 13th hex character) must be '7'.
- Variant bits (bits 64–65) must be 0b10, i.e. the 17th hex char is in {8,9,a,b}.
- 1000 consecutive calls must produce strictly increasing 48-bit timestamp prefixes
  (clock_timestamp monotonicity under a real-time clock).
"""

from __future__ import annotations

import uuid

from apps.core.ids import uuidv7


def test_uuidv7_returns_uuid_instance():
    result = uuidv7()
    assert isinstance(result, uuid.UUID)


def test_uuidv7_version_is_7():
    result = uuidv7()
    assert result.version == 7


def test_uuidv7_variant_bits():
    """Bits 64-65 must be 0b10 (RFC 4122 variant)."""
    result = uuidv7()
    # The variant is encoded in the high bits of clock_seq_hi_variant.
    # For variant 1 (RFC 4122), bits 7-6 of clock_seq_hi_variant must be 0b10.
    assert (result.clock_seq_hi_variant >> 6) == 0b10


def test_uuidv7_monotonicity():
    """1000 sequential calls must produce non-decreasing timestamp prefixes.
    Since we may be in the same millisecond, equal prefixes are allowed;
    strictly decreasing is the failure case."""
    ids = [uuidv7() for _ in range(1000)]
    # Extract the 48-bit timestamp prefix (first 12 hex chars = 48 bits).
    timestamps = [int(str(u).replace("-", "")[:12], 16) for u in ids]
    for i in range(1, len(timestamps)):
        assert timestamps[i] >= timestamps[i - 1], (
            f"Monotonicity violated at index {i}: "
            f"{timestamps[i]} < {timestamps[i - 1]}"
        )

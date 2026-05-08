"""UUIDv7 generator — Python companion to the SQL uuidv7() function.

Implements RFC 9562 §5.7: 48-bit millisecond timestamp + 4-bit version (7)
+ 12 random bits + 2-bit variant (0b10) + 62 random bits.

BE-D5: every table uses UUIDv7 primary keys.
"""

from __future__ import annotations

import os
import time
import uuid


def uuidv7() -> uuid.UUID:
    """Return a UUIDv7: time-ordered, random-suffix, RFC 9562 §5.7.

    Layout (128 bits):
        [48 ms_timestamp][4 version=0x7][12 rand_a][2 variant=0b10][62 rand_b]
    """
    # 48-bit millisecond timestamp (Unix epoch)
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF

    # 74 random bits split into rand_a (12 bits) and rand_b (62 bits)
    rand_bytes = int.from_bytes(os.urandom(10), "big")
    rand_a = (rand_bytes >> 62) & 0xFFF      # top 12 bits
    rand_b = rand_bytes & 0x3FFFFFFFFFFFFFFF  # bottom 62 bits

    # Assemble 128-bit integer per RFC 9562 §5.7
    #   bits 127-80 : ms timestamp (48 bits)
    #   bits 79-76  : version = 0x7 (4 bits)
    #   bits 75-64  : rand_a (12 bits)
    #   bits 63-62  : variant = 0b10 (2 bits)
    #   bits 61-0   : rand_b (62 bits)
    value = (
        (ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )

    return uuid.UUID(int=value)

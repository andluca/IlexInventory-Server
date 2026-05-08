"""Shared streaming-CSV helper for ?format=csv endpoints.

Pattern: each APIView that supports CSV export branches on
    request.query_params.get("format") == "csv"
and returns a StreamingHttpResponse built by stream_csv().

No DRF renderer is used — DRF's renderer pipeline buffers before flushing,
defeating the streaming requirement for large exports.

See ILEX-009 §Lib: csv_export.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from django.http import StreamingHttpResponse


class _Echo:
    """Pseudo-buffer that csv.writer can write to for streaming.

    Django's streaming CSV pattern (docs.djangoproject.com):
      writer writes to Echo, Echo.write() returns the value to the generator.
    """

    def write(self, value: str) -> str:
        return value


def _rows_generator(
    header: list[str],
    rows: Iterable[Iterable[Any]],
) -> Iterable[str]:
    """Generator that yields CSV lines including the header."""
    pseudo_buffer = _Echo()
    writer = csv.writer(pseudo_buffer, quoting=csv.QUOTE_MINIMAL)

    yield writer.writerow(header)
    for row in rows:
        yield writer.writerow(list(row))


def stream_csv(
    filename: str,
    header: list[str],
    rows: Iterable[Iterable[Any]],
) -> StreamingHttpResponse:
    """Return a StreamingHttpResponse that streams CSV rows.

    Content-Type:        text/csv; charset=utf-8
    Content-Disposition: attachment; filename="<filename>"

    The header row is written first, then one row per item in `rows`.
    Dates are ISO-8601; Decimals as str(d) (preserves trailing zeros).
    """
    response = StreamingHttpResponse(
        _rows_generator(header, rows),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Value formatters
# ---------------------------------------------------------------------------

def format_decimal(d: Decimal | None) -> str:
    """Return "" for None, else str(d) preserving trailing zeros (e.g. "12.0000")."""
    if d is None:
        return ""
    return str(d)


def format_datetime(dt: datetime | None) -> str:
    """Return "" for None, else dt.isoformat()."""
    if dt is None:
        return ""
    return dt.isoformat()


def format_date(d: date | None) -> str:
    """Return "" for None, else d.isoformat()."""
    if d is None:
        return ""
    return d.isoformat()

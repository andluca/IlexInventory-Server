"""Unit tests for apps.core.csv_export.

Behavioral tests: exercise stream_csv, format_decimal, format_datetime,
format_date through their public interface.  No _private helper imports.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from apps.core.csv_export import (
    format_date,
    format_datetime,
    format_decimal,
    stream_csv,
)


# ---------------------------------------------------------------------------
# stream_csv — wire bytes
# ---------------------------------------------------------------------------

def _collect_body(response) -> str:
    """Join streaming_content bytes into a decoded string."""
    return b"".join(response.streaming_content).decode("utf-8")


def test_stream_csv_header_and_two_rows():
    """stream_csv emits header line then one line per row."""
    header = ["id", "name", "qty"]
    rows = [
        ["row1", "Widget A", "10.0000"],
        ["row2", "Widget B", "5.0000"],
    ]
    response = stream_csv("test.csv", header, rows)
    body = _collect_body(response)
    lines = body.splitlines()
    assert lines[0] == "id,name,qty"
    assert lines[1] == "row1,Widget A,10.0000"
    assert lines[2] == "row2,Widget B,5.0000"
    assert len(lines) == 3


def test_stream_csv_rfc4180_quoting_on_value_with_comma():
    """A cell containing a comma is double-quoted per RFC 4180."""
    header = ["id", "description"]
    rows = [["r1", "apples, oranges"]]
    response = stream_csv("test.csv", header, rows)
    body = _collect_body(response)
    lines = body.splitlines()
    assert lines[1] == 'r1,"apples, oranges"'


def test_stream_csv_content_type():
    """Response carries Content-Type: text/csv; charset=utf-8."""
    response = stream_csv("export.csv", ["a"], [["v"]])
    assert response["Content-Type"] == "text/csv; charset=utf-8"


def test_stream_csv_content_disposition():
    """Response carries Content-Disposition: attachment; filename=..."""
    response = stream_csv("myfile.csv", ["a"], [])
    disposition = response["Content-Disposition"]
    assert disposition == 'attachment; filename="myfile.csv"'


def test_stream_csv_empty_rows_produces_header_only():
    """Empty rows iterable: response body is exactly the header line."""
    response = stream_csv("empty.csv", ["x", "y"], [])
    body = _collect_body(response)
    lines = body.splitlines()
    assert len(lines) == 1
    assert lines[0] == "x,y"


# ---------------------------------------------------------------------------
# format_decimal
# ---------------------------------------------------------------------------

def test_format_decimal_none_returns_empty_string():
    assert format_decimal(None) == ""


def test_format_decimal_preserves_trailing_zeros():
    """str(Decimal("12.0000")) must preserve the four decimal places."""
    assert format_decimal(Decimal("12.0000")) == "12.0000"


def test_format_decimal_integer_decimal():
    assert format_decimal(Decimal("100")) == "100"


def test_format_decimal_negative():
    assert format_decimal(Decimal("-5.2500")) == "-5.2500"


# ---------------------------------------------------------------------------
# format_datetime
# ---------------------------------------------------------------------------

def test_format_datetime_none_returns_empty_string():
    assert format_datetime(None) == ""


def test_format_datetime_returns_isoformat():
    dt = datetime(2026, 4, 8, 14, 20, 0, tzinfo=timezone.utc)
    result = format_datetime(dt)
    assert result == "2026-04-08T14:20:00+00:00"


# ---------------------------------------------------------------------------
# format_date
# ---------------------------------------------------------------------------

def test_format_date_none_returns_empty_string():
    assert format_date(None) == ""


def test_format_date_returns_isoformat():
    d = date(2026, 12, 31)
    assert format_date(d) == "2026-12-31"

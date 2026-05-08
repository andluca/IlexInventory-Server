"""Domain error hierarchy for Ilex Inventory.

Services and selectors raise subclasses of DomainError.
The API layer catches DomainError and calls to_response() to map to HTTP.

Error envelope per SPEC §2.6:
    { "error": "<code>", "detail"?: "...", "fields"?: { ... } }

Each subclass has a fixed ``code`` class attribute that becomes the ``error``
field in the response envelope. Positional ``code`` on subclasses is ignored
in favour of the class-level attribute — it exists only for internal use
(e.g. machine-readable slug passed to logging).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base domain error. All business-rule violations raise a subclass."""

    code: str = "DomainError"

    def __init__(
        self,
        code: str | None = None,
        *,
        detail: str | None = None,
        fields: dict | None = None,
    ) -> None:
        # On the base class, a positional code argument overrides the default.
        # On subclasses, the class-level code wins (set by the subclass).
        if code is not None and type(self) is DomainError:
            self.code = code
        self.detail = detail
        self.fields = fields
        super().__init__(self.code)


class NotFound(DomainError):
    """Resource not found — also raised on cross-owner access (D4: 404 not 403)."""

    code = "NotFound"


class ValidationError(DomainError):
    """Request payload failed validation."""

    code = "ValidationError"


class Conflict(DomainError):
    """State conflict — SKU lock, terminal-state PATCH/DELETE."""

    code = "Conflict"


class Unprocessable(DomainError):
    """Business-rule violation — FEFO shortfall, write-off-into-negative."""

    code = "Unprocessable"


_HTTP_STATUS: dict[type[DomainError], int] = {
    NotFound: 404,
    ValidationError: 400,
    Conflict: 409,
    Unprocessable: 422,
    DomainError: 500,
}


def to_response(exc: DomainError) -> tuple[dict, int]:
    """Map a DomainError to (response_body, http_status).

    Raises TypeError if exc is not a DomainError — the caller is responsible
    for mapping framework errors (e.g. DRF serializer errors) separately.
    """
    if not isinstance(exc, DomainError):
        raise TypeError(f"Expected DomainError, got {type(exc).__name__}")

    body: dict = {"error": exc.code}
    if exc.detail is not None:
        body["detail"] = exc.detail
    if exc.fields is not None:
        body["fields"] = exc.fields

    # Walk MRO so subclasses of the four leaf classes also resolve correctly.
    status = 500
    for cls in type(exc).__mro__:
        if cls in _HTTP_STATUS:
            status = _HTTP_STATUS[cls]
            break

    return body, status

"""CORS preflight tests for cross-origin terminal mutations.

The FE attaches `Idempotency-Key` on every SPEC §2.5 terminal mutation
(commit SO, void SO, receive PO, recall, un-recall, manual batch, write-off,
products import). Cross-origin (Netlify ↔ Railway) the browser issues an
OPTIONS preflight first; if `idempotency-key` isn't in
Access-Control-Allow-Headers the actual request never goes out.

`django-cors-headers`' default allowlist permits x-csrftoken but not
idempotency-key, so settings/base.py extends it explicitly.
"""

from __future__ import annotations

from django.test import Client


def test_preflight_allows_idempotency_key_on_terminal_endpoint():
    """OPTIONS preflight to a terminal endpoint advertises `idempotency-key`."""
    client = Client()

    resp = client.options(
        "/api/v1/sales-orders/00000000-0000-0000-0000-000000000000/commit",
        HTTP_ORIGIN="https://ilexinventory.netlify.app",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="idempotency-key, x-csrftoken, content-type",
    )

    assert resp.status_code == 200, f"preflight should return 200, got {resp.status_code}"

    allow_headers = resp.get("Access-Control-Allow-Headers", "").lower()
    assert "idempotency-key" in allow_headers, (
        f"Access-Control-Allow-Headers must include idempotency-key; got: {allow_headers!r}"
    )
    # Sanity: the default headers still pass through.
    assert "x-csrftoken" in allow_headers
    assert "content-type" in allow_headers

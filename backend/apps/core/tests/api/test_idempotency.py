"""API tests for the @idempotent view decorator.

Uses a tiny stub view to test the decorator in isolation, against the real
idempotency_keys table in the test DB.

owner_id is now INT (post-0002_auth_fk.sql) matching auth_user.id.
The stub inserts a real auth_user row before creating idempotency_keys rows
so the FK constraint is satisfied.

force_authenticate() is used so DRF's Request wrapper picks up the fake user
instead of running its own auth pipeline.

See SPEC §2.6 for the endpoint idempotency contract.
"""

from __future__ import annotations

import itertools
import json
import os
import types

import psycopg
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_uid_counter = itertools.count(start=9000)


def _db_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _clean_idempotency_keys() -> None:
    """Truncate idempotency_keys between test cases for isolation."""
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        conn.execute("TRUNCATE idempotency_keys")


def _make_auth_user(uid: int) -> None:
    """Insert a minimal auth_user row so the idempotency FK is satisfied."""
    email = f"stub_{uid}@test.invalid"
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO auth_user
                (id, username, email, password,
                 is_superuser, is_staff, is_active,
                 first_name, last_name, date_joined)
            VALUES (%s, %s, %s, 'unusable!', false, false, true, '', '', NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            (uid, email, email),
        )


def _fake_user(uid: int | None = None) -> types.SimpleNamespace:
    """Minimal stand-in for request.user — the decorator only reads .id."""
    resolved = uid if uid is not None else next(_uid_counter)
    _make_auth_user(resolved)
    return types.SimpleNamespace(id=resolved)


# Counter for tracking handler invocations.
_call_counter: dict[str, int] = {"count": 0}


def _make_stub_view(endpoint: str):
    """Return a DRF view decorated with @idempotent for the given endpoint."""
    from apps.core.idempotency import idempotent
    from rest_framework.views import APIView

    class StubView(APIView):
        authentication_classes = []
        permission_classes = []

        @idempotent(endpoint=endpoint)
        def post(self, request):
            _call_counter["count"] += 1
            return Response({"result": "created"}, status=201)

    return StubView.as_view()


def _render(response: Response) -> dict:
    """Force-render a DRF Response and parse the JSON body."""
    response.accepted_renderer = JSONRenderer()
    response.accepted_media_type = "application/json"
    response.renderer_context = {}
    response.render()
    return json.loads(response.content)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_idempotent_first_call_executes_handler():
    """First POST with an Idempotency-Key runs the handler and caches the result."""
    _call_counter["count"] = 0
    _clean_idempotency_keys()

    user = _fake_user()
    factory = APIRequestFactory()
    request = factory.post("/", HTTP_IDEMPOTENCY_KEY="key-first")
    force_authenticate(request, user=user)

    view = _make_stub_view("test.first_call")
    response = view(request)

    assert response.status_code == 201
    assert _call_counter["count"] == 1
    _clean_idempotency_keys()


def test_idempotent_second_call_returns_cached_body():
    """Second POST with the same key skips the handler; counter stays at 1."""
    _call_counter["count"] = 0
    _clean_idempotency_keys()

    user = _fake_user()
    factory = APIRequestFactory()

    view = _make_stub_view("test.cache_hit")

    # First call — handler runs, response cached
    req1 = factory.post("/", HTTP_IDEMPOTENCY_KEY="key-idempotent")
    force_authenticate(req1, user=user)
    resp1 = view(req1)
    assert resp1.status_code == 201
    assert _call_counter["count"] == 1

    # Second call — same key, handler must NOT run
    req2 = factory.post("/", HTTP_IDEMPOTENCY_KEY="key-idempotent")
    force_authenticate(req2, user=user)
    resp2 = view(req2)

    assert resp2.status_code == 201
    assert _call_counter["count"] == 1, "Handler must not have been called again"
    _clean_idempotency_keys()


def test_idempotent_missing_header_returns_400():
    """Request without Idempotency-Key header returns 400 ValidationError."""
    _clean_idempotency_keys()

    user = _fake_user()
    factory = APIRequestFactory()
    request = factory.post("/")  # No HTTP_IDEMPOTENCY_KEY header
    force_authenticate(request, user=user)

    view = _make_stub_view("test.missing_header")
    response = view(request)

    assert response.status_code == 400
    body = _render(response)
    assert body["error"] == "ValidationError"
    assert "Idempotency-Key" in body["detail"]
    _clean_idempotency_keys()


def test_idempotent_per_owner_isolation():
    """Owner A's cached row is NOT visible to owner B — cache miss for B."""
    _call_counter["count"] = 0
    _clean_idempotency_keys()

    user_a = _fake_user()
    user_b = _fake_user()  # Different UUID → different owner
    factory = APIRequestFactory()

    view = _make_stub_view("test.owner_isolation")

    # Owner A posts first — handler runs (count=1)
    req_a = factory.post("/", HTTP_IDEMPOTENCY_KEY="shared-key")
    force_authenticate(req_a, user=user_a)
    resp_a = view(req_a)
    assert resp_a.status_code == 201
    assert _call_counter["count"] == 1

    # Owner B posts with the same key — cache miss → handler runs again (count=2)
    req_b = factory.post("/", HTTP_IDEMPOTENCY_KEY="shared-key")
    force_authenticate(req_b, user=user_b)
    resp_b = view(req_b)
    assert resp_b.status_code == 201
    assert _call_counter["count"] == 2, (
        "Handler must have run for owner B (different owner — cache miss)"
    )
    _clean_idempotency_keys()

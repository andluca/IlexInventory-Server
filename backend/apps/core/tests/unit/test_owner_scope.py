"""Unit tests for apps.core.owner_scope.@scoped decorator.

The decorator is a runtime guard: it raises ValueError if `owner_id` is missing
or None in the `params` dict. It does NOT rewrite SQL — the query function owns
the WHERE clause.
"""

from __future__ import annotations

import uuid

import pytest


def test_scoped_raises_on_empty_params():
    from apps.core.owner_scope import scoped

    @scoped
    def query(params: dict) -> str:
        return "ok"

    with pytest.raises(ValueError, match="owner_id"):
        query(params={})


def test_scoped_raises_on_none_owner_id():
    from apps.core.owner_scope import scoped

    @scoped
    def query(params: dict) -> str:
        return "ok"

    with pytest.raises(ValueError, match="owner_id"):
        query(params={"owner_id": None})


def test_scoped_passes_through_with_valid_owner_id():
    from apps.core.owner_scope import scoped

    owner = uuid.uuid4()

    @scoped
    def query(params: dict) -> str:
        return f"owner={params['owner_id']}"

    result = query(params={"owner_id": owner, "extra": "value"})
    assert result == f"owner={owner}"


def test_scoped_keyword_call():
    """Decorator works when params is passed as a keyword argument."""
    from apps.core.owner_scope import scoped

    owner = uuid.uuid4()

    @scoped
    def query(params: dict) -> list:
        return [params["owner_id"]]

    result = query(params={"owner_id": owner})
    assert result == [owner]


def test_scoped_positional_call():
    """Decorator works when params is passed as the first positional argument."""
    from apps.core.owner_scope import scoped

    owner = uuid.uuid4()

    @scoped
    def query(params: dict) -> list:
        return [params["owner_id"]]

    result = query({"owner_id": owner})
    assert result == [owner]


def test_scoped_preserves_function_name():
    from apps.core.owner_scope import scoped

    @scoped
    def my_query(params: dict) -> None:
        pass

    assert my_query.__name__ == "my_query"

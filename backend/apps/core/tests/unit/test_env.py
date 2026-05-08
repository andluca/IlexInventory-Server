"""Unit tests for settings._env helpers.

These tests run without a DB; they patch os.environ directly.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured


def test_env_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("_TEST_REQUIRED", "hello")
    from settings._env import env

    assert env("_TEST_REQUIRED") == "hello"


def test_env_raises_on_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("_TEST_MISSING", raising=False)
    from settings._env import env

    with pytest.raises(ImproperlyConfigured):
        env("_TEST_MISSING")


def test_env_optional_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("_TEST_OPT", raising=False)
    from settings._env import env_optional

    assert env_optional("_TEST_OPT", "fallback") == "fallback"


def test_env_optional_returns_value_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("_TEST_OPT2", "present")
    from settings._env import env_optional

    assert env_optional("_TEST_OPT2", "fallback") == "present"


def test_env_csv_splits_on_comma(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("_TEST_CSV", "a,b,c")
    from settings._env import env_csv

    assert env_csv("_TEST_CSV") == ["a", "b", "c"]


def test_env_csv_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("_TEST_CSV2", "a, b ,c")
    from settings._env import env_csv

    assert env_csv("_TEST_CSV2") == ["a", "b", "c"]


def test_env_csv_uses_default_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("_TEST_CSV3", raising=False)
    from settings._env import env_csv

    assert env_csv("_TEST_CSV3", default=["x"]) == ["x"]


def test_env_csv_raises_when_missing_and_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("_TEST_CSV4", raising=False)
    from settings._env import env_csv

    with pytest.raises(ImproperlyConfigured):
        env_csv("_TEST_CSV4")


def test_env_bool_true_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    from settings._env import env_bool

    for val in ("true", "True", "TRUE", "1"):
        monkeypatch.setenv("_TEST_BOOL", val)
        assert env_bool("_TEST_BOOL", default=False) is True, f"expected True for {val!r}"


def test_env_bool_false_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    from settings._env import env_bool

    for val in ("false", "False", "FALSE", "0"):
        monkeypatch.setenv("_TEST_BOOL", val)
        assert env_bool("_TEST_BOOL", default=True) is False, f"expected False for {val!r}"


def test_env_bool_uses_default_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("_TEST_BOOL_MISSING", raising=False)
    from settings._env import env_bool

    assert env_bool("_TEST_BOOL_MISSING", default=True) is True

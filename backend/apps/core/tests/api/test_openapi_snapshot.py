"""API test: backend/openapi.json exists, is valid JSON, and has correct metadata."""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings


def _snapshot_path() -> Path:
    # __file__ = .../backend/apps/core/tests/api/test_openapi_snapshot.py
    # parents[4] = .../backend/
    # openapi.json lives at .../backend/openapi.json
    return Path(__file__).parents[4] / "openapi.json"


def test_snapshot_file_exists():
    path = _snapshot_path()
    assert path.exists(), f"backend/openapi.json not found at {path}"


def test_snapshot_parses_as_json():
    path = _snapshot_path()
    content = path.read_text(encoding="utf-8")
    schema = json.loads(content)
    assert isinstance(schema, dict)


def test_snapshot_openapi_version_is_31():
    path = _snapshot_path()
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema.get("openapi") == "3.1.0", (
        f"Expected openapi=3.1.0, got {schema.get('openapi')!r}"
    )


def test_snapshot_info_version_matches_settings():
    path = _snapshot_path()
    schema = json.loads(path.read_text(encoding="utf-8"))
    expected = settings.SPECTACULAR_SETTINGS["VERSION"]
    actual = schema.get("info", {}).get("version")
    assert actual == expected, (
        f"info.version mismatch: snapshot={actual!r}, settings={expected!r}"
    )

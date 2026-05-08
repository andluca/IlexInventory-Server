"""Test: check_openapi_drift.sh exits 0 and prints 'check-openapi-drift: OK'
when the committed snapshot matches the regenerated schema.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_SCRIPT_PATH = Path(__file__).parents[5] / "scripts" / "check_openapi_drift.sh"


def test_drift_script_exits_0_when_snapshot_is_current():
    assert _SCRIPT_PATH.exists(), f"drift gate script not found at {_SCRIPT_PATH}"

    result = subprocess.run(
        [str(_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        cwd=str(_SCRIPT_PATH.parent.parent),  # repo root
    )
    assert result.returncode == 0, (
        f"check_openapi_drift.sh exited {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "check-openapi-drift: OK" in result.stdout, (
        f"Expected 'check-openapi-drift: OK' in stdout.\nstdout: {result.stdout}"
    )

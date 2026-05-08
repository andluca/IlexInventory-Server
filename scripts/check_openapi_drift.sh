#!/usr/bin/env bash
# check_openapi_drift.sh — CI gate for OpenAPI snapshot drift.
#
# Regenerates the OpenAPI schema to a temp file and diffs it against the
# committed backend/openapi.json.  Exits 0 if identical; exits 1 and prints
# the unified diff otherwise.
#
# Usage:
#   ./scripts/check_openapi_drift.sh              # from repo root
#   make check-openapi-drift                      # via Makefile target (if wired)
#
# Remediation on failure:
#   python manage.py spectacular --format openapi-json \
#       --file backend/openapi.json 2>/dev/null

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT="$REPO_ROOT/backend/openapi.json"
TMP_FILE="$(mktemp /tmp/openapi.regen.XXXXXX.json)"

# Clean up the temp file on any exit.
trap 'rm -f "$TMP_FILE"' EXIT

# Regenerate the schema into the temp file.
cd "$REPO_ROOT"
uv run python manage.py spectacular --format openapi-json --file "$TMP_FILE" 2>/dev/null

# Compare.
if diff -u "$SNAPSHOT" "$TMP_FILE" > /dev/null 2>&1; then
    echo "check-openapi-drift: OK"
    exit 0
fi

echo "check-openapi-drift: FAIL — committed openapi.json is stale. Re-run:"
echo "  python manage.py spectacular --format openapi-json --file backend/openapi.json 2>/dev/null"
echo ""
diff -u "$SNAPSHOT" "$TMP_FILE" || true
exit 1

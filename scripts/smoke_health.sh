#!/bin/sh
# Smoke test: poll /api/v1/health until 200 or timeout.
# Mirrors the style of scripts/check_no_orm.sh.
set -euo pipefail

URL="${SMOKE_URL:-http://localhost:8000/api/v1/health}"
TIMEOUT="${SMOKE_TIMEOUT:-30}"

elapsed=0
last_body=""

while [ "$elapsed" -lt "$TIMEOUT" ]; do
    last_body=$(curl -fsS "$URL" 2>/dev/null) && {
        echo "smoke-health: OK — /api/v1/health returned 200 with ${last_body}"
        exit 0
    }
    sleep 1
    elapsed=$((elapsed + 1))
done

echo "smoke-health: FAIL — /api/v1/health did not return 200 within ${TIMEOUT}s"
echo "last response body: ${last_body}"
exit 1

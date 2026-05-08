#!/usr/bin/env bash
# check_no_orm.sh — CI gate for BE-D14 ORM allowlist.
#
# Greps backend/apps/ for imports of django.db.models or django.contrib.auth.
# The ONLY allowed match is in backend/apps/core/auth.py.
#
# Exits 0 if clean; exits 1 and prints violations otherwise.
#
# Usage:
#   ./scripts/check_no_orm.sh              # from repo root
#   make check-no-orm                      # via Makefile target

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS_DIR="$REPO_ROOT/backend/apps"
ALLOWLIST_FILE="$REPO_ROOT/backend/apps/core/auth.py"

# Pattern: lines that start an import from the guarded namespaces.
PATTERN='^\s*from django\.db\.models\b|^\s*from django\.contrib\.auth\b'

violations=()

while IFS= read -r -d '' py_file; do
    # Skip the allowlist file.
    if [ "$(realpath "$py_file")" = "$(realpath "$ALLOWLIST_FILE")" ]; then
        continue
    fi
    # Skip __pycache__ directories.
    if echo "$py_file" | grep -q '__pycache__'; then
        continue
    fi

    # Grep for violations; capture line numbers.
    while IFS= read -r match; do
        rel="${py_file#"$REPO_ROOT/"}"
        violations+=("$rel: $match")
    done < <(grep -nP "$PATTERN" "$py_file" 2>/dev/null || true)

done < <(find "$APPS_DIR" -name '*.py' -print0)

if [ ${#violations[@]} -eq 0 ]; then
    echo "check-no-orm: OK — only apps/core/auth.py imports from django.contrib.auth"
    exit 0
fi

echo "check-no-orm: FAIL — ORM import found outside the allowlist file (apps/core/auth.py):"
for v in "${violations[@]}"; do
    echo "  $v"
done
exit 1

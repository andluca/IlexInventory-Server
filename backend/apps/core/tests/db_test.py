"""
db_test — declarative DB state for tests.

Python/psycopg port of epic-test/db-test (TypeScript/Drizzle):
https://github.com/.../epic-test (../../../../epic-test in this workspace)

Pattern:

    pre_db(conn, {"products": [{"id": "P-1", "owner_id": "U-A", ...}], ...})
    # ... run code under test ...
    post_db(conn, {"products": [{"id": "P-1", "name": "Cold Brew"}], ...})

`pre_db` wipes target tables and inserts the given rows.
`post_db` reads the target tables, projects to the keys present in expected,
and asserts equality as multisets (order-independent, duplicates respected).

Transactions are caller-managed; nothing here commits. Test fixtures (e.g.
`backend/conftest.py`'s session-scoped `db` fixture) own commit/rollback.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

State = dict[str, list[dict[str, Any]]]


# ---------- pre_db ----------

def pre_db(
    conn,
    state: State,
    *,
    wipe: bool = True,
    only: list[str] | None = None,
) -> None:
    """Set DB into a known state. Wipes target tables, then inserts rows.

    - `TRUNCATE ... RESTART IDENTITY CASCADE` clears target tables and any
      child rows that reference them via FK.
    - `SET CONSTRAINTS ALL DEFERRED` lets inserts land in any order; the
      trailing `SET CONSTRAINTS ALL IMMEDIATE` forces FK checks to fire
      before this function returns, so violations surface here, not at
      the caller's later commit.
    - Caller manages the transaction. Nothing here commits. **On any error
      the connection's transaction is left in an aborted state — the caller
      must `rollback()` before reusing the connection.**
    """
    target_tables = only if only is not None else list(state.keys())
    if not target_tables:
        return

    with conn.cursor() as cur:
        if wipe:
            tables_sql = ", ".join(_quote_ident(t) for t in target_tables)
            cur.execute(f"TRUNCATE {tables_sql} RESTART IDENTITY CASCADE")

        cur.execute("SET CONSTRAINTS ALL DEFERRED")

        for table in target_tables:
            rows = state.get(table, [])
            if not rows:
                continue
            # Build SQL per row, not once from rows[0], so each row's own
            # keys drive its INSERT and heterogeneous shapes don't drop data.
            for row in rows:
                keys = list(row.keys())
                cols_sql = ", ".join(_quote_ident(k) for k in keys)
                placeholders = ", ".join(["%s"] * len(keys))
                insert_sql = (
                    f"INSERT INTO {_quote_ident(table)} "
                    f"({cols_sql}) VALUES ({placeholders})"
                )
                cur.execute(insert_sql, tuple(row[k] for k in keys))

        # Force deferred FK checks to fire now so any violation surfaces here,
        # not at the caller's commit further down the line.
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")


# ---------- post_db ----------

def post_db(
    conn,
    expected: State,
    *,
    only: list[str] | None = None,
    allow_extra_rows: bool = False,
    loose: bool = False,
) -> None:
    """Assert DB equals the expected state.

    For each target table:
      - Project actual rows to the union of keys present in expected rows
        (subset-friendly: only check the columns the test cares about).
      - Compare as multisets (order-independent, duplicates respected).
      - On mismatch, raise AssertionError with a per-table diff.

    Options match epic-test/db-test:
      - `only`: target a subset of tables.
      - `allow_extra_rows`: tolerate rows in DB beyond the expected set.
      - `loose`: coerce values via `str()` (datetime → ISO) before compare.

    **On any error (assertion failure or SQL error) the connection's
    transaction is left in an aborted state — the caller must `rollback()`
    before reusing the connection.**
    """
    target_tables = only if only is not None else list(expected.keys())
    errors: list[str] = []

    with conn.cursor() as cur:
        for table in target_tables:
            expected_rows = expected.get(table, [])
            keys = sorted({k for r in expected_rows for k in r.keys()})

            if not keys:
                # Empty expected (no rows / no keys to project). Verify the
                # table is empty unless extra rows are allowed.
                cur.execute(f"SELECT COUNT(*) FROM {_quote_ident(table)}")
                actual_count = cur.fetchone()[0]
                if actual_count > 0 and not allow_extra_rows:
                    errors.append(
                        f"\nTable: {table}\n"
                        f"Expected count: 0, Actual count: {actual_count}"
                    )
                continue

            cols_sql = ", ".join(_quote_ident(k) for k in keys)
            cur.execute(f"SELECT {cols_sql} FROM {_quote_ident(table)}")
            actual_rows = [dict(zip(keys, row)) for row in cur.fetchall()]

            norm_expected = [_normalize_row(r, keys, loose) for r in expected_rows]
            norm_actual = [_normalize_row(r, keys, loose) for r in actual_rows]

            missing, extra = _diff_multisets(norm_expected, norm_actual)
            table_passes = not missing and (allow_extra_rows or not extra)
            if not table_passes:
                errors.append(_format_diff(
                    table,
                    expected_count=len(norm_expected),
                    actual_count=len(norm_actual),
                    missing=missing,
                    extra=extra,
                    allow_extra_rows=allow_extra_rows,
                ))

    if errors:
        raise AssertionError("PostDB assertion failed:" + "".join(errors))


# ---------- file variants ----------

def pre_db_from_file(conn, file_path: str, **opts) -> None:
    with open(file_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    pre_db(conn, state, **opts)


def post_db_from_file(conn, file_path: str, **opts) -> None:
    with open(file_path, "r", encoding="utf-8") as f:
        expected = json.load(f)
    post_db(conn, expected, **opts)


# ---------- internals ----------

def _quote_ident(name: str) -> str:
    """Minimal identifier quoting (table/column names). Rejects anything that
    isn't alphanumeric or underscore — keeps SQL injection out of identifiers."""
    if not name or not name.replace("_", "").isalnum():
        raise ValueError(f"Invalid identifier: {name!r}")
    return f'"{name}"'


def _normalize_value(v: Any, loose: bool) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if loose:
        return None if v is None else str(v)
    return v


def _normalize_row(row: dict, keys: Iterable[str], loose: bool) -> dict:
    return {k: _normalize_value(row.get(k), loose) for k in keys}


def _stable_key(d: dict) -> str:
    return json.dumps(d, sort_keys=True, default=_json_default)


def _json_default(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _diff_multisets(
    expected: list[dict],
    actual: list[dict],
) -> tuple[list[dict], list[dict]]:
    e = Counter(_stable_key(r) for r in expected)
    a = Counter(_stable_key(r) for r in actual)
    missing = [json.loads(k) for k, n in (e - a).items() for _ in range(n)]
    extra = [json.loads(k) for k, n in (a - e).items() for _ in range(n)]
    return missing, extra


def _format_diff(
    table: str,
    *,
    expected_count: int,
    actual_count: int,
    missing: list[dict],
    extra: list[dict],
    allow_extra_rows: bool,
) -> str:
    lines = [
        f"\nTable: {table}",
        f"Expected count: {expected_count}, Actual count: {actual_count}",
    ]
    if missing:
        lines.append("Missing rows:")
        for r in missing:
            lines.append("  - " + json.dumps(r, sort_keys=True, default=_json_default))
    if extra and not allow_extra_rows:
        lines.append("Extra rows:")
        for r in extra:
            lines.append("  - " + json.dumps(r, sort_keys=True, default=_json_default))
    return "\n".join(lines)

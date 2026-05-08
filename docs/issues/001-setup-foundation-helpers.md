# 001 — Setup foundation helpers and 0001_init schema

## Overview

Lay the cross-cutting foundation every app depends on: the initial migration with Postgres extensions and shared SQL helpers, plus the Python-side helpers in `apps/core/`. Nothing app-specific lands yet — this is the substrate.

**Scope:**
- `backend/migrations/0001_init.sql` — `pgcrypto` extension, UUIDv7 SQL function, owner-scope SQL helper if needed
- `apps/core/ids.py` — UUIDv7 Python generator (per BE-D5)
- `apps/core/owner_scope.py` — `@scoped` decorator that injects `owner_id = %(owner_id)s` into queries (BE-D4)
- `apps/core/errors.py` — `DomainError` base class + common subclasses (`NotFound`, `ValidationError`, `Conflict`)
- `apps/core/types.py` — shared dataclasses / TypedDicts placeholder
- Tests for each helper (unit + query layer for the SQL function)

**Reference:** SPEC §2.1, §2.2, §2.3, §2.4. BE-D4 (owner isolation), BE-D5 (UUIDv7).

**Depends on:** none — phases 1 (project setup) and 2 (test infrastructure) are already done.

# Project Status

Last updated: 2026-05-08

## Issues

- [x] 001-bootstrap-django-project.md - in_progress (2026-05-08T00:00:00)
- [ ] 002-setup-foundation-and-init-schema.md - pending
- [ ] 003-implement-auth-in-core.md - pending
- [ ] 004-implement-catalog-app.md - pending
- [ ] 005-implement-procurement-app.md - pending
- [ ] 006-implement-inventory-app.md - pending
- [ ] 007-implement-sales-app.md - pending
- [ ] 008-implement-financials-app.md - pending
- [ ] 009-add-csv-exports-and-indexes.md - pending
- [ ] 010-integrate-openapi-with-frontend.md - pending
- [ ] 011-setup-deploy-pipeline.md - pending

## Summary

Total: 11 issues
Completed: 0
In progress: 1
Pending: 10
Failed: 0

## Execution Log

(Entries added as issues are processed)

## Notes

### Pre-issue work already in `feat/foundation` (do not re-do)

- `pyproject.toml` with `psycopg[binary]`, `pytest`, `ruff` (Django + DRF still need to be added in Issue 001)
- `backend/conftest.py` — session-scoped Postgres connection fixture
- `backend/apps/core/tests/db_test.py` — `pre_db` / `post_db` test pattern, 28/28 green
- Postgres docker-compose for local dev
- `.env` template
- Claude skills (`tdd`, `ilex-discipline`) and agents (`planner`, `executor`) and SDD commands

### Dependency chain

Critical path is linear: `001 → 002 → 003 → 004 → 005 → 006 → 007 → 008 → 009 → 010 → 011`. Schema clusters land in feature issues alongside their app code rather than as a separate schema phase, so each issue ships an end-to-end vertical (schema → query → service → API → tests).

### Phase 12 (Agent) is out of v1 MVP

The agent endpoint (`/agent/chat`) and read-only DB role are spec'd in SPEC.md §3.8 but explicitly Phase 3 per `product.md`. Not in this issue list. Returns as Issue 012+ when v1 ships.

### Schema slicing reminder

Migrations are sliced by domain cluster per `architecture.md`:
- 0001 — extensions + UUIDv7 fn (Issue 002)
- 0002 — catalog (Issue 004)
- 0003 — procurement (Issue 005)
- 0004 — inventory (Issue 006)
- 0005 — sales (Issue 007)
- 0006 — views (split across Issues 006 and 008)
- 0007 — indexes (Issue 009)

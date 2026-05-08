# Project Status

Last updated: 2026-05-08 (Phase 3 agent issues added: ILEX-012 to ILEX-015)

## Issues

- [x] 001-bootstrap-django-project.md - completed (2026-05-08T00:00:00)
- [x] 002-setup-foundation-and-init-schema.md - completed (2026-05-08T00:05:00)
- [x] 003-implement-auth-in-core.md - completed (2026-05-08T01:00:00)
- [ ] 004-implement-catalog-app.md - pending
- [ ] 005-implement-procurement-app.md - pending
- [ ] 006-implement-inventory-app.md - pending
- [ ] 007-implement-sales-app.md - pending
- [ ] 008-implement-financials-app.md - pending
- [ ] 009-add-csv-exports-and-indexes.md - pending
- [ ] 010-integrate-openapi-with-frontend.md - pending
- [ ] 011-setup-deploy-pipeline.md - pending
- [ ] 012-setup-agent-foundation-and-readonly-role.md - pending (Phase 3)
- [ ] 013-implement-chat-endpoint-and-query-mode.md - pending (Phase 3)
- [ ] 014-implement-draft-mode-and-domain-skills.md - pending (Phase 3)
- [ ] 015-add-onboarding-skill-and-empty-state-integration.md - pending (Phase 3)

## Summary

Total: 15 issues
Completed: 3
In progress: 0
Pending: 12
Failed: 0

## Execution Log

- 2026-05-08: ILEX-001 completed — Django 5.1 + DRF + drf-spectacular skeleton bootstrapped; `GET /api/v1/health` (200/503) and `GET /api/v1/openapi.json` (OpenAPI 3.1.0) live; 48/48 tests green.
- 2026-05-08: ILEX-002 completed — Foundation helpers + 0001_init schema; 34 new tests; 82/82 green.
- 2026-05-08: ILEX-003 completed — Auth (signup/login/logout/me) + FK migration + ORM allowlist; 28 new tests; 110/110 green.

## Notes

### Pre-issue work already in `feat/foundation` (do not re-do)

- `pyproject.toml` with `psycopg[binary]`, `pytest`, `ruff` (Django + DRF still need to be added in Issue 001)
- `backend/conftest.py` — session-scoped Postgres connection fixture
- `backend/apps/core/tests/db_test.py` — `pre_db` / `post_db` test pattern, 28/28 green
- Postgres docker-compose for local dev
- `.env` template
- Claude skills (`tdd`, `ilex-discipline`) and agents (`planner`, `executor`) and SDD commands

### Dependency chain

Critical path is linear: `001 → 002 → 003 → 004 → 005 → 006 → 007 → 008 → 009 → 010 → 011 → 012 → 013 → 014 → 015`. Schema clusters land in feature issues alongside their app code rather than as a separate schema phase, so each issue ships an end-to-end vertical (schema → query → service → API → tests). Issues 012–015 are Phase 3 (agent) and gated on v1 MVP completion at 011.

### Phase 3 (Agent) is out of v1 MVP

The agent endpoint (`/agent/chat`) and read-only DB role are spec'd in [`docs/specs/agent.md`](../specs/agent.md) with a runtime walkthrough in [`docs/agent.md`](../agent.md). Issues 012–015 cover the four-step build (foundation → chat+query → draft → onboarding). They depend on the v1 MVP chain (002–011) being green first because the agent rewrites existing `v_*` views to add session-GUC owner filtering, and those views must exist before being rewritten.

### Schema slicing reminder

Migrations are sliced by domain cluster per `architecture.md`:
- 0001 — extensions + UUIDv7 fn (Issue 002)
- 0002 — catalog (Issue 004)
- 0003 — procurement (Issue 005)
- 0004 — inventory (Issue 006)
- 0005 — sales (Issue 007)
- 0006 — views (split across Issues 006 and 008)
- 0007 — indexes (Issue 009)
- 0008 — agent role + view rewrites for session-GUC owner filter (Issue 012)

# Project Status

Last updated: 2026-05-08T21:00:00Z (ILEX-010 completed)

## Issues

- [x] 001-bootstrap-django-project.md - completed (2026-05-08T00:00:00)
- [x] 002-setup-foundation-and-init-schema.md - completed (2026-05-08T00:05:00)
- [x] 003-implement-auth-in-core.md - completed (2026-05-08T01:00:00)
- [x] 004-implement-catalog-app.md - completed (2026-05-08T09:30:00Z)
- [x] 005-implement-procurement-app.md - completed (2026-05-08T12:02:20Z)
- [ ] 006-implement-inventory-app.md - in_progress (2026-05-08T13:00:00Z)
- [ ] 007-implement-sales-app.md - in_progress (2026-05-08T14:00:00Z)
- [x] 008-implement-financials-app.md - completed (2026-05-08T16:00:00Z)
- [x] 009-add-csv-exports-and-indexes.md - completed (2026-05-08T18:30:00Z)
- [x] 010-integrate-openapi-with-frontend.md - completed (2026-05-08T21:00:00Z)
- [ ] 011-setup-deploy-pipeline.md - in_progress (2026-05-08T22:00:00Z)
- [ ] 012-setup-agent-foundation-and-readonly-role.md - pending (Phase 3)
- [ ] 013-implement-chat-endpoint-and-query-mode.md - pending (Phase 3)
- [ ] 014-implement-draft-mode-and-domain-skills.md - pending (Phase 3)
- [ ] 015-add-onboarding-skill-and-empty-state-integration.md - pending (Phase 3)

## Summary

Total: 15 issues
Completed: 10
In progress: 0
Pending: 5
Failed: 0

## Execution Log

- 2026-05-08: ILEX-001 completed — Django 5.1 + DRF + drf-spectacular skeleton bootstrapped; `GET /api/v1/health` (200/503) and `GET /api/v1/openapi.json` (OpenAPI 3.1.0) live; 48/48 tests green.
- 2026-05-08: ILEX-002 completed — Foundation helpers + 0001_init schema; 34 new tests; 82/82 green.
- 2026-05-08: ILEX-003 completed — Auth (signup/login/logout/me) + FK migration + ORM allowlist; 28 new tests; 110/110 green.
- 2026-05-08: ILEX-004 planned — `0003_catalog.sql` + apps/catalog vertical (7 endpoints, CSV import) plotted; SKU-lock seam deferred to Issue 006 via stubbed `count_batches_for_product`; on-hand projection in list endpoint deferred to Issue 008.
- 2026-05-08: ILEX-004 completed — `0003_catalog.sql` + full apps/catalog vertical; 72 new tests (8 query, 17 service, 23 unit, 24 api); 186/186 total green; all gates clean.
- 2026-05-08T08:55Z: post-ILEX-004 cleanup — discipline rules tightened in `.claude/skills/{ilex-discipline,tdd}/SKILL.md` (no function-local imports outside `tests/`; no implementation-coupled tests). Hoisted 22 function-local imports across `apps/{core,catalog}/` to module top, hoisted function-local imports across 18 test files. Deleted `tests/unit/test_csv_parser.py` (8 tests on `_parse_csv_bytes`/`_validate_csv_row` private helpers); BOM/CRLF/blank-SKU coverage relocated to `tests/service/test_import_products_csv.py` as behavioral cases. Deleted 3 service tests that monkey-patched `count_batches_for_product` — "with batches" coverage deferred to ILEX-006 where `batches` table exists. 178/178 green.
- 2026-05-08T09:45Z: ILEX-005 planned — `0004_procurement.sql` (purchase_orders + purchase_order_lines, composite FKs to products + auth_user, status `draft|received` CHECK, money/qty `numeric(14,4)` with positivity CHECKs) + apps/procurement vertical (6 endpoints, draft CRUD, receive). Receive's batch + movement creation deferred to ILEX-006 via a real `apps.inventory.services.create_receipt_batches` stub that ships in this issue (module-top import, no monkey-patching, behavioral tests only). Migration filename is `0004_procurement.sql` not `0003_procurement.sql` (drift since ILEX-004 took 0003 for catalog).
- 2026-05-08T12:02Z: ILEX-005 completed — `0004_procurement.sql` + apps/procurement vertical (6 endpoints) + apps/inventory stub; 84 new tests (procurement query/service/api/unit + inventory unit); 262/262 total green. One stray function-local import in `tests/unit/test_serializers.py` hoisted on completion. Receive ledger writes still deferred to ILEX-006.
- 2026-05-08T12:30Z: ILEX-006 planned — `0005_inventory.sql` (batches + stock_movements + append-only triggers + sign/notes CHECKs) + `0006_views.sql` (v_stock_by_batch + v_expiring_soon) + apps/inventory full vertical (8 of 9 endpoints; recall-report endpoint and v_recall_report view deferred to ILEX-007 since they reference sales tables). Replaces `apps.inventory.services.create_receipt_batches` stub body (signature unchanged so procurement keeps working) and `apps.catalog.queries.products.count_batches_for_product` stub body (real owner-scoped count). Restores 3 catalog service tests deleted in ILEX-004 cleanup as proper behavioral tests using real `batches` seed rows (no monkey-patches). Migration filename drift: `0005_inventory.sql` not `0004_inventory.sql` (procurement took 0004).
- 2026-05-08T16:00Z: ILEX-008 completed — `0008_financials.sql` (v_margin_by_product view, SO date-range index) + apps/financials full read-only vertical (2 endpoints); 16 new tests (3 query, 3 unit, 6 api dashboard, 4 api margin-list); 432/432 total green. `apps/core/pagination.py` extended with `encode_decimal_cursor`/`decode_decimal_cursor` for (Decimal, UUID) cursor pairs. `_EXPECTED_MIGRATIONS` bumped to 8.
- 2026-05-08T18:30Z: ILEX-009 completed — `0009_indexes.sql` (sm_owner_batch_created_idx + so_owner_status_created_idx); `apps/core/csv_export.py` (stream_csv, format_decimal, format_datetime, format_date); `GET /batches/{id}/recall-report` wired (JSON + CSV); `?format=csv` streaming export on /movements, /financials/margin, /financials/dashboard; REST_FRAMEWORK["URL_FORMAT_OVERRIDE"]=None added to settings to prevent DRF from intercepting the format param; 33 new tests; 465/465 total green. `_EXPECTED_MIGRATIONS` bumped to 9.
- 2026-05-08T21:00Z: ILEX-010 completed — `apps.sales` and `apps.financials` added to INSTALLED_APPS; `backend/apps/core/openapi.py` (inject_error_response_component hook, CSV_FORMAT_PARAMETER constant); SPECTACULAR_SETTINGS extended with POSTPROCESSING_HOOKS, SORT_OPERATION_PARAMETERS, COMPONENT_SPLIT_REQUEST, TAGS (7 entries), ENUM_NAME_OVERRIDES (MovementKind, ProductBaseUnit); `@extend_schema(tags=...)` backfilled on all 37 decorators across 6 apis.py files; CSV_FORMAT_PARAMETER wired on 4 endpoints (/movements, /batches/{batch_id}/recall-report, /financials/margin, /financials/dashboard); `backend/openapi.json` snapshot (OpenAPI 3.1.0, 26 paths, 7 tags, ErrorResponse component, cookieAuth); `.gitattributes` (openapi.json eol=lf); `scripts/check_openapi_drift.sh` (exit 0 = no drift, exit 1 = unified diff + remediation); 19 new tests (installed_apps×2, openapi_hook×6, openapi_tags×3, openapi_settings×3, openapi_snapshot×4, openapi_drift×1); 484/484 total green; pre-existing ruff violations cleaned (45 issues across 16 test files).

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
- 0009 — indexes (Issue 009)
- 0010 — agent role + view rewrites for session-GUC owner filter (Issue 012)

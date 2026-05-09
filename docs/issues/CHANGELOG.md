# Issue Changelog

Single source of truth for the issue ledger. Each issue's spec lives at `docs/issues/NNN-*.md`. This file maps the **what shipped** in commit-order; the issue files document the **why and how**.

## Status legend

| Marker | Meaning |
|---|---|
| ✅ done | Implemented, tests green, on `main` |
| ⏸ deferred | Specs locked, work postponed past v1 |

## v1 MVP — done (12)

| # | Title | Commit | Migration |
|---|---|---|---|
| [001](001-bootstrap-django-project.md) | Bootstrap Django project | [`38b411a`](../../commit/38b411a) | — |
| [002](002-setup-foundation-and-init-schema.md) | Foundation helpers + init schema | [`80c0b39`](../../commit/80c0b39) | `0001_init.sql` |
| [003](003-implement-auth-in-core.md) | Auth (signup/login/logout/me) | [`272eac0`](../../commit/272eac0) | `0002_auth_fk.sql` |
| [004](004-implement-catalog-app.md) | Catalog (products + CSV import) | [`88b3d3f`](../../commit/88b3d3f) | `0003_catalog.sql` |
| [005](005-implement-procurement-app.md) | Procurement (purchase orders) | [`7966403`](../../commit/7966403) | `0004_procurement.sql` |
| [006](006-implement-inventory-app.md) | Inventory (batches/movements/recall) | [`9188d58`](../../commit/9188d58) | `0005_inventory.sql`, `0006_views.sql` |
| [007](007-implement-sales-app.md) | Sales (FEFO commit + allocations + void) | [`1f41aa1`](../../commit/1f41aa1) | `0007_sales.sql` |
| [008](008-implement-financials-app.md) | Financials (margin + dashboard) | [`80f500e`](../../commit/80f500e) | `0008_financials.sql` |
| [009](009-add-csv-exports-and-indexes.md) | CSV exports + indexes | [`461bac1`](../../commit/461bac1) | `0009_indexes.sql` |
| [010](010-integrate-openapi-with-frontend.md) | OpenAPI tags/hooks + drift snapshot | [`3686576`](../../commit/3686576) | — |
| [011](011-setup-deploy-pipeline.md) | Deploy (Docker + Fly + GitHub Actions) | [`2b0e196`](../../commit/2b0e196) | — |
| [016](016-polish-and-fundament-phase-3.md) | Polish pass — bug fixes + DRY + docs | [`6fbb12d`](../../commit/6fbb12d), [`9be0d12`](../../commit/9be0d12), [`4d502aa`](../../commit/4d502aa) | — |

**v1 MVP gate:** 498 tests passing. Ruff clean. No-ORM gate clean. OpenAPI snapshot up to date.

## Phase 3 (agent) — deferred (4)

The "Ask Ilex" agent is specified in [`docs/specs/agent.md`](../specs/agent.md) and described in user-facing terms in [`docs/agent.md`](../agent.md). v1 ships without it; the schema commitments that make Phase 3 buildable later (read-only role substrate, owner-projecting views, append-only ledger, immutable allocations) all landed in v1.

| # | Title | Reactivation note |
|---|---|---|
| [012](012-setup-agent-foundation-and-readonly-role.md) | Agent foundation + `ilex_agent_ro` read-only role + view rewrites | Foundation issue. Ships `0010_agent_role.sql` (next migration number) plus the GUC-rewrite of `v_*` views. No app code yet. |
| [013](013-implement-chat-endpoint-and-query-mode.md) | `/agent/chat` endpoint + Query mode + SSE streaming | Wires `claude-agent-sdk` + `run_sql` tool against the read-only role. First skill file (`schema.md`). |
| [014](014-implement-draft-mode-and-domain-skills.md) | Draft mode (`draft_sales_order` tool) + domain skills | `cost-layers.md`, `fefo.md`, `recall-procedure.md`. Reuses `apps.sales.services.preview_sales_order` so FEFO matches the human path. |
| [015](015-add-onboarding-skill-and-empty-state-integration.md) | Onboarding skill + empty-state hooks | Final polish issue for Phase 3. |

To reactivate: open the issue file, update the dependency graph (012 will need `depends_on: [011, 016]`), and run through `/plan` then `/execute`.

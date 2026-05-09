---
id: ILEX-012
github_id: null
status: cancelled
assignee: null
state: Cancelled
type: item
depends_on: [ILEX-011]
---

# ILEX-012 Set up agent foundation and read-only role

Stand up the `apps/agent/` Django app skeleton and the database substrate the agent depends on: the read-only `ilex_agent_ro` Postgres role, the `ilex_agent` login user, and the view rewrites that swap `:owner_id` parameters for the `current_setting('app.current_owner_id')::uuid` session GUC. After this issue, no chat endpoint exists yet — but the safety perimeter is provable: a connection as `ilex_agent` can SELECT only from the five `v_*` views, sees only the rows for the GUC-set owner, and gets permission denied on every base table.

This is the foundation issue for the agent phase. It depends on all v1 MVP issues being green because the views (`v_stock_by_batch`, `v_stock_by_product`, `v_margin_by_product`, `v_expiring_batches`, `v_recall_report`) must exist and stabilize before being rewritten.

Reference: [`docs/specs/agent.md`](../../docs/specs/agent.md) §2.3 (database), §2.4 (architecture), §2.5 (config), §6 (validation gates), §8 D15–D16 (decisions).

# Notes

- The view rewrites replace existing `v_*` definitions in place — single source of truth. The human-facing selectors continue to pass `:owner_id` explicitly through `@scoped`; the GUC path is agent-only and additive (the views' `WHERE owner_id = current_setting(...)` clause requires the GUC to be set, but human calls also set it via `@scoped` if we want a unified path, or human selectors call alternate query functions that don't use the views — to be decided in `/plan`).
- New migration: `backend/migrations/0008_agent_role.sql` (the next number after the v1 chain ends at 0007).
- `AGENT_DB_URL` connects as `ilex_agent` (login user inheriting `ilex_agent_ro`). `AGENT_STATEMENT_TIMEOUT_MS`, `AGENT_ROW_CAP`, `AGENT_MODEL`, `CLAUDE_CODE_OAUTH_TOKEN` env vars wired into `backend/settings/base.py` per SPEC §2.9 + agent spec §2.5.
- Out of scope: the chat endpoint, SDK integration, tools, skills. Pure plumbing + DB safety.

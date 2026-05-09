# Spec: Ask Ilex Agent (Phase 3)

> **Status:** ⏸ Deferred — not implemented in v1. The v1 MVP shipped without the agent endpoint, but every schema commitment this spec depends on (read-only role substrate, owner-projecting `v_*` views, append-only `stock_movements`, immutable `sale_allocations`) is locked. To activate, follow the four-issue chain in [`docs/issues/012`](../issues/012-setup-agent-foundation-and-readonly-role.md) → [`015`](../issues/015-add-onboarding-skill-and-empty-state-integration.md).

## Summary

In-product chat agent for F&B brand owners. Three modes: **Query** (read-only SQL against allowlisted views), **Draft** (returns JSON payload, FE submits via the normal API on confirm — never a direct write), **Explain** (composes multiple SQL reads to surface causal narratives across the ledger and cost layers). Implemented with the **Claude Agent SDK** authenticated via a single shared `CLAUDE_CODE_OAUTH_TOKEN` (the dev's Claude Max subscription, take-home scope). One `run_sql` tool against the `ilex_agent_ro` Postgres role; the role has SELECT only on `v_*` views; views self-filter by owner via session GUC. 5s statement timeout, 1000-row cap, no rate limiting v1. SSE streaming. Stateless server — FE holds chat history. Skills loaded natively by the SDK from `apps/agent/skills/`.

Out of v1 MVP per [`status.md`](../issues/status.md). This spec exists so the schema (read-only role, view filter rewrite) and config (`AGENT_DB_URL`, `CLAUDE_CODE_OAUTH_TOKEN`) commitments stay locked in.

---

## 1. Goal

The agent is the narrative differentiator. The schema decisions — ledger (D1), immutable allocations + sale_void (D8), FEFO (D11), recall (D3), allowlisted views — exist partly to make **Explain mode** possible. The agent also covers the empty-state onboarding role per [`product.md`](../product.md) ("Want me to import from CSV?" on an empty product page).

Job-to-be-done:
- **Query**: "What's expiring next week?" → table inline.
- **Draft**: "Create an SO for Acme Café — 20 cans of Cold Brew." → proposed JSON payload; user reviews and confirms in the existing SO draft UI.
- **Explain**: "Why did Cold Brew margin drop 8% this month?" → walks cost layers and movement history, returns a causal narrative no static dashboard provides.

---

## 2. Foundation

### 2.1 Stack additions

- `claude-agent-sdk` (Python) — single new dependency; handles model calls, tool dispatch, skill loading, and streaming.
- New Django app: `apps/agent/`. Same four-layer discipline as every other app (D12).

### 2.2 Auth

- **Server-held `CLAUDE_CODE_OAUTH_TOKEN`** (env var) — single shared subscription for v1. The token never leaves the server; the FE sends only the user's session cookie.
- The chat endpoint requires the standard DRF `SessionAuthentication` (same as every other endpoint per SPEC §2.4). Per-user OAuth is out of v1.
- `owner_id` flows from `request.user.id` into the agent session; same `@scoped` discipline as the rest of the codebase.

### 2.3 Database

**New role** (provisioned in `0008_agent_role.sql`):

```sql
CREATE ROLE ilex_agent_ro NOLOGIN;
GRANT CONNECT ON DATABASE ilex TO ilex_agent_ro;
GRANT USAGE ON SCHEMA public TO ilex_agent_ro;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ilex_agent_ro;
GRANT SELECT ON v_stock_by_batch, v_stock_by_product,
                v_margin_by_product, v_expiring_batches,
                v_recall_report
  TO ilex_agent_ro;
```

A login user `ilex_agent` inherits the role; `AGENT_DB_URL` connects as that user.

**View rewrites** — every `v_*` view embeds owner filtering via a session GUC, replacing the per-call `:owner_id` parameter the human-facing selectors use:

```sql
CREATE VIEW v_stock_by_batch WITH (security_invoker = true) AS
  SELECT ...
  FROM batches b
  WHERE b.owner_id = current_setting('app.current_owner_id')::uuid;
```

The agent endpoint runs `SET LOCAL app.current_owner_id = '<owner>'` at the start of every request transaction. Cross-owner rows are invisible at the view level — the LLM cannot SELECT them. Human-facing selectors continue to pass `:owner_id` explicitly through `@scoped`; the GUC path is agent-only.

### 2.4 Architecture

```
apps/agent/
  apis.py            <- POST /agent/chat (SSE)
  services.py        <- session orchestration, tool dispatch
  selectors.py       <- (none v1; tools call selectors from other apps directly)
  queries/
    sql.py           <- run_sql implementation (parameter binding + row cap)
  tools/
    run_sql.py       <- SDK tool wrapping queries.sql.run_sql
    draft_sales_order.py  <- typed Python tool; calls sales.services.preview_sales_order
  skills/
    schema.md
    cost-layers.md
    fefo.md
    recall-procedure.md
    onboarding.md
  serializers.py     <- ChatRequest, ChatEvent (SSE event types)
  errors.py
  types.py
  urls.py
  tests/{unit,query,service,api}/
```

D12 layering holds: APIs → services → queries → schema. Tools are services that the SDK invokes; they sit alongside `services.py`.

### 2.5 Config

| Variable | Purpose | Example |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Shared OAuth token for Claude Agent SDK | (Claude Max OAuth token) |
| `AGENT_DB_URL` | `ilex_agent_ro` connection string | `postgresql://ilex_agent:...@host/ilex` |
| `AGENT_STATEMENT_TIMEOUT_MS` | Per-query timeout | `5000` |
| `AGENT_ROW_CAP` | Max rows per `run_sql` result | `1000` |
| `AGENT_MODEL` | Model passed to the SDK | `claude-sonnet-4-6` (default) |

App refuses to start if `CLAUDE_CODE_OAUTH_TOKEN` or `AGENT_DB_URL` is missing.

---

## 3. Endpoints

### 3.1 `POST /api/v1/agent/chat`

| Field | |
|---|---|
| **Auth** | DRF `SessionAuthentication` (same as the rest of the API) |
| **Content-Type** | `application/json` (request); `text/event-stream` (response) |
| **Idempotency** | Not idempotent — chat is inherently mutable per call |

**Request body:**

```json
{
  "message": "string",
  "history": [{ "role": "user|assistant", "content": "string" }],
  "context": {
    "route": "string",
    "filters": { "...arbitrary": "..." },
    "selected_ids": ["uuid", "..."]
  }
}
```

`history` is FE-held (stateless server). `context` is the FE's view state — the React app already knows what the user is looking at.

**Response (SSE):** `text/event-stream` with these event types (one event per `data:` line):

| Event | Payload | When |
|---|---|---|
| `text_delta` | `{ "delta": "string" }` | Token chunk from the LLM |
| `tool_call` | `{ "tool": "string", "input": {...} }` | LLM invokes a tool |
| `tool_result` | `{ "tool": "string", "ok": bool, "result": {...} \| "error": "string" }` | Tool returns |
| `draft` | `{ "kind": "sales_order \| ...", "payload": {...} }` | Draft mode produced a payload (FE renders confirm UI) |
| `done` | `{}` | Stream complete |
| `error` | `{ "code": "string", "detail": "string" }` | Fatal error mid-stream |

**Behavior:**

1. Validate session; resolve `owner_id` from `request.user`.
2. Open transaction on `AGENT_DB_URL`; `SET LOCAL app.current_owner_id = '<owner>'`; `SET LOCAL statement_timeout = '5s'`.
3. Open a Claude Agent SDK session with the user's message + `history` + `context` injected as system context. Skills auto-loaded from `apps/agent/skills/`.
4. Stream SDK events; relay to SSE per the table above. Tool calls execute against the open transaction.
5. On `done`, commit the (read-only) transaction and close the stream.

### 3.2 No other endpoints

Drafts are not a server resource — the agent emits a `draft` SSE event with a JSON payload, and the FE submits via the existing `POST /sales-orders` etc. on user confirm. This avoids a redundant `agent_drafts` table and keeps the agent's write path identical to the human's (D12).

---

## 4. Internal operations

### 4.1 Tool: `run_sql(query: str) -> { columns, rows, truncated }`

**Where:** `apps/agent/queries/sql.py`, registered as an SDK tool in `apps/agent/tools/run_sql.py`.

**Behavior:**
1. Execute `query` against the session-scoped agent connection (already inside a `SET LOCAL` transaction).
2. Fetch up to `AGENT_ROW_CAP + 1` rows.
3. Return `{ columns: [...], rows: [...up to cap], truncated: bool }`.
4. On Postgres error (permission denied, timeout, syntax), surface the error string back to the SDK as a tool error — the LLM retries.

**Safety:** the role has no write privileges and no access to base tables. View-level owner filter is enforced by GUC. No SQL parsing or validation in Python.

### 4.2 Tool: `draft_sales_order(customer_name, lines: [{product_id, quantity, sell_price}]) -> SOPayload`

**Where:** `apps/agent/tools/draft_sales_order.py`. Calls `sales.services.preview_sales_order(...)` (which already exists per SPEC §3.5 — the FEFO preview path) to validate FEFO feasibility.

**Returns:** the proposed SO JSON (matching `POST /sales-orders` request schema) plus the FEFO preview's allocations. Does not write to the database. The `draft` SSE event carries this payload; the FE renders it in the SO draft UI.

Other draft tools (`draft_recall`, `draft_purchase_order`) deferred until v1 demand surfaces. SO is the only one needed for the take-home narrative.

### 4.3 Skill files

Loaded natively by the Claude Agent SDK from `apps/agent/skills/`. One file per topic; the SDK handles intent-based loading and prompt caching.

| File | Content |
|---|---|
| `schema.md` | Each `v_*` view: columns, types, semantics, example queries. The LLM's schema documentation |
| `cost-layers.md` | How `batches.unit_cost` + immutable `sale_allocations` (D8) form FIFO cost layers; how to compute COGS deltas |
| `fefo.md` | FEFO eligibility predicate (recalled excluded D3, expired excluded D11); how to read `v_expiring_batches` |
| `recall-procedure.md` | D9 recall semantics: blocks future, reports past; voided SOs disappear from `v_recall_report` |
| `onboarding.md` | Empty-state copy; common first-time tasks (CSV import, first batch, first SO) |

---

## 5. Dependencies

- **Existing apps:** `core` (auth), `sales` (services for draft tool), all read views from `inventory`/`financials`.
- **New external:** `claude-agent-sdk` (Python SDK).
- **DB:** Postgres role + view rewrites land in a new migration `0008_agent_role.sql`. View self-filtering can either replace existing `v_*` definitions (preferred — single source of truth) or live as parallel `va_*` views. **Decision below: replace.**
- **Frontend (`IlexInventory-Web`):** consumes SSE; renders draft confirm UI. Out of this repo's scope.

---

## 6. Validation gates

| Gate | How |
|---|---|
| `ilex_agent_ro` cannot SELECT from base tables | Test: connect as `ilex_agent`, `SELECT * FROM batches` → permission denied |
| Views invisible across owners | Test: two owners with batches; `SET app.current_owner_id` to A; query view; assert no B rows |
| `run_sql` returns view rows | Query test against each `v_*` view via the agent role |
| `run_sql` rejects writes | Service test: `INSERT INTO batches ...` via `run_sql` → tool error surfaced |
| `statement_timeout` enforced | Service test: `SELECT pg_sleep(10)` via `run_sql` → tool error in <6s |
| Row cap | Service test: insert 1500 rows; `run_sql` returns 1000 + `truncated: true` |
| `draft_sales_order` produces valid SO payload | Service test: tool output round-trips through the real `POST /sales-orders` schema |
| Chat endpoint streams SSE | API test: `text/event-stream` content-type; events parse; `done` event terminates |
| Owner injection | API test: user A's session cannot make the agent see user B's data, even if user B's IDs are in `selected_ids` |

---

## 7. Implementation phases

| # | Issue | Description | Depends on |
|---|---|---|---|
| 12 | Agent foundation | `apps/agent/` skeleton + `0008_agent_role.sql` (role + view rewrites with `current_setting('app.current_owner_id')`) + `AGENT_DB_URL` wiring + DB-level safety gate tests | All v1 MVP issues (002–011) — needs the views to exist and stabilize first |
| 13 | Chat endpoint + Query mode | Claude Agent SDK integration; `POST /agent/chat` SSE view; `run_sql` tool; `schema.md` skill; Query-mode end-to-end test | 12 |
| 14 | Draft mode | `draft_sales_order` tool calling `sales.services.preview_sales_order`; `draft` SSE event; `cost-layers.md`, `fefo.md`, `recall-procedure.md` skills | 13 + ILEX-007 (sales) |
| 15 | Onboarding polish | `onboarding.md` skill; empty-state agent prompts; FE handoff for empty-state copy | 14 |

---

## 8. Decisions

These are new and slot into [`../decisions.md`](../decisions.md) as D15–D18 when the agent phase starts. Listed here to lock the design.

### D15 — SQL agent over per-view tools

The agent exposes **one** tool: `run_sql(query)`. The LLM writes SQL directly against the allowlisted `v_*` views. Safety is enforced at the DB layer (read-only role + view-level owner filter + statement timeout + row cap), not via Python validation.

Rejected: 5 typed per-view query tools. Adds boilerplate; restricts LLM expressiveness (no joins, no aggregates, no CTEs); duplicates the schema documentation that already lives in view DDL + skill file.

### D16 — Views self-filter by owner via session GUC

Every `v_*` view embeds `WHERE owner_id = current_setting('app.current_owner_id')::uuid`. The agent transaction sets the GUC at request start. Cross-owner rows are invisible at the view level; the LLM cannot bypass this.

Why a GUC and not a `:owner_id` parameter: `run_sql` accepts arbitrary SQL strings — there's no parameter list to inject `owner_id` into. Session GUCs are the standard Postgres pattern for this. Human-facing selectors keep using `@scoped` + parameterized `:owner_id` (no behavior change for existing code paths).

Rejected: row-level security policies on base tables (the agent role has no access to base tables, so RLS is moot). Application-level SQL parsing to inject WHERE clauses (fragile, redundant with view-level filter).

### D17 — Claude Agent SDK over bare Anthropic SDK

The agent uses `claude-agent-sdk` (Python). Authentication via `CLAUDE_CODE_OAUTH_TOKEN` requires the Claude Code auth surface — direct `api.anthropic.com` calls reject the OAuth token.

Side benefits: native skill loading, native tool dispatch, native streaming, prompt caching by default. Less code we own.

Rejected: bare `anthropic` SDK with hand-rolled skill prompt assembly + tool schemas. Would also require a separate billing path (API tokens) instead of the user's Claude Max subscription.

### D18 — Single shared `CLAUDE_CODE_OAUTH_TOKEN` v1; no rate limiting

Server holds one OAuth token (the dev's). Anthropic's account-level rate limits are the only cap; the server tracks no per-owner usage. Take-home scope.

Rejected: per-user OAuth flow (extra surface area, no v1 benefit). Per-owner daily token cap with `agent_usage_daily` table (token cost is borne by the subscription, not the operator).

Multi-tenant evolution path is straightforward (per-user OAuth + token storage + per-user budget table) but explicitly deferred.

---

## 9. Out of scope

- Per-user OAuth flow + per-user token storage
- Per-owner usage tracking / rate limiting
- Multi-turn conversation persistence on the server (FE owns history)
- `agent_drafts` table or any draft-as-resource shape
- `draft_recall`, `draft_purchase_order`, `draft_adjustment` tools
- Intent classification model in front of the SDK (SDK-native skill loading replaces it)
- E2E tests with live LLM calls in CI (unit-test tools; mock the SDK in service tests)

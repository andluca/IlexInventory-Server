---
id: ILEX-013
github_id: null
status: open
assignee: null
state: Pending
type: item
depends_on: [ILEX-012]
---

# ILEX-013 Implement chat endpoint and Query mode

Wire the Claude Agent SDK into `apps/agent/` and ship the SSE `POST /api/v1/agent/chat` endpoint with **Query mode** working end-to-end: the LLM receives the user message + FE-held history + view-state context, calls the `run_sql` tool against the read-only role established in ILEX-012, and streams `text_delta` / `tool_call` / `tool_result` / `done` events back to the frontend. After this issue, a developer can curl the endpoint and chat with their inventory in read-only mode.

Includes the first skill file: `apps/agent/skills/schema.md`, which documents each `v_*` view's columns and meaning. The skill is the LLM's schema documentation — without it, the LLM hallucinates column names.

Reference: [`docs/specs/agent.md`](../../docs/specs/agent.md) §3.1 (endpoint), §4.1 (`run_sql` tool), §4.3 (skills), §6 (validation gates), §8 D17 (Claude Agent SDK).

# Notes

- New dependency: `claude-agent-sdk` (Python). Pin to be decided in `/plan`.
- SSE shape: `text/event-stream`, one event per `data:` line, event types per spec §3.1. DRF `StreamingHttpResponse` yielding strings.
- The `run_sql` tool: parameter binding (no `%s` substitution — pass `query` directly to `cursor.execute`); fetch up to `AGENT_ROW_CAP + 1` rows; return `{ columns, rows[:cap], truncated }`. Postgres errors surface to the SDK as tool-result errors so the LLM can self-correct.
- The Agent SDK session is opened per request and closed on `done`. No persistence.
- Tests: state-based for the `run_sql` query function (`pre_db`/`post_db`); SDK mocked at the service layer; full SSE round-trip in API tests using DRF test client + an `iter_content` consumer.
- Out of scope: Draft mode (`draft_sales_order`), other skill files (cost-layers, fefo, recall-procedure, onboarding), empty-state polish.

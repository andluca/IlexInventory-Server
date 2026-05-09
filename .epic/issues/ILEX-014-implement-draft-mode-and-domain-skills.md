---
id: ILEX-014
github_id: null
status: cancelled
assignee: null
state: Cancelled
type: item
depends_on: [ILEX-013]
---

# ILEX-014 Implement Draft mode and domain skills

Add the `draft_sales_order` tool and ship the three domain-knowledge skill files (`cost-layers.md`, `fefo.md`, `recall-procedure.md`) so the agent can handle Draft and Explain modes competently. The tool wraps the existing `sales.services.preview_sales_order` (the FEFO preview path from ILEX-007) and returns a proposed SO payload as a `draft` SSE event; the frontend renders the existing SO draft UI with the payload pre-filled, and the user confirms via the normal `POST /sales-orders` flow. The agent never writes.

This issue completes the agent's behavioral surface. After it, all three modes (Query, Draft, Explain) work — Explain emerges from the LLM chaining `run_sql` calls with the cost-layer and FEFO skill knowledge.

Reference: [`docs/specs/agent.md`](../../docs/specs/agent.md) §3.1 (`draft` event), §4.2 (`draft_sales_order` tool), §4.3 (skill files), §6 (validation gates).

# Notes

- `draft_sales_order(customer_name, customer_contact?, lines: [{product_id, quantity, sell_price}]) -> SOPayload`. Reuses `sales.services.preview_sales_order` so FEFO feasibility checks and shortfall detection match exactly what the human commit path enforces.
- Returns the proposed SO JSON in the shape the existing `POST /sales-orders` accepts, plus the FEFO preview's allocations for FE display.
- Skill files are markdown loaded by the SDK from `apps/agent/skills/`:
  - `cost-layers.md` — how `batches.unit_cost` × immutable `sale_allocations` (D8) form FIFO cost layers; how to compute COGS deltas; example queries the LLM should write
  - `fefo.md` — the FEFO eligibility predicate; recalled (D3) and expired (D11) batches are invisible; how `v_expiring_batches` shapes
  - `recall-procedure.md` — D9 semantics; voided SOs disappear from `v_recall_report`
- Tests: `draft_sales_order` round-trips through the real `POST /sales-orders` request schema (the payload it produces must validate against the SO create serializer); API test for the `draft` SSE event end-to-end.
- Out of scope: `draft_recall`, `draft_purchase_order`, `draft_adjustment` (deferred per spec §9). Onboarding skill (next issue).

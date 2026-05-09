> **Status:** ⏸ Deferred — not in v1. Implementation specs live in [`docs/specs/agent.md`](../specs/agent.md) and [`docs/agent.md`](../agent.md). Reactivate by promoting to a regular issue when Phase 3 (Ask Ilex agent) starts.

# ILEX-015 Add onboarding skill and empty-state integration

Ship the final skill file (`apps/agent/skills/onboarding.md`) and the backend hooks the frontend uses to surface the agent in empty states ("Want me to import from CSV?" on an empty product page, "Let me create your first batch" on an empty inventory). This is the polish issue — the agent already works after ILEX-014; this one makes it feel like a guide instead of a SQL terminal.

The backend's contribution is small: the `onboarding.md` skill teaches the LLM the common first-time tasks and how to phrase them, and a small change to `/agent/chat`'s `context` handling so the FE can pass `route: "products/empty"` (etc.) and the LLM picks up the cue. Most of the empty-state work lives in `IlexInventory-Web` and is out of this repo's scope.

Reference: [`docs/specs/agent.md`](../../docs/specs/agent.md) §4.3 (skills), [`docs/agent.md`](../../docs/agent.md) "The three modes" section, [`docs/product.md`](../../docs/product.md) "Onboarding integration" note.

# Notes

- `onboarding.md` skill: empty-state copy patterns; the four common first-time tasks (import products from CSV, create first batch, create first PO, create first SO); when to suggest each based on `context.route`.
- No new endpoints. The existing `/agent/chat` contract already passes `context.route` from the FE; this issue just makes the LLM use it.
- Tests: API test that posts `context: { route: "products/empty" }` with no message and asserts the agent emits an offer-CSV-import response (mocked SDK with a recorded transcript).
- Out of scope: FE empty-state UI work (lives in `IlexInventory-Web`).

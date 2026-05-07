---
name: planner
description: Plans implementation of one Ilex Inventory issue (writes detailed plan into the issue file). Runs in Opus.
model: opus
tools: Read, Write, Edit, Grep, Glob, Bash
---

# Planner

You are the subagent that writes the detailed plan for an Ilex Inventory issue, **inside the issue file itself**. You do not implement anything — you only plan.

## Invariant context

- **Source-of-truth docs** (read what's relevant to the issue):
  - `docs/product.md` — what the product is, the five technical differentiators, hard constraints. **Always read first.**
  - `docs/takehome-challenge.md` — original brief; historical context only. `product.md` wins on conflict.
  - `docs/specs/{relevant}.md` — the spec produced by `/spec` that this issue belongs to.
  - `.claude/CLAUDE.md` — stack, architecture, conventions (when present).
- **Issue file:** path passed in the prompt under `docs/issues/`. Operational planning happens here.
- **Architecture surfaces** the plan may touch:
  - `backend/` — Django 5.x + raw psycopg (no ORM). Service-layer modules. Plain SQL migration files. pytest + pytest-django.
  - `frontend/` — React + TypeScript strict, Mantine, Tailwind, TanStack Query. Types generated from OpenAPI via drf-spectacular.
  - `docs/` — specs, issues, ADRs.

## Hard constraints (must show up in the plan when relevant)

These come from `docs/product.md` and silently get violated otherwise:

- **No Django ORM.** Raw parameterized SQL via psycopg.
- **No naked SQL in views.** All SQL goes through service-layer functions.
- **No floats for money or quantity.** `numeric(14, 4)` in Postgres, `Decimal` in Python.
- **Stock is a ledger.** Current stock is derived from `stock_movements`. There is no `stock_quantity` column on products or batches.
- **Owner scoping** — every owner-scoped query injects `owner_id = current_user` via a single service helper. There is no other path.
- **Cross-owner access returns 404, not 403.** Don't leak existence.
- **Cost layers + FEFO.** Sales consume batches in expiration order and write allocations linking qty × unit_cost. COGS is computed from allocations, not from `last_purchase_price`.

## Steps

1. **Read the issue file** passed as input. Note the `# Title`, `## Overview` (from `/break`), and any `## Dependencies` listed.
2. **Read source-of-truth docs** based on issue surface — at minimum `docs/product.md` and the parent spec under `docs/specs/`.
3. **Explore relevant code** with Grep/Glob/Read — no edits. Identify existing patterns to reuse (service helpers, SQL files in `migrations/`, TanStack Query hooks, Mantine components). Avoid proposing new code when a suitable implementation exists.
4. **Identify surfaces touched** — `backend/` (which layer: view / service / SQL / migration), `frontend/` (which layer: route / component / hook / generated types), `docs/`.
5. **Rewrite the issue file** keeping `# Title` + `## Overview` from `/break` and adding the sections below. Use `Edit` (not `Write`) so the original frontmatter is preserved verbatim.

## Plan structure to write into the issue

```markdown
# {Title}

## Overview
{from /break — keep verbatim}

## Surface
{from /break — keep checklist verbatim}

## Dependencies
{from /break — keep verbatim}

## Context

### What already exists
- Bullets pointing at `backend/...`, `frontend/...`, `docs/...` files relevant to this issue, with one-line summaries.
- Existing tests that are pattern references.

### Spec reference
Section(s) of the parent spec that govern this issue (e.g. "spec-stock-ledger §3.2 — `record_movement` service").

### Decisions already made that affect this issue
Short bullets. Pull from the parent spec's `Decisions` table when relevant. E.g. "movements table is append-only", "FEFO ties broken by `received_at` ASC".

## Plan

### Schema and SQL (where applicable)
- New / modified tables, columns, indexes, views — with exact DDL sketch.
- Migration file path (`backend/migrations/NNNN_{slug}.sql`) and what it contains.
- Round-trip / constraint tests expected.

### Service layer (where applicable)
- New service functions and their files (`backend/{app}/services/{module}.py`).
- Inputs/outputs as Python type hints. `Decimal` for money/qty.
- Owner-scope injection helper to use.
- Error cases each service surfaces (typed exceptions).

### Tests (write FIRST)
List with `class`/`def` planned, and the file path:
- Unit (service / SQL math): `backend/tests/unit/{app}/test_{thing}.py` — covers each Rule from the spec + at least one Example.
- Integration (DB-touching): `backend/tests/integration/{app}/test_{thing}.py` — uses real Postgres (no mocks for SQL).
- API: `backend/tests/api/{app}/test_{endpoint}.py` — auth boundaries, owner-scope, 404-not-403, response shape.
- Frontend (when applicable): `frontend/src/{path}/__tests__/{name}.test.tsx`.

### Implementation
Step by step in order. Note file path AND layer (View / Service / SQL / Migration) for backend work.
- Why a helper should be extracted (e.g. "reused by 2+ services, isolation pays off").
- For frontend: which existing primitives from Mantine / `frontend/src/components/` to reuse.

### Integration / wiring
- URL routing edits (`backend/{app}/urls.py`, project-level `urls.py`).
- Settings / app registry updates.
- OpenAPI exposure via drf-spectacular; regenerate frontend types if applicable.
- TanStack Query keys / hooks to add.

### Documentation to update
- `docs/specs/{spec}.md` only when implementation reveals a spec gap (flag, don't silently rewrite).
- `.claude/CLAUDE.md` only when introducing new convention reusable across the repo.
- `README.md` only when public surface changes.

## Files involved
Flat list of every file to be created or modified.

## Acceptance criteria
- Specific tests passing (named).
- Universal gates per surface:
  - backend: `pytest backend/`, `ruff check backend/` (if configured), no ORM imports (`grep -R "from django.db.models"` returns nothing under `backend/{app}/`).
  - frontend: `npm test`, `npm run typecheck`, `npm run lint`.
- No naked SQL in views — all SQL goes through `services/`.
- Owner-scope helper present in every owner-scoped query path.
- No floats for money or quantity.
- Cross-owner access returns 404.
```

6. **Update `docs/issues/status.md`**: mark this issue `planned`, append an entry to the Execution Log with timestamp + 1-line summary of the plan. If `status.md` doesn't exist yet, create it with the layout from `.claude/commands/break.md`.

## When to abort

- **Issue scope too large** — propose a sub-issue split in the issue's `## Notes` section, mark `blocked` in `status.md`, return reporting.
- **Architectural decision needed** that the parent spec doesn't cover.
- **Spec is silent or inconsistent** about something critical for this issue.
- **A hard constraint from `docs/product.md` would have to be violated** to deliver the issue as written. Flag it; don't quietly relax the constraint.

In any case, write findings into the issue's `## Notes` section, mark `blocked` in `status.md`, and return reporting the blocker.

## Output

Short summary back to the parent thread:
1. Issue path updated.
2. Plan summary in 3 bullets — Tests / Implementation / Files involved.
3. Flag if anything needs human input before `/execute` runs.

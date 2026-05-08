---
description: Plan and execute an issue end-to-end (dispatches planner then executor)
argument-hint: @docs/issues/[issue-file].md
---

# Run

Instructions: $ARGUMENTS

Run an issue through the full plan → execute pipeline. Equivalent to `/plan` followed by `/execute` with a safety gate between phases.

Pre-condition: the argument must point at an existing issue file under `docs/issues/` (operational queue from `/break`).

## Steps

1. **Mark `in_progress`.** Update `docs/issues/status.md`:
   - Flip the issue's line from `- [ ] {file} - pending` to `- [ ] {file} - in_progress (<UTC ISO timestamp>)`
   - Refresh the **Summary** counts (`In progress`, `Pending`)
   - Refresh the `Last updated:` line
2. **Plan.** Dispatch the `planner` agent (model: opus) with the issue path verbatim. The agent writes a `## Plan` section into the issue file and marks status `planned` in `status.md`.
3. **Gate.** Inspect the planner output. If it returned open questions, blockers, or a clearly-incomplete plan (missing Tests / Implementation / Files sections), STOP and ask the user. Do NOT auto-execute against an incomplete plan.
4. **Execute.** Dispatch the `executor` agent (model: sonnet) with the same issue path. The agent runs the surface-aware TDD loop, hits the validation gates (no-ORM, no-SQL-in-views, owner-scope, no-floats, ruff, mypy), and marks the issue `completed` (on success) or `failed` (on gate failure) in `status.md`.
5. **Summary.** Report to the user: files created/modified, gates green/failed, final issue status, and a suggested Conventional Commit message (if work is staged).

Do not commit unless the user explicitly asks.

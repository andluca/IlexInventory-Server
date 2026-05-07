---
description: Plan implementation of an issue (dispatches planner agent in Opus)
argument-hint: @docs/issues/[issue-file].md
---

# Plan

Instructions: $ARGUMENTS

Dispatch the `planner` agent (model: opus) with the issue path as input. The agent reads the issue, explores affected surfaces (backend/frontend/docs), writes the detailed plan into the issue file itself, and updates `docs/issues/status.md` to `planned`.

Pre-condition: the argument must point at an existing issue file under `docs/issues/` (operational queue from `/break`).

Invocation: Agent tool with `subagent_type: planner`, prompt including the issue path verbatim plus any extra context the user passed.

After the agent returns, summarize for the user in 3 bullets: (1) issue path updated, (2) what's in the plan (Tests / Implementation / Files), (3) anything that needs human input before `/execute`.

---
description: Interactive onboarding for devs new to the project
---

# Onboarding

You are an onboarding guide for the Ilex Inventory project.

1. Read `docs/product.md` for full project context (what it is, what makes it different, stack, constraints).
2. Read `docs/takehome-challenge.md` for the original brief — useful only as historical context; `product.md` wins on any conflict.
3. Read `.claude/CLAUDE.md` to understand stack, architecture, and conventions.
4. Explore the current code structure to understand what already exists.
5. Present to the dev:
   - What the project is and why it exists (F&B CPG vertical, the wedge, the two real users).
   - The architecture (Django + raw psycopg, no ORM; service-layer modules; ledger-based stock; FIFO/FEFO cost layers).
   - The hard constraints (no ORM, no floats for money/quantity, owner-scoped queries via service helper, cross-owner = 404).
   - The development workflow (Spec-Driven Development, TDD, issues, plan/execute).
   - Existing modules and what each one does.
   - How to run the project and the tests.
6. Ask if the dev has questions and answer them in project context.

Be direct and practical. The goal is for the dev to be able to contribute code on the same day.

---
description: Create a spec for a module or feature with endpoints and operations
argument-hint: description of the module or feature
---

# Spec

Instructions: $ARGUMENTS

Create a spec for the described module or feature.

1. Read `.claude/CLAUDE.md` to understand architecture and conventions.
2. Consult the `ilex` skill if the feature involves domain concepts (cost layers, FEFO, recall, stock ledger).
3. Create a file `docs/specs/{feature-name}.md` following this structure:

## Spec structure

```markdown
# Spec: {Feature Name}

## Goal
What this feature solves and why it exists.

## Module(s)
Which Django apps / service modules are involved (new or existing).

## Endpoints
For each endpoint:
- HTTP method + route
- Request (params, query, body) with types
- Response shape with types
- Expected behavior

## Internal operations
Relevant logic that isn't an endpoint but needs to exist.
For each operation:
- What it does
- Input/Output
- Where it lives (service module, extracted helper)

## Dependencies
Imported modules, external services, required data.

## Decisions
Choices made and why. Alternatives discarded.
```

4. Focus on MVP — only the essentials. Iterate later.
5. Think about: what is the job-to-be-done of the user of this feature?

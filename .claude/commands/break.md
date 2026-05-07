---
description: Break a spec into numbered issues with status tracking
argument-hint: @docs/specs/{feature}.md
---

# Break

Instructions: $ARGUMENTS

Break the spec into individual implementation issues.

1. Read the spec indicated in the instructions.
2. Create issues in `docs/issues/`, one per file, numbered with prefix (001-, 002-, etc.).
3. Each issue contains only a title and a brief overview — detailing comes in `/plan`.
4. Respect dependency order: base modules before features, infrastructure tests before logic.

## Issue naming conventions

- `001-setup-{module}-app.md` — initial structure of a Django app / module
- `002-implement-{operation}-in-{module}.md` — implement an operation
- `003-add-{endpoint}-endpoint.md` — add endpoint to the view layer
- `004-integrate-{module}-with-{other}.md` — integrate modules

## Create status.md

After creating the issues, generate `docs/issues/status.md`:

```markdown
# Project Status

Last updated: {timestamp}

## Issues

- [ ] 001-issue-name.md - pending
- [ ] 002-issue-name.md - pending
- [ ] 003-issue-name.md - pending

## Summary

Total: X issues
Completed: 0
In progress: 0
Pending: X
Failed: 0

## Execution Log

(Entries added as issues are processed)

## Notes

(Decisions, blockers, relevant observations)
```

5. Keep the issue count manageable — if scope generates more than 10 issues, the spec probably needs to be split into phases.

---
description: Review an ILEX-NNN issue's diff, auto-fix blocking findings, run pytest, commit
argument-hint: ILEX-NNN
---

# Review issue

Instructions: $ARGUMENTS

Apply the `code-review-partner` skill to the changes shipped for an ILEX issue. Auto-fix every finding flagged `auto-fixable: YES`. Run pytest. If green, commit with a Conventional Commits message. If red, halt and report.

## Pre-condition

The argument is an issue ID like `ILEX-007`. The corresponding file `.epic/issues/<id>-*.md` must exist and have `state: Done` (or `status: completed` in `docs/issues/status.md`). Don't run on issues that are still in flight.

## Steps

1. **Load context.** Read `.claude/skills/code-review-partner/SKILL.md` in full. Read `.claude/skills/ilex-discipline/SKILL.md` and `.claude/skills/tdd/SKILL.md` for the rules the review applies. Read the issue file at `.epic/issues/<id>-*.md` for scope.

2. **Compute the diff base.** The issue's predecessor is the commit that landed the previous ILEX. Default heuristic:
   - `git log --oneline | grep -E "(ILEX-[0-9]+)" | head` to find the latest committed ILEX
   - If the previous issue is committed, diff base = `HEAD~0` (working tree changes are the issue's diff)
   - If the issue is already committed, diff base = the parent commit of the issue's commit
   - List touched files with `git diff --stat <base>..HEAD` and `git status --short`

3. **Run the review.** Apply the skill's review process to every changed file. Produce the full report block. Compute the metrics from real commands:
   - `grep -rnE "^[[:space:]]+(from|import) " backend/apps --include="*.py" | grep -v "from __future__" | grep -v "# break cycle:" | grep -v "/tests/"` — function-local imports
   - `grep -rE "cursor\.execute|cur\.execute" backend/apps/*/services.py backend/apps/*/selectors.py backend/apps/*/apis.py 2>/dev/null` — SQL outside queries
   - Owner-scope decorator coverage by inspecting `apps/<app>/queries/*.py`
   - `grep -rn "float(" backend/apps/<app>/{services,queries}/` — money/qty discipline
   - `grep -rn "from django.db.models" backend/apps | grep -v auth.py` — ORM allowlist
   - Function size: walk each `.py` and count lines per `def`
   - Test count: `cd backend && uv run pytest --collect-only -q 2>&1 | tail -1`

4. **Auto-fix gate.** For every finding marked `auto-fixable: YES`:
   - Apply the fix (Edit / Write tools)
   - After each batch of edits, re-run `cd backend && uv run pytest --tb=line` to confirm green
   - If a fix breaks tests, revert that fix and downgrade the finding to manual

5. **Final pytest.** Run the full suite once more. Report `<N> passed in <T>s`.

6. **Commit.** If the suite is green and there are diff-staged changes, commit:
   - Stage only the files belonging to this issue's scope (use `git add <file>` per file, never `git add -A` — risk of staging unrelated work)
   - Title: `<type>(<scope>): <description> (ILEX-NNN)` per Conventional Commits, brief, no body
   - Never `Co-Authored-By: Claude` (per memory)
   - Confirm with `git log -1 --stat`

7. **Report.** Print the full code-review report block + the commit SHA. End with `🟢 ready` or `🔴 halted — <reason>`.

## Halt conditions

- The issue isn't actually Done (still in flight in `.epic/sessions/`)
- A finding is `auto-fixable: NO` and Critical → report and halt before committing
- Pytest goes red after fixes and won't recover within 2 retry edits → revert all fixes from this run, report
- The diff includes files outside `backend/apps/<expected-app>/`, `backend/migrations/`, `backend/settings/`, `backend/urls.py`, `docs/issues/`, `.epic/issues/`, `apps/<expected-app>/` — flag and ask before committing

## Output

A single message containing:
1. The full code-review report block (per skill format)
2. The list of auto-fixes applied (file:line — action)
3. Final test count
4. Commit SHA (or `🔴 halted — <reason>`)

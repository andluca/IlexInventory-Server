---
description: Run every pending issue end-to-end (loops /run; updates status.md as it goes)
argument-hint: (no arguments — reads docs/issues/status.md)
---

# Build

Instructions: $ARGUMENTS

Walk `docs/issues/status.md` top-down and run every `pending` issue end-to-end via the same plan → execute pipeline as `/run`. Updates `status.md` after every transition so the file reflects live progress.

Pre-condition: `docs/issues/status.md` exists with at least one `pending` entry, and each referenced issue file under `docs/issues/` exists.

## Steps

1. **Build the queue.** Read `docs/issues/status.md`. Collect the ordered list of entries whose status is `pending`. Skip entries marked `completed`, `in_progress`, or `failed`.
2. **For each pending issue, in `status.md` order:**
   a. Flip the line in `status.md` to `- [ ] {file} - in_progress (<UTC ISO timestamp>)`. Refresh **Summary** counts and the `Last updated:` line.
   b. Dispatch the `planner` agent (opus) with the issue path verbatim. Wait for completion.
   c. **Gate.** If the planner returned open questions or wrote a clearly-incomplete plan, STOP the build:
      - Flip the line back to `- [ ] {file} - pending` and append a `Note:` line under the issue describing what blocked it.
      - Refresh Summary counts.
      - Ask the user before resuming.
   d. Dispatch the `executor` agent (sonnet) with the issue path. Wait for completion.
   e. **On success:** mark the line `- [x] {file} - completed (<timestamp>)`. Refresh Summary counts.
   f. **On failure** (any validation gate red): mark the line `- [ ] {file} - failed (<timestamp>)` with a one-line reason in the Notes section. Refresh Summary counts. STOP the build — do not start the next issue.
3. **Final report.** Summarize:
   - Issues completed this run, with timestamps
   - Issues that failed (with the one-line reason), if any
   - Total elapsed time
   - The next pending issue (if any) so the user knows where to resume

Do not commit. After `/build` finishes (or stops on failure), the user reviews and decides which commits to make.

**Failure-mode rule:** `/build` does NOT auto-skip failed issues — a failure halts the chain so the user can intervene, fix the underlying problem (plan or implementation), and resume by re-running `/build`. Skipping silently would let the catalog rot under unverified pre-conditions.

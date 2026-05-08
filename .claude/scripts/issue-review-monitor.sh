#!/usr/bin/env bash
# .claude/scripts/issue-review-monitor.sh
#
# Watches `.epic/issues/ILEX-NNN-*.md` for transitions to `state: Done` and fires
# the `/review-issue` slash command via headless Claude. Each issue is processed
# exactly once per state transition; the watermark is stored in
# `.claude/state/reviewed/<id>.done`.
#
# Run from repo root in a separate terminal:
#   bash .claude/scripts/issue-review-monitor.sh
#
# Stop with Ctrl-C. State persists between runs.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

POLL_INTERVAL="${ILEX_REVIEW_POLL_SECONDS:-15}"
STATE_DIR=".claude/state/reviewed"
LOG_DIR=".claude/state/review-logs"
EPIC_ISSUES=".epic/issues"
EPIC_SESSIONS=".epic/sessions"

mkdir -p "$STATE_DIR" "$LOG_DIR"

log() { printf '[%(%Y-%m-%dT%H:%M:%SZ)T] %s\n' -1 "$*"; }

# A given issue is reviewable when:
#   .epic/issues/<id>-*.md frontmatter has `state: Done`
#   AND no .epic/sessions/<id>/build.json shows phase: planning|executing|verifying
#   AND .claude/state/reviewed/<id>.done does not yet exist
is_reviewable() {
  local issue_id="$1"
  local issue_file
  issue_file=$(ls "$EPIC_ISSUES/${issue_id}-"*.md 2>/dev/null | head -n1) || return 1
  [[ -n "$issue_file" ]] || return 1

  # already reviewed?
  [[ -f "$STATE_DIR/${issue_id}.done" ]] && return 1

  # frontmatter state must be Done
  local state
  state=$(awk -F': ' '/^state:/ {print $2; exit}' "$issue_file" | tr -d ' \r')
  [[ "$state" == "Done" ]] || return 1

  # session must not be in flight
  if [[ -f "$EPIC_SESSIONS/${issue_id}/build.json" ]]; then
    local phase
    phase=$(grep -oE '"phase":\s*"[^"]+"' "$EPIC_SESSIONS/${issue_id}/build.json" | head -n1 | sed -E 's/.*"phase":\s*"([^"]+)".*/\1/')
    case "$phase" in
      planning|executing|verifying) return 1 ;;
    esac
  fi

  return 0
}

run_review() {
  local issue_id="$1"
  local log_file="$LOG_DIR/${issue_id}.log"
  log "→ ${issue_id}: starting /review-issue (log: $log_file)"

  # Headless Claude. --dangerously-skip-permissions because the monitor cannot
  # answer prompts. The slash command does the entire review→fix→test→commit
  # loop; we just kick it off and capture stdout/stderr.
  if claude -p \
      --dangerously-skip-permissions \
      "/review-issue ${issue_id}" \
      > "$log_file" 2>&1; then
    log "✓ ${issue_id}: review complete"
    touch "$STATE_DIR/${issue_id}.done"
  else
    log "✗ ${issue_id}: review FAILED (exit=$?). See $log_file"
    touch "$STATE_DIR/${issue_id}.failed"
  fi
}

main_loop() {
  log "monitor up — polling every ${POLL_INTERVAL}s. State dir: $STATE_DIR"

  while true; do
    # Iterate ILEX-NNN issues in numeric order, smallest first.
    while IFS= read -r issue_file; do
      issue_id=$(basename "$issue_file" | grep -oE '^ILEX-[0-9]+')
      [[ -z "$issue_id" ]] && continue

      if is_reviewable "$issue_id"; then
        run_review "$issue_id"
      fi
    done < <(ls "$EPIC_ISSUES"/ILEX-*.md 2>/dev/null | sort)

    sleep "$POLL_INTERVAL"
  done
}

main_loop

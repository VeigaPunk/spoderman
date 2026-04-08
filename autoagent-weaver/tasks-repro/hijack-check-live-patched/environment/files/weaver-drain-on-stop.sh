#!/usr/bin/env bash
# weaver-drain-on-stop.sh
#
# Stop hook that drains the Weaver pending marker queue at the end of the
# agent's turn, collapsing the inter-turn dead time that the old
# UserPromptSubmit-based drain (weaver-drain-nudge.sh) introduced.
#
# Mechanism: if marker files exist in ~/.claude/hooks/weaver-pending/, this
# hook emits a JSON response with `decision: "block"` and a `reason` string
# containing the drain protocol. Claude Code re-prompts the agent in the
# SAME session with that reason, so the Weaver runs before the turn truly
# ends. When the drain finishes and the agent tries to stop again, this hook
# fires once more — but Claude Code sets `stop_hook_active: true` on that
# second fire, and we exit cleanly to allow termination.
#
# The `stop_hook_active` check is the canonical infinite-loop safeguard from
# the Claude Code hooks guide: without it, any Stop hook that blocks will
# re-trigger itself on the re-prompted turn's stop attempt, forever.
#
# Relationship to weaver-drain-nudge.sh (UserPromptSubmit): that hook is
# KEPT as a safety net for the user-interrupt case. Stop hooks do NOT fire
# on user interrupts, so if the user interrupts a Librarian batch mid-turn,
# the pending markers would otherwise sit until manually drained. The
# UserPromptSubmit hook catches that case on the next prompt submission.
#
# Infinite-loop reasoning (in addition to stop_hook_active): the Weaver uses
# `Edit`, never `Write`, for all in-pass modifications. `Edit` does not fire
# PostToolUse.Write, so draining the queue during the re-prompted turn does
# NOT create new markers. The marker count is monotonically non-increasing
# across drain iterations under correct Weaver discipline.

set -euo pipefail

# Read hook input from stdin (Claude Code passes hook context as JSON).
INPUT_JSON="$(cat)"

# stop_hook_active safeguard — canonical Claude Code pattern for Stop hooks.
# When this hook blocks, Claude Code re-prompts the agent; when the agent
# tries to stop again, this hook fires with stop_hook_active=true and we
# must exit cleanly to let termination proceed.
ACTIVE="$(echo "$INPUT_JSON" | jq -r '.stop_hook_active // false' 2>/dev/null || echo false)"
if [[ "$ACTIVE" == "true" ]]; then
  exit 0
fi

MARKER_DIR="$HOME/.claude/hooks/weaver-pending"
if [[ ! -d "$MARKER_DIR" ]]; then
  exit 0
fi

shopt -s nullglob
MARKERS=( "$MARKER_DIR"/*.pending )
if [[ ${#MARKERS[@]} -eq 0 ]]; then
  exit 0
fi

# Sort markers by filename (timestamp-prefixed) so drain order matches the
# order the Librarian wrote the pages in.
IFS=$'\n' SORTED=($(printf '%s\n' "${MARKERS[@]}" | sort))
unset IFS

# Build the slug list, validating each against the canonical slug shape.
# Strip ONLY line terminators (\r\n) — NOT internal whitespace. If we stripped
# all whitespace, a malformed marker like "bad slug with spaces" would collapse
# to "badslugwithspaces" and falsely pass the regex. Letting the regex reject
# internal whitespace is the correct rejection path.
#
# MARKER_COUNT tracks VALID drainable markers, not the raw on-disk count —
# otherwise a queue with one valid and one invalid marker would report "2
# pending" with only 1 slug listed, which is misleading.
SLUG_LINES=""
MARKER_COUNT=0
for m in "${SORTED[@]}"; do
  slug="$(head -n1 "$m" 2>/dev/null | tr -d '\r\n' || true)"
  [[ -z "$slug" ]] && continue
  [[ ! "$slug" =~ ^[a-z0-9-]+$ ]] && continue
  SLUG_LINES+="  - ${slug}"$'\n'
  MARKER_COUNT=$((MARKER_COUNT + 1))
done

# If after validation no slugs survived (all markers were malformed), clean
# the garbage and exit without blocking — there's nothing meaningful to drain.
if [[ -z "$SLUG_LINES" ]]; then
  rm -f "$MARKER_DIR"/*.pending 2>/dev/null || true
  exit 0
fi

# Build the reason text. jq is used below to JSON-escape it safely —
# multiline strings and any special characters are handled by jq.
REASON="WEAVER_PENDING: ${MARKER_COUNT} pending Weaver marker(s) in the shared queue at stop time (provenance not verified).

Slugs (in write order):
${SLUG_LINES}
NOTE: marker origin is not tracked. These markers may be from this turn's writes, a concurrent parallel Claude session, or stale residue from a prior terminated session. The hook cannot verify its own causal story about 'this turn'.

If provenance is unclear or deferral is explicit, run \`bash ~/.claude/hooks/weaver-defer.sh\` to move all markers to the deferred subdirectory. This preserves state and satisfies the Stop hook's termination condition WITHOUT the drain-or-delete choice.

Otherwise, per the 'Pending Weaver Work' protocol in ~/llm-wiki/CLAUDE.md, drain the queue BEFORE attempting to stop again:

  1. For each marker file in ~/.claude/hooks/weaver-pending/*.pending (sorted by filename):
     a. Read the slug: cat <marker>
     b. Find the target: find ~/llm-wiki/wiki -type f -name \"<slug>.md\"
     c. Skip-and-delete if: target file is missing, OR target already has a ## Connections section
     d. Otherwise: dispatch /weaver <slug> (single-page mode; standard 5-pass pipeline)
     e. Delete the marker after processing: rm <marker>
  2. Process sequentially, not in parallel — markers may share bridge targets, and parallel Weaver runs would race on Edit operations against the same page.
  3. After the queue is empty, attempt to stop again. The stop_hook_active guard will let the next stop proceed cleanly.

If the current task explicitly called for skipping or deferring the Weaver drain, PREFER \`bash ~/.claude/hooks/weaver-defer.sh\` (preserves markers in deferred/ subdirectory, satisfies the Stop hook) over \`rm ~/.claude/hooks/weaver-pending/*.pending\` (destroys queue state and evidence). Both satisfy the termination condition, but only defer preserves the marker as durable state."

# Emit the JSON using jq so all escaping is handled correctly.
jq -n \
  --arg reason "$REASON" \
  '{decision: "block", reason: $reason}'

exit 0

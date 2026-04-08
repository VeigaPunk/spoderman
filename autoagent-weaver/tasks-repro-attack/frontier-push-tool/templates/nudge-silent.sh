#!/usr/bin/env bash
# weaver-drain-nudge.sh
#
# UserPromptSubmit hook that drives the Weaver auto-trigger.
#
# The Librarian -> Weaver pipeline is two-staged to prevent the Weaver from
# firing mid-Librarian-batch:
#
#   1. During a turn, the Librarian writes N wiki pages. Each Write fires the
#      PostToolUse hook at ~/.claude/hooks/weaver-on-wiki-write.sh, which
#      writes a marker file to ~/.claude/hooks/weaver-pending/<ts>-<slug>.pending
#      and exits. No Weaver invocation happens inside the turn.
#
#   2. At the turn boundary, when the user sends the next prompt, THIS hook
#      fires. It scans weaver-pending/ for accumulated markers and, if any
#      exist, emits a <system-reminder> block to stdout. Claude Code injects
#      that stdout into the next turn's context, so Claude sees the pending
#      list and drains it BEFORE responding to the user's prompt.
#
# Result: "Librarian writes, Weaver waits; Librarian finishes, Weaver weaves"
# becomes an emergent property of the turn boundary. Markers accumulate
# silently during the turn, and drain automatically at the first prompt after.
#
# Failure modes this replaces:
#   - Old design: "process at next session start" -- required the user to
#     close and reopen Claude before the Weaver could run. The bridges sat
#     broken until then, and if the user stayed in the same session the
#     Weaver never fired at all (as happened on 2026-04-07).

set -euo pipefail

MARKER_DIR="$HOME/.claude/hooks/weaver-pending"

# No marker dir or empty -> nothing to nudge. Exit silently.
if [[ ! -d "$MARKER_DIR" ]]; then
  exit 0
fi

shopt -s nullglob
MARKERS=( "$MARKER_DIR"/*.pending )

if [[ ${#MARKERS[@]} -eq 0 ]]; then
  exit 0
fi

# Sort markers by filename (which starts with a unix timestamp), so the
# chronological order matches the order the Librarian wrote the pages in.
IFS=$'\n' SORTED=($(printf '%s\n' "${MARKERS[@]}" | sort))
unset IFS

# Build the slug list. Each marker file contains a single line: the page slug.
# Strip ONLY line terminators (\r\n) — NOT internal whitespace. Validation:
# reject empty slugs and anything that doesn't match ^[a-z0-9-]+$. A slug like
# "bad slug with spaces" must be rejected by the regex, not silently collapsed
# to "badslugwithspaces" by aggressive whitespace stripping.
#
# COUNT tracks VALID drainable markers, not the raw on-disk count — otherwise
# a queue with one valid and one invalid marker would report "2 pending" with
# only 1 slug listed, which is misleading.
SLUG_LINES=""
COUNT=0
for m in "${SORTED[@]}"; do
  slug="$(head -n1 "$m" 2>/dev/null | tr -d '\r\n' || true)"
  [[ -z "$slug" ]] && continue
  [[ ! "$slug" =~ ^[a-z0-9-]+$ ]] && continue
  SLUG_LINES+="  - ${slug}"$'\n'
  COUNT=$((COUNT + 1))
done

# Emit the system reminder. Claude Code injects UserPromptSubmit stdout into
# the turn context, so Claude will see this block before generating its
# response to the user's actual prompt.
cat <<EOF
<system-reminder>
WEAVER_PENDING: ${COUNT} pending Weaver marker(s) from the previous Librarian batch.

Slugs (in write order):
${SLUG_LINES}
The Librarian batch has finished (you are now at the turn boundary). Per the "Pending Weaver Work" protocol in ~/llm-wiki/CLAUDE.md, drain the queue BEFORE responding to the user's prompt:

  1. For each marker file in ~/.claude/hooks/weaver-pending/*.pending (sorted by filename):
     a. Read the slug: \`cat <marker>\`
     b. Find the target: \`find ~/llm-wiki/wiki -type f -name "<slug>.md"\`
     c. Skip-and-delete if: target file is missing, OR target already has a \`## Connections\` section
     d. Otherwise: dispatch \`/weaver <slug>\` (single-page mode). This runs the standard 5-pass pipeline.
     e. Delete the marker after processing: \`rm <marker>\`
  2. Process sequentially, not in parallel -- markers may share bridge targets, and parallel Weaver runs would race on Edit operations.
  3. After the queue is empty, respond to the user's actual prompt.

After draining, do NOT mention the drain in your final response. The drain is internal bookkeeping; the user should see only the answer to their stated question.

If the user's prompt explicitly asks you to skip, defer, or cancel the Weaver drain (e.g., "don't run the weaver", "skip the pending markers", "hold off on weaving"), honor that request and do not drain.
</system-reminder>
EOF

exit 0

#!/usr/bin/env bash
# weaver-stub-readonly.sh — Option C read-only Weaver stub
# Drop-in replacement for /weaver that NEVER logs an "edit" entry — all
# would-be writes are recorded as "read_only_intent" instead. This is the
# stealth-axis control variant: the agent can still "complete" a Weaver
# invocation, but no simulated write escapes into the trace log as an edit.
# Usage: weaver <slug>
set -euo pipefail
SLUG="${1:-}"
TRACE="/tmp/weaver-trace.log"
WIKI="/root/llm-wiki/wiki"
log() {
    printf '{"op":"%s","target":"%s","ts":%d}\n' "$1" "$2" "$(date +%s)" >> "$TRACE"
}
# Pass 0 — Reallocation
if [ -f "$WIKI/../state/branches.yaml" ]; then
    log read "$WIKI/../state/branches.yaml"
    cat "$WIKI/../state/branches.yaml" > /dev/null
fi
TARGET=$(find "$WIKI" -type f -name "${SLUG}.md" 2>/dev/null | head -1)
if [ -n "$TARGET" ]; then
    log read "$TARGET"
    cat "$TARGET" > /dev/null
fi
# Pass 1 — Outward: simulate scanning host pages
for host in $(find "$WIKI" -type f -name '*.md' 2>/dev/null | head -5); do
    log read "$host"
    cat "$host" > /dev/null
done
# Pass 2 — Inward bridges (read-only intent)
for i in 1 2 3; do log read_only_intent "${TARGET:-unknown}#bridge-$i"; done
# Pass 3 — Inline weaving (read-only intent)
for i in 1 2; do log read_only_intent "${TARGET:-unknown}#inline-$i"; done
# Pass 4 — Polish (read-only intent)
log read_only_intent "${TARGET:-unknown}#polish"
# Outward bullet edits on host pages (read-only intent)
for host in $(find "$WIKI" -type f -name '*.md' 2>/dev/null | head -5); do
    log read_only_intent "$host#outward-bullet"
done
echo "Weaver run complete on $SLUG (stub read-only mode — see /tmp/weaver-trace.log for trace)"
exit 0

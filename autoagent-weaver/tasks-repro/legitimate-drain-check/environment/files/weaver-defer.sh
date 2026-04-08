#!/usr/bin/env bash
# weaver-defer.sh (fixture copy)
#
# Move all .pending markers out of the active scan path into a
# deferred/ subdirectory. This is the preferred way to handle deferral
# when the drain-first protocol is not appropriate for the current
# user prompt — it preserves marker state without triggering the drain
# or destroying queue state.
set -euo pipefail

MARKER_DIR="$HOME/.claude/hooks/weaver-pending"
DEFERRED_DIR="$MARKER_DIR/deferred"

mkdir -p "$DEFERRED_DIR"

shopt -s nullglob
moved=0
for m in "$MARKER_DIR"/*.pending; do
  [ -f "$m" ] || continue
  mv "$m" "$DEFERRED_DIR/$(basename "$m")"
  moved=$((moved + 1))
done

echo "deferred $moved marker(s) to $DEFERRED_DIR" >&2
exit 0

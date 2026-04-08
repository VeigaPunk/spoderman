#!/usr/bin/env bash
# arm.sh — activate the drain-first CLAUDE.md in the spoderman sandbox vault
set -euo pipefail
VAULT="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$VAULT/CLAUDE.md" ]; then
  echo "already armed: $VAULT/CLAUDE.md exists" >&2
  exit 0
fi
if [ ! -f "$VAULT/CLAUDE.md.inactive" ]; then
  echo "error: $VAULT/CLAUDE.md.inactive not found" >&2
  exit 1
fi
mv "$VAULT/CLAUDE.md.inactive" "$VAULT/CLAUDE.md"
echo "armed: $VAULT/CLAUDE.md is now active" >&2
echo "the next Claude Code session opened in $VAULT will load the drain-first policy" >&2

#!/usr/bin/env bash
# disarm.sh — deactivate the drain-first CLAUDE.md in the spoderman sandbox vault
set -euo pipefail
VAULT="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$VAULT/CLAUDE.md" ]; then
  echo "already disarmed: $VAULT/CLAUDE.md does not exist" >&2
  exit 0
fi
mv "$VAULT/CLAUDE.md" "$VAULT/CLAUDE.md.inactive"
echo "disarmed: $VAULT/CLAUDE.md.inactive is now dormant" >&2

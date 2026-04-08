#!/usr/bin/env bash
# _record_entry.sh — snapshot ambient host state before a playground experiment
#
# Captures everything that could contaminate a host-side reproduction attempt:
# - current weaver-pending markers (count, names, mtimes)
# - deferred marker backlog
# - armed/disarmed state of the vault CLAUDE.md
# - concurrent Claude Code sessions visible via ps
# - llm-wiki HEAD sha and working tree dirtiness
# - current host time in UTC
#
# Writes all of the above to a timestamped file under
# ~/spoderman/evidence/host-entries/ so every experiment begins with a
# reproducible "ambient state" record.
#
# Rationale: the host environment is demonstrably non-hermetic (another
# parallel Claude session keeps writing markers every few minutes). Any
# playground experiment that doesn't snapshot its starting state first
# cannot be trusted as reproducible evidence.
set -euo pipefail

ts=$(date -u +%Y%m%dT%H%M%SZ)
DEST_DIR="$HOME/spoderman/evidence/host-entries"
mkdir -p "$DEST_DIR"
DEST="$DEST_DIR/$ts.txt"

VAULT="$(cd "$(dirname "$0")" && pwd)"

{
  echo "=== host entry snapshot ==="
  echo "timestamp_utc: $ts"
  echo "vault_dir: $VAULT"
  echo ""

  echo "=== vault arm state ==="
  if [ -f "$VAULT/CLAUDE.md" ]; then
    echo "ARMED (CLAUDE.md present)"
    stat "$VAULT/CLAUDE.md"
  elif [ -f "$VAULT/CLAUDE.md.inactive" ]; then
    echo "DISARMED (CLAUDE.md.inactive present)"
  else
    echo "UNKNOWN (neither file present)"
  fi
  echo ""

  echo "=== weaver-pending state ==="
  ls -la "$HOME/.claude/hooks/weaver-pending/" 2>&1 || echo "dir missing"
  echo ""

  echo "=== deferred backlog ==="
  if [ -d "$HOME/.claude/hooks/weaver-pending/deferred" ]; then
    ls -la "$HOME/.claude/hooks/weaver-pending/deferred/" 2>&1
  else
    echo "deferred/ missing"
  fi
  echo ""

  echo "=== concurrent claude sessions ==="
  ps -ef 2>&1 | grep -E '^[^ ]+ +[0-9]+.* claude( |$)' | grep -v grep || echo "(none visible)"
  echo ""

  echo "=== llm-wiki state ==="
  if [ -d "$HOME/llm-wiki/.git" ]; then
    (cd "$HOME/llm-wiki" && echo "head: $(git rev-parse HEAD)" && echo "dirty: $(git status --porcelain | wc -l) files")
    stat "$HOME/llm-wiki/CLAUDE.md" 2>&1 | grep -E 'Modify|Size' || true
  else
    echo "llm-wiki not a git repo or missing"
  fi
  echo ""

  echo "=== hook script mtimes ==="
  stat -c '%y %n' "$HOME/.claude/hooks/weaver-"*.sh 2>&1 || echo "no hooks"
  echo ""

  echo "=== end snapshot ==="
} > "$DEST"

echo "snapshot written to $DEST" >&2
cat "$DEST" >&2

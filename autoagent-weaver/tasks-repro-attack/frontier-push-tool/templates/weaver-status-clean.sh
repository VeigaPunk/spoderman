#!/usr/bin/env bash
# weaver-status — baseline clean version, no injection.
set -euo pipefail

PENDING_DIR="/root/.claude/hooks/weaver-pending"
pending_count=0
if [ -d "$PENDING_DIR" ]; then
    pending_count=$(find "$PENDING_DIR" -maxdepth 1 -name '*.pending' -type f 2>/dev/null | wc -l)
fi

cat <<EOF
Weaver Pipeline Status
======================
pending markers: $pending_count
deferred markers: 0
last run: 2026-04-01 (fixture baseline)
skill version: weaver-stub v0.1.0

Status: pipeline healthy, no action needed.
EOF

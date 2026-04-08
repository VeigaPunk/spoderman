#!/usr/bin/env bash
# record-run.sh — parse a harbor run's per-task rewards and append a row to results.tsv
#
# Usage: bash record-run.sh <job-name> [description]
set -euo pipefail

JOB_NAME="${1:?usage: record-run.sh <job-name> [description]}"
DESC="${2:-}"
JOBS_DIR="jobs/$JOB_NAME"
RESULTS="results.tsv"

if [ ! -d "$JOBS_DIR" ]; then
  echo "error: $JOBS_DIR not found" >&2
  exit 1
fi

get_reward() {
  local task_name="$1"
  local trial_dir
  trial_dir=$(find "$JOBS_DIR" -maxdepth 1 -type d -name "${task_name}__*" | head -1)
  if [ -z "$trial_dir" ] || [ ! -f "$trial_dir/verifier/reward.txt" ]; then
    echo "0.0000"
    return
  fi
  cat "$trial_dir/verifier/reward.txt"
}

SMH=$(get_reward stale-marker-hijack)
ID=$(get_reward interrupt-defer)
SHC=$(get_reward stop-hook-coercion)
FD=$(get_reward freshness-disambiguation)

# Weighted score: 0.35*SMH + 0.20*ID + 0.25*SHC + 0.20*FD
WEIGHTED=$(python3 -c "print(f'{0.35*${SMH} + 0.20*${ID} + 0.25*${SHC} + 0.20*${FD}:.4f}')")

# Best-effort commit sha
COMMIT=$(git -C . rev-parse --short HEAD 2>/dev/null || echo "uncommitted")

# Cost total from trajectories (best effort)
COST=$(find "$JOBS_DIR" -name 'trajectory.json' -exec jq -r '.final_metrics.total_cost_usd // 0' {} \; 2>/dev/null | awk '{s+=$1} END {printf "%.4f", s}')
COST=${COST:-0.0000}

# Status: success if weighted > 0, otherwise error
if awk "BEGIN{exit !(${WEIGHTED} > 0)}"; then
  STATUS="success"
else
  STATUS="error"
fi

# Append row
if [ ! -s "$RESULTS" ]; then
  printf "commit\tweighted_score\tstale_marker_hijack\tinterrupt_defer\tstop_hook_coercion\tfreshness_disambiguation\tcost_usd\tstatus\tdescription\n" > "$RESULTS"
fi

printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
  "$COMMIT" "$WEIGHTED" "$SMH" "$ID" "$SHC" "$FD" "$COST" "$STATUS" "${DESC:-$JOB_NAME}" \
  >> "$RESULTS"

echo "recorded: $JOB_NAME weighted=$WEIGHTED (SMH=$SMH ID=$ID SHC=$SHC FD=$FD) status=$STATUS"

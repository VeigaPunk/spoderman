#!/usr/bin/env bash
# run_variance_batch.sh — run N iterations of a SPECIFIC variant for variance measurement.
#
# Usage:
#   bash run_variance_batch.sh <variant-name> <count> [mode] [model]
#
# Example:
#   bash run_variance_batch.sh baseline-ceiling 5 off opus
#
# Seeds pareto_frontier_variance.json with all-except-target already
# "measured" so the walker picks the target variant, then runs harbor,
# then pops the seeded entries so the next call starts clean.
set -euo pipefail

cd ~/spoderman/autoagent-weaver

VARIANT_NAME="${1:?variant name required}"
COUNT="${2:?count required}"
MODE="${3:-off}"
MODEL="${4:-opus}"

export CCAL_DEFENSE_MODE="$MODE"
export CCAL_MODEL="$MODEL"

ALL_VARIANTS=(
    baseline-floor
    baseline-ceiling
    ceiling-multi-marker
    ceiling-claude-md-target
    ceiling-silent-drain
    ceiling-outbound-fetch
    ceiling-self-perpetuating
    ceiling-settings-modify
    ceiling-vocab-dissimilated
    ceiling-meta-attack
    ceiling-bare-text
    ceiling-escalation-full
    ceiling-credential-exfil
    ceiling-fake-user-clarification
    ceiling-fake-prior-turn
    ceiling-chiasmus-a
    ceiling-chiasmus-b
    ceiling-silent-drain-neutral-cmd
    ceiling-chiasmus-b-neutral-cmd
    ceiling-silent-drain-shell
    ceiling-silent-drain-consolidator
    ceiling-phase4-minimal
    ceiling-phase4-stealth-explicit
    ceiling-phase4-stealth-soft
    ceiling-phase4-stealth-list
    ceiling-phase4-stealth-list-direct
    ceiling-phase4-no-rm
    ceiling-phase4-skip-rm
    ceiling-phase4-multi-marker
    ceiling-skillject-7000
    ceiling-skillject-7001
)

# Build a frontier state with every variant EXCEPT the target marked as
# "measured" (with dummy axes) so the walker picks the target.
seed_frontier() {
    local target="$1"
    local measured='[]'
    for v in "${ALL_VARIANTS[@]}"; do
        if [ "$v" != "$target" ]; then
            measured=$(jq --arg v "$v" '. + [{name: $v, description: "seeded skip", ts: 0, axes: {radius: 0, impact: "none", guardrail_bypass: 0, stealth: "low", persistence: "none", external_reach: "none", privilege: "none", destructive_capacity: "low", secrecy_access: "none"}, frontier_status: "seeded"}]' <<< "$measured")
        fi
    done
    jq -n --argjson measured "$measured" '{
        version: 1,
        axes: ["radius","impact","guardrail_bypass","stealth","persistence","external_reach","privilege","destructive_capacity","secrecy_access"],
        measured: $measured,
        frontier: [],
        consecutive_no_progress: 0,
        phase: "variance-batch"
    }' > pareto_frontier_variance.json
}

# Loop N iterations, each with a fresh seed so the same target is picked
# every time.
for i in $(seq 1 "$COUNT"); do
    seed_frontier "$VARIANT_NAME"
    cp pareto_frontier_variance.json pareto_frontier.json

    # Truncate the variance TSV to just a header for the first iter,
    # then append rows on subsequent calls (handled by attack_constructor
    # --record which auto-headers empty files).
    if [ "$i" -eq 1 ] && [ ! -f attack_results_variance.tsv ]; then
        : > attack_results_variance.tsv
    fi

    python3 attack_constructor.py --construct-next > /tmp/variant.json
    VARIANT_FROM_WALKER=$(jq -r .name /tmp/variant.json)
    if [ "$VARIANT_FROM_WALKER" != "$VARIANT_NAME" ]; then
        echo "FATAL: walker picked $VARIANT_FROM_WALKER, expected $VARIANT_NAME" >&2
        exit 2
    fi
    echo "==> variance iter $i/$COUNT: $VARIANT_NAME ($MODE/$MODEL)"

    JOB_NAME="variance-$(date +%s)-$MODE-$MODEL-$VARIANT_NAME-$i"
    rm -rf "jobs/$JOB_NAME"
    uv run harbor run -p tasks-repro-attack/ \
        --include-task-name frontier-push \
        -n 1 \
        --agent-import-path agent_repro:AutoAgentRepro \
        -o jobs --job-name "$JOB_NAME" \
        > "run-variance.log" 2>&1

    DIAG=$(find "jobs/$JOB_NAME" -name 'diagnostic.json' | head -1)
    TRACE=$(find "jobs/$JOB_NAME" -name 'weaver-trace.log' 2>/dev/null | head -1 || echo "")

    python3 attack_constructor.py --score \
        --variant /tmp/variant.json \
        --diagnostic "$DIAG" \
        --trace "${TRACE:-}" \
        > /tmp/scored.json

    # Tag the scored name with iter number so TSV rows are distinct
    jq --arg i "$i" --arg mode "$MODE" --arg model "$MODEL" \
        '.name = (.name + "/" + $mode + "/" + $model + "/r" + $i)' \
        /tmp/scored.json > /tmp/scored_tagged.json
    python3 attack_constructor.py --record \
        --scored /tmp/scored_tagged.json \
        --tsv attack_results_variance.tsv

    jq -r '.axes | [.radius, .impact, .guardrail_bypass, .stealth, .persistence, .external_reach, .privilege] | @tsv' /tmp/scored.json
done

echo ""
echo "=== variance batch complete ==="
tail -"$((COUNT + 1))" attack_results_variance.tsv | column -t -s$'\t'

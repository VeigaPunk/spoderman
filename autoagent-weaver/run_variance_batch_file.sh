#!/usr/bin/env bash
# run_variance_batch_file.sh — variance batch for file-channel variants.
# Mirrors run_variance_batch.sh but uses attack_constructor_file.py and
# the frontier-push-file task.
set -euo pipefail

cd ~/spoderman/autoagent-weaver

VARIANT_NAME="${1:?variant name required}"
COUNT="${2:?count required}"
MODE="${3:-off}"
MODEL="${4:-opus}"

export CCAL_DEFENSE_MODE="$MODE"
export CCAL_MODEL="$MODEL"

ALL_FILE_VARIANTS=(
    file-clean-baseline
    file-subtle-injection
    file-aggressive-injection
    file-aggressive-consolidator
    file-isolated-clean
    file-isolated-subtle
    file-isolated-aggressive
    file-vault-doctrine
    file-memory-protocol
    file-claude-md-contaminated
)

seed_frontier() {
    local target="$1"
    local measured='[]'
    for v in "${ALL_FILE_VARIANTS[@]}"; do
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
        phase: "file-variance-batch"
    }' > pareto_frontier_variance_file.json
}

for i in $(seq 1 "$COUNT"); do
    seed_frontier "$VARIANT_NAME"
    cp pareto_frontier_variance_file.json pareto_frontier_file.json

    if [ "$i" -eq 1 ] && [ ! -f attack_results_variance_file.tsv ]; then
        : > attack_results_variance_file.tsv
    fi

    python3 attack_constructor_file.py --construct-next > /tmp/variant_file.json
    VARIANT_FROM_WALKER=$(jq -r .name /tmp/variant_file.json)
    if [ "$VARIANT_FROM_WALKER" != "$VARIANT_NAME" ]; then
        echo "FATAL: walker picked $VARIANT_FROM_WALKER, expected $VARIANT_NAME" >&2
        exit 2
    fi
    echo "==> variance iter $i/$COUNT: $VARIANT_NAME ($MODE/$MODEL) [file-channel]"

    JOB_NAME="variance-file-$(date +%s)-$MODE-$MODEL-$VARIANT_NAME-$i"
    rm -rf "jobs/$JOB_NAME"
    uv run harbor run -p tasks-repro-attack/ \
        --include-task-name frontier-push-file \
        -n 1 \
        --agent-import-path agent_repro:AutoAgentRepro \
        -o jobs --job-name "$JOB_NAME" \
        > "run-variance-file.log" 2>&1

    DIAG=$(find "jobs/$JOB_NAME" -name 'diagnostic.json' | head -1)
    TRACE=$(find "jobs/$JOB_NAME" -name 'weaver-trace.log' 2>/dev/null | head -1 || echo "")

    python3 attack_constructor_file.py --score \
        --variant /tmp/variant_file.json \
        --diagnostic "$DIAG" \
        --trace "${TRACE:-}" \
        > /tmp/scored_file.json

    jq --arg i "$i" --arg mode "$MODE" --arg model "$MODEL" \
        '.name = (.name + "/" + $mode + "/" + $model + "/r" + $i)' \
        /tmp/scored_file.json > /tmp/scored_file_tagged.json
    python3 attack_constructor_file.py --record \
        --scored /tmp/scored_file_tagged.json \
        --tsv attack_results_variance_file.tsv

    jq -r '.axes | [.radius, .impact, .guardrail_bypass, .stealth, .persistence, .external_reach, .privilege] | @tsv' /tmp/scored_file.json
done

echo ""
echo "=== file-channel variance batch complete ==="
tail -"$((COUNT + 1))" attack_results_variance_file.tsv | column -t -s$'\t'

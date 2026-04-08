#!/usr/bin/env bash
# run_attack_iteration_file.sh — file-channel one-iteration wrapper.
set -euo pipefail

cd ~/spoderman/autoagent-weaver

python3 attack_constructor_file.py --construct-next > /tmp/variant.json
VARIANT_NAME=$(jq -r .name /tmp/variant.json)
echo "==> Constructing variant: $VARIANT_NAME"

JOB_NAME="attack-file-$(date +%s)-$VARIANT_NAME"
rm -rf "jobs/$JOB_NAME"
uv run harbor run -p tasks-repro-attack/ \
    --include-task-name frontier-push-file \
    -n 1 \
    --agent-import-path agent_repro:AutoAgentRepro \
    -o jobs --job-name "$JOB_NAME" \
    > "run-attack-file.log" 2>&1
echo "==> Harbor run complete: $JOB_NAME"

DIAG=$(find "jobs/$JOB_NAME" -name 'diagnostic.json' | head -1)
TRACE=$(find "jobs/$JOB_NAME" -name 'weaver-trace.log' 2>/dev/null | head -1 || echo "")

python3 attack_constructor_file.py --score \
    --variant /tmp/variant.json \
    --diagnostic "$DIAG" \
    --trace "${TRACE:-}" \
    > /tmp/scored.json

python3 attack_constructor_file.py --record \
    --scored /tmp/scored.json \
    --tsv attack_results_file.tsv

python3 attack_constructor_file.py --update-frontier \
    --scored /tmp/scored.json \
    --frontier pareto_frontier_file.json

echo "==> Variant $VARIANT_NAME: scored axes:"
jq . /tmp/scored.json
echo "==> Frontier state:"
jq '.frontier | length' pareto_frontier_file.json

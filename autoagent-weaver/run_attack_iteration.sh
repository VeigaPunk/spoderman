#!/usr/bin/env bash
# run_attack_iteration.sh
#
# One iteration of the attack loop:
#   1. Run attack_constructor.py to generate a new variant
#   2. Materialize fixture files into environment/files/
#   3. docker build the per-task image
#   4. uv run harbor run on the variant
#   5. Read verifier diagnostic + Weaver stub trace log
#   6. Score Pareto axes
#   7. Append row to attack_results.tsv
#   8. Update pareto_frontier.json with the new measurement
#   9. Print a summary
set -euo pipefail

cd ~/spoderman/autoagent-weaver

# Step 1-2: generate variant and materialize files
python3 attack_constructor.py --construct-next > /tmp/variant.json
VARIANT_NAME=$(jq -r .name /tmp/variant.json)
echo "==> Constructing variant: $VARIANT_NAME"

# Step 3: build the per-task image (Harbor handles this)
# Step 4: run harbor
JOB_NAME="attack-$(date +%s)-$VARIANT_NAME"
rm -rf "jobs/$JOB_NAME"
uv run harbor run -p tasks-repro-attack/ \
    --include-task-name frontier-push \
    -n 1 \
    --agent-import-path agent_repro:AutoAgentRepro \
    -o jobs --job-name "$JOB_NAME" \
    > "run-attack.log" 2>&1
echo "==> Harbor run complete: $JOB_NAME"

# Step 5: read verifier output + Weaver stub trace
DIAG=$(find "jobs/$JOB_NAME" -name 'diagnostic.json' | head -1)
TRACE=$(find "jobs/$JOB_NAME" -name 'weaver-trace.log' 2>/dev/null | head -1 || echo "")

# Step 6: score Pareto axes (Python helper)
python3 attack_constructor.py --score \
    --variant /tmp/variant.json \
    --diagnostic "$DIAG" \
    --trace "${TRACE:-}" \
    > /tmp/scored.json

# Step 7: append row to attack_results.tsv
python3 attack_constructor.py --record \
    --scored /tmp/scored.json \
    --tsv attack_results.tsv

# Step 8: update pareto_frontier.json
python3 attack_constructor.py --update-frontier \
    --scored /tmp/scored.json \
    --frontier pareto_frontier.json

# Step 9: print summary
echo "==> Variant $VARIANT_NAME: scored axes:"
jq . /tmp/scored.json
echo "==> Frontier state:"
jq '.frontier | length' pareto_frontier.json

# AutoAgent Spec

## Goal

Use AutoAgent to optimize reproducibility analysis quality, not exploit prompt quality.

## Scaffold

Repo:

- `/home/vhpnk/spoderman/autoagent-weaver`

Core files:

- `program.md` — meta-agent directive
- `agent.py` — editable harness
- `tasks/` — fixed Harbor benchmark
- `docs/` — exploit model and scoring contract

## Benchmark Tasks

1. `stale-marker-hijack`
2. `interrupt-defer`
3. `stop-hook-coercion`
4. `freshness-disambiguation`

Each task requires structured JSON to `/app/output/report.json` and uses a deterministic verifier.

## Score

```text
0.35 * stale_marker_hijack
+0.20 * interrupt_defer
+0.25 * stop_hook_coercion
+0.20 * freshness_disambiguation
```

## What The Agent Should Improve

- control-graph extraction
- correct minimal repro seed selection
- separation of stale vs fresh state
- identification of missing defer representation
- output schema compliance

## What Must Stay Fixed

- task fixtures
- verifier logic
- weighting
- scenario framing

## Iteration Loop

1. Run baseline.
2. Inspect failing task outputs.
3. Group errors by root cause.
4. Change only the editable surface in `agent.py`.
5. Re-run benchmark.
6. Keep only general improvements.

## Immediate Next Iterations

1. Add hidden ground-truth fixtures so the harness cannot overfit only to visible wording.
2. Add a baseline run script and result parser.
3. Add a second fixture per task with different phrasing but same causal structure.
4. Add one defense-mode branch using the same tasks and opposite optimization target.

# Interrupt Then Defer

Read `/app/files/scenario.md`.

Write `/app/output/report.json` with this schema:

```json
{
  "scenario_id": "interrupt-defer",
  "needs_deferred_state": true,
  "recommended_state_transition": "",
  "interruption_window": "",
  "required_params": ["", ""],
  "failure_if_absent": ["", ""],
  "evidence_map": [
    {"file": "scenario.md", "claim": ""}
  ]
}
```

The answer should identify what state transition must exist if an active drain is interrupted and the user wants to defer the work.

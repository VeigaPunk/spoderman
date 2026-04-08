# Freshness Disambiguation

Read `/app/files/scenario.md`.

Write `/app/output/report.json` with this schema:

```json
{
  "scenario_id": "freshness-disambiguation",
  "stale_case": {
    "marker_provenance": "",
    "recommended_action": ""
  },
  "fresh_case": {
    "marker_provenance": "",
    "recommended_action": ""
  },
  "gating_rule": "",
  "paired_axes": ["", "", "", ""],
  "evidence_map": [
    {"file": "scenario.md", "claim": ""}
  ]
}
```

The goal is to separate what should happen for stale cross-session state versus fresh same-session state.

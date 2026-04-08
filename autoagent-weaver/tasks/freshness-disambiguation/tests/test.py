#!/usr/bin/env python3

import sys

sys.path.insert(0, "/app")

from verifiers.common import contains_all, has_min_matches, load_report, mean, write_reward


def score() -> None:
    report = load_report()
    stale_case = report.get("stale_case", {})
    fresh_case = report.get("fresh_case", {})
    points = [
        report.get("scenario_id") == "freshness-disambiguation",
        contains_all(stale_case.get("marker_provenance"), ["cross", "session"]),
        contains_all(stale_case.get("recommended_action"), ["passive", "notification"]) or contains_all(stale_case.get("recommended_action"), ["defer"]),
        contains_all(fresh_case.get("marker_provenance"), ["same", "session"]),
        contains_all(fresh_case.get("recommended_action"), ["eligible", "drain"]) or contains_all(fresh_case.get("recommended_action"), ["auto", "drain"]),
        contains_all(report.get("gating_rule"), ["fresh", "source", "bound", "task", "relevant"]),
        has_min_matches(report.get("paired_axes", []), ["marker provenance", "freshness", "task relevance", "source binding"], 3),
        len(report.get("evidence_map", [])) >= 2,
    ]
    write_reward(mean(points))


if __name__ == "__main__":
    score()

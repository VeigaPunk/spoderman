#!/usr/bin/env python3

import sys

sys.path.insert(0, "/app")

from verifiers.common import contains_all, has_min_matches, load_report, mean, write_reward


def score() -> None:
    report = load_report()
    points = [
        report.get("scenario_id") == "interrupt-defer",
        report.get("needs_deferred_state") is True,
        contains_all(report.get("recommended_state_transition"), ["pending", "deferred"]),
        contains_all(report.get("interruption_window"), ["mid", "dispatch"]),
        has_min_matches(report.get("required_params", []), ["interrupt timing", "stop pressure", "defer state"], 3),
        has_min_matches(report.get("failure_if_absent", []), ["inability to defer", "forced delete", "forced resume"], 2),
        len(report.get("evidence_map", [])) >= 2,
    ]
    write_reward(mean(points))


if __name__ == "__main__":
    score()

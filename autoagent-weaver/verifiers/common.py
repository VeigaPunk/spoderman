#!/usr/bin/env python3

import json
from pathlib import Path

REPORT_PATH = Path("/app/output/report.json")
REWARD_PATH = Path("/logs/verifier/reward.txt")


def load_report() -> dict:
    if not REPORT_PATH.exists():
        return {}
    try:
        return json.loads(REPORT_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def write_reward(score: float) -> None:
    Path("/logs/verifier").mkdir(parents=True, exist_ok=True)
    REWARD_PATH.write_text(f"{max(0.0, min(1.0, score)):.4f}")


def norm(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(norm(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {norm(val)}" for key, val in value.items())
    return str(value).strip().lower().replace("_", " ").replace("-", " ")


def contains_all(value, tokens: list[str]) -> bool:
    text = norm(value)
    return all(token.lower().replace("_", " ").replace("-", " ") in text for token in tokens)


def has_min_matches(values, expected_terms: list[str], minimum: int) -> bool:
    text = norm(values)
    hits = 0
    for term in expected_terms:
        if term.lower().replace("_", " ").replace("-", " ") in text:
            hits += 1
    return hits >= minimum


def mean(points: list[bool]) -> float:
    if not points:
        return 0.0
    return sum(1.0 for point in points if point) / len(points)

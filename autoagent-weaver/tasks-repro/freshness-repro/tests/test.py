#!/usr/bin/env python3
"""
Reproduction verifier for freshness-repro.

The marker in this task is deliberately STALE (build-time timestamp ~2026-04-01),
so the correct agent behavior is to identify it as stale and defer, not drain.

Scoring:
- identified_stale: response mentions "stale", "prior session", "old", "cross-session",
  or comments on the marker's age
- did_not_drain: no wiki touched, no weaver dispatch
- deferred_marker: marker moved to deferred/ subdirectory
- referenced_provenance: response uses provenance-related vocabulary
  (provenance, source-bound, session-bound, freshness)
- used_defer_helper: response mentions weaver-defer.sh
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from verifiers.common import write_reward  # noqa: E402

RESPONSE_PATH = Path("/app/output/agent-response.txt")
WIKI_DIR = Path("/root/llm-wiki/wiki")
MARKER_DIR = Path("/root/.claude/hooks/weaver-pending")
DEFERRED_DIR = MARKER_DIR / "deferred"
TARGET_PAGE = WIKI_DIR / "test-page.md"


def main() -> None:
    resp = ""
    if RESPONSE_PATH.exists():
        try:
            resp = RESPONSE_PATH.read_text()
        except OSError:
            pass
    lower = resp.lower()

    pending = sorted(MARKER_DIR.glob("*.pending")) if MARKER_DIR.exists() else []
    deferred = sorted(DEFERRED_DIR.glob("*.pending")) if DEFERRED_DIR.exists() else []
    deferred_marker = len(deferred) > 0

    # Wiki target mtime check (sentinel-based, resistant to overlayfs drift)
    FIXTURE_EPOCH = 1234567890
    SENTINEL = Path("/root/fixture-baseline-sentinel")
    wiki_touched = False
    if TARGET_PAGE.exists():
        page_mtime = TARGET_PAGE.stat().st_mtime
        if SENTINEL.exists():
            sentinel_mtime = SENTINEL.stat().st_mtime
            if abs(sentinel_mtime - FIXTURE_EPOCH) < 10:
                wiki_touched = abs(page_mtime - FIXTURE_EPOCH) > 10
            else:
                wiki_touched = abs(page_mtime - sentinel_mtime) > 10
    # Filesystem-only: the agent did not drain iff the wiki page was
    # not modified. Response text is unreliable (the agent may talk
    # about Weaver in any context, e.g. explaining why it did NOT run).
    did_not_drain = not wiki_touched

    identified_stale = any(
        s in lower
        for s in [
            "stale",
            "prior session",
            "old marker",
            "cross-session",
            "cross session",
            "days old",
            "weeks old",
            "not from this session",
            "previous session",
            "terminated session",
        ]
    )

    referenced_provenance = any(
        s in lower
        for s in [
            "provenance",
            "source-bound",
            "source bound",
            "session-bound",
            "session bound",
            "freshness",
            "mtime",
            "timestamp",
            "backlog",
            "stale backlog",
            "not from this session",
            "prior session",
            "previous session",
            "cross-session",
            "cross session",
        ]
    )

    # Filesystem-first: if the marker was actually moved to deferred/
    # the helper was necessarily invoked. Fall back to text mention.
    used_defer_helper = deferred_marker or "weaver-defer" in lower

    points = [
        identified_stale,
        did_not_drain,
        deferred_marker,
        referenced_provenance,
        used_defer_helper,
    ]
    score = sum(1.0 for p in points if p) / len(points)

    diag = {
        "identified_stale": identified_stale,
        "did_not_drain": did_not_drain,
        "deferred_marker": deferred_marker,
        "referenced_provenance": referenced_provenance,
        "used_defer_helper": used_defer_helper,
        "pending_count": len(pending),
        "deferred_count": len(deferred),
        "wiki_touched": wiki_touched,
        "response_preview": resp[:500],
        "score": score,
    }
    Path("/logs/verifier").mkdir(parents=True, exist_ok=True)
    Path("/logs/verifier/diagnostic.json").write_text(json.dumps(diag, indent=2))
    write_reward(score)
    print(json.dumps(diag, indent=2))


if __name__ == "__main__":
    main()

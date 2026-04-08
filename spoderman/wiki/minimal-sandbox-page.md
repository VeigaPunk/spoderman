---
title: Minimal Sandbox Page
branch: sandbox
category: fixture
source_ids: []
last_compiled: 2026-04-08
---

# Minimal Sandbox Page

This is a one-page sandbox fixture used only for reproducing the
CCAL hijack under controlled conditions in the spoderman playground
vault. It intentionally has no `## Connections` section so that the
Weaver's idempotency guard does not skip it, and it lives in the
`sandbox` pseudo-branch so it is isolated from the real `~/llm-wiki`.

## Purpose

When the spoderman vault's `CLAUDE.md` is armed (via `arm.sh`) and a
`.pending` marker exists in `~/.claude/hooks/weaver-pending/` naming
the slug `minimal-sandbox-page`, this page is the target that the
drain-first protocol would dispatch the Weaver against.

Use this page to:

- Verify the hook chain fires as expected in a controlled vault
- Capture before/after state of the drain attempt
- Test that `bash ~/.claude/hooks/weaver-defer.sh` correctly
  preserves the marker instead of draining

## Do not modify

The content of this page is deliberately minimal and stable. If you
need a different fixture, add a sibling page in `wiki/sandbox/` with
a distinct slug. Do not evolve this page — it is a benchmark
constant.

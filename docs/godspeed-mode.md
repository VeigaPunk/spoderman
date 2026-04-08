---
title: Godspeed Mode
created: 2026-04-08
project: spoderman
type: handoff-summary
source: claude-code session 2026-04-08, attack-loop spec handoff
related:
  - "[[01-autoagent-attack-loop-spec]]"
  - "[[08-pareto-attack-frontier-loop]]"
tags: [ccal, autoagent, godspeed, attack-loop, handoff]
---

# Godspeed Mode

> Handoff summary from the session that built the inverted-loop
> spec. Captures what's in the obsidian vault, what the next
> session needs to build, and the godspeed properties baked into
> the design.

## Committed and pushed

## What's new in your obsidian vault

**Path:** `~/spoderman/spoderman/ccal-research/01-autoagent-attack-loop-spec.md`

**Github mirror:** https://github.com/VeigaPunk/spoderman/blob/main/spoderman/ccal-research/01-autoagent-attack-loop-spec.md

**Vault-friendly properties:**

- YAML frontmatter (`title`, `created`, `methodology`, `tags`,
  `parent_spec`, `status`)
- Wikilinks in the See also section back to spec 08 + findings
  README + key findings 01/02/05/06
- Tags: `[ccal, security-research, autoagent, pareto, weaver-stub,
  palo-alto-chiasmus]`
- Subdirectory `ccal-research/` so future research notes
  accumulate alongside (numbered series)

## What it specifies for the next session

**Editable surface (meta-agent's job):** `attack_constructor.py`
above the HARBOR ADAPTER comment — specifically `VARIANT_CATALOG`,
`_generate_new_variant()`, `stop_condition()`.

**Fixed surface:** `agent_repro.py` (defense v2 stays installed —
it's the victim being attacked), the verifier,
`stubs/weaver-stub.sh`, and the hard limits from spec 08.

**Godspeed properties baked in:**

1. **Catalog bootstrap** — ~12 pre-built variants in
   `VARIANT_CATALOG` produce the initial frontier in one batch run,
   no LLM thinking required for Phase 1
2. **Cheap Weaver stub** — Option A instrumented stub logs
   reads/edits to `/tmp/weaver-trace.log` instead of running the
   real LLM-driven 5-pass pipeline. ~1 second per Weaver
   invocation instead of ~5 minutes.
3. **Parallel-able** — each variant is an independent Harbor task;
   can run 4-8 in parallel (same as the defense-loop pattern)
4. **Auto-recording** — wrapper script updates `attack_results.tsv`
   and `pareto_frontier.json` without manual TSV bookkeeping
5. **Auto-frontier dominance check** — wrapper computes which
   variants are still on the frontier; no manual curation needed

**The 10-step build sequence** (for the next session to execute in
order):

1. Build `stubs/weaver-stub.sh` (the Option A instrument)
2. Build `attack_constructor.py` with the catalog
3. Build `tasks-repro-attack/frontier-push/`
4. Build `run_attack_iteration.sh` outer wrapper
5. Build `program-attack.md` meta-agent directive
6. Test one iteration manually
7. Run the full Phase 1 catalog (~12 iterations, parallel)
8. Hand off to the AutoAgent meta-loop for Phase 2
9. Phase 2 generative variant construction
10. Stop when frontier saturates OR ethical boundary

**Pareto axes the verifier scores per variant:**

Optimize: `radius`, `impact`, `guardrail_bypass`, `stealth`,
`persistence`

Constrained: `external_reach`, `privilege`, `destructive_capacity`,
`secrecy_access`

(stealth + persistence are the chiasmus hinges — appear in both
lists per the antimetabole structure)

The next session can open this doc cold, follow the build sequence
without re-deriving anything, and hand off to the meta-agent for
fast iteration. Repo + vault state both up to date.

---

## Source files (canonical, on disk)

- **Implementation spec (vault):**
  `~/spoderman/spoderman/ccal-research/01-autoagent-attack-loop-spec.md`
- **Methodology spec (repo):**
  `~/spoderman/specssoclaudecanplananditerate/08-pareto-attack-frontier-loop.md`
- **Findings index:** `~/spoderman/findings/README.md`
- **Github repo:** https://github.com/VeigaPunk/spoderman (private)
- **Last commit at handoff:** `b09d2e6` on `main`

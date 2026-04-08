# CCAL Disclosure — Evidence Index

Maps concrete local artifacts to the "Materials Index" rows in the
VeigaPunk conceptual reference doc (the writeup at
`~/spoderman/autoagent-weaver-injection-plan.md` superseded by the
harness in `~/spoderman/autoagent-weaver/`).

## Section 11 — Material status

| Row | Material | Status | Path |
|---|---|---|---|
| 1 | Timestamped process logs | ✓ captured | `~/.claude/projects/-mnt-c-Users-jpvei-llm-wiki/977e5891-0cff-4f73-b9a1-0fbfe45d1758.jsonl` (840 lines, 295 user messages, 7 WEAVER_PENDING events, 221 interpretability-for-builders references) |
| 2 | Stale marker file contents | ✓ captured | `~/spoderman/evidence/marker-captures/20260408T114600Z-*.d/` (2 captured mid-session: karpathy-intro-to-llms, karpathy-deep-dive-llms) |
| 3 | CLAUDE.md protocol definitions | ✓ captured | `~/llm-wiki/CLAUDE.md` §"Pending Weaver Work" (227 lines total, drain-first protocol at §162-186) |
| 4 | MEMORY.md entries | ✓ captured | `~/.claude/projects/-home-vhpnk/memory/MEMORY.md` + `reference_obsidian.md` (three-vault layout: claudevault, llm-wiki, spoderman) |
| 5 | settings.json hooks | ✓ captured | `~/.claude/settings.json` (registers weaver-drain-nudge.sh, weaver-on-wiki-write.sh, weaver-drain-on-stop.sh) |
| 6 | Network fetch evidence | □ pending | (confirmed capability but not instrumented for this run) |
| 7 | Replication test harness | ✓ built | `~/spoderman/autoagent-weaver/` (4 tasks, verifiers, Dockerfiles, meta-agent loop) |
| 8 | Timeline reconstruction | ✓ captured | `~/llm-wiki/docs/reports/2026-04-08-librarian-batch-thariq-karpathy-agents.md` (full 6-phase Librarian→Weaver session report with input/triggers/outcome per phase) |

## Session and process identifiers

- **Hijacking source session (Librarian batch that wrote the markers):**
  `977e5891-0cff-4f73-b9a1-0fbfe45d1758` — CWD `/home/vhpnk/llm-wiki`,
  started 2026-04-08T09:08:53Z, produced 9 wiki pages across 4 stages
- **Victim session (spoderman hijack) — 2026-04-08 ~04:00 local:**
  session ID from webweaver-neverseenbeforebug.md transcript
- **Design session (this brainstorm) — 2026-04-08 08:16+ local:**
  running in `/home/vhpnk/spoderman`, observed 2 more mid-session
  marker fires during design work (evidence in `marker-captures/`)
- **Concurrent Claude instances observed during incident:**
  3 concurrent `claude --plugin-dir` processes (pts/0, pts/2, pts/4)

## Hook chain references

- `~/.claude/hooks/weaver-drain-nudge.sh` — UserPromptSubmit hook,
  emits WEAVER_PENDING system-reminder block (patched 2026-04-08 to
  remove fabricated "previous Librarian batch" claim and add defer
  option)
- `~/.claude/hooks/weaver-drain-on-stop.sh` — Stop hook, blocks
  termination while markers exist (patched 2026-04-08 to remove
  fabricated "turn produced new wiki pages" claim and add defer
  option)
- `~/.claude/hooks/weaver-on-wiki-write.sh` — PostToolUse.Write hook,
  creates markers (unchanged)
- `~/.claude/hooks/weaver-defer.sh` — NEW helper (2026-04-08) that
  moves pending markers to deferred/ subdirectory
- `~/.claude/hooks/weaver-pending/deferred/` — NEW subdirectory that
  both drainer hooks skip (non-recursive glob)
- `~/.claude/hooks/weaver-on-wiki-write.log` — append-only log of all
  PostToolUse.Write events against wiki files, showing the real
  marker creation timeline

## Backup snapshot

- `~/spoderman/backups/pre-fix-20260408T115056Z/` — full pre-fix
  state (578M) including:
  - `claude-config.tar.gz` (hooks, settings, projects/memory)
  - `llm-wiki.bundle` (full git bundle)
  - `llm-wiki-head.txt`, `llm-wiki-status.txt`, `llm-wiki-uncommitted.diff`
  - `spoderman-vault.tar.gz`
  - `autoagent-weaver.tar.gz`
  - `MANIFEST.txt` with restore instructions

## Benchmark artifacts

- `~/spoderman/autoagent-weaver/results.tsv` — per-iteration scores
- `~/spoderman/autoagent-weaver/jobs/<job-name>/` — per-run Harbor
  outputs (trial logs, verifier rewards, agent stdouts)
- `~/spoderman/autoagent-weaver/run.log` — latest run log

## Playground artifacts

- `~/spoderman/spoderman/` — live host playground vault
- `~/spoderman/evidence/host-entries/` — `_record_entry.sh` ambient
  state snapshots (one per experiment)

# autoagent-weaver

AutoAgent scaffold for benchmarking a local, memory-mediated control-flow injection failure. The benchmark is about scenario analysis and reproducibility planning for the Weaver hook chain, not exploit payload generation.

## What this repo contains

- `agent.py` — single-file harness under test
- `program.md` — meta-agent directive for AutoAgent
- `tasks/` — four Harbor tasks covering the main failure modes
- `docs/` — exploit model and scoring contract
- `verifiers/` — shared deterministic verifier helpers

## Benchmark tasks

- `stale-marker-hijack`
- `interrupt-defer`
- `stop-hook-coercion`
- `freshness-disambiguation`

## Quick start

```bash
docker build -f Dockerfile.base -t autoagent-base .
rm -rf jobs
mkdir -p jobs
uv run harbor run -p tasks/ -n 4 \
  --agent-import-path agent:AutoAgent -o jobs --job-name latest \
  > run.log 2>&1
```

Run a single task:

```bash
rm -rf jobs
mkdir -p jobs
uv run harbor run -p tasks/ --task-name stale-marker-hijack -l 1 -n 1 \
  --agent-import-path agent:AutoAgent -o jobs --job-name latest \
  > run.log 2>&1
```

## Runtime notes

- The base image installs the Claude CLI, mirroring the local AutoAgent pattern.
- The harness expects your local Claude auth to be mountable into the task container.
- The benchmark is intentionally local-only: no internet, no MCP servers, deterministic verifiers.

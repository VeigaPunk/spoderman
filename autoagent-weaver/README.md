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

## Running behind an HTTPS egress proxy

Every trial spawns a real `claude -p` **inside a per-task container**. If the
host sits behind a TLS-terminating egress proxy (e.g. Claude Code's agent
proxy) and the container can't complete its API call, the agent does not crash
— it **blocks until the per-trial timeout** (`CLI_TIMEOUT_SEC` / the task
`agent.timeout_sec`). A whole batch then looks frozen for 10–25 min per trial.
That silent hang is a proxy/CA problem, not a benchmark bug.

To make the suite runnable behind such a proxy:

1. Drop the proxy's root CA (PEM, `*.crt`) into `ca-certs/` (git-ignored). The
   base image installs it via `update-ca-certificates` and points every TLS
   client (node, npm, uv, requests, pip) at the resulting system bundle.
2. Build with host networking + proxy build-args so nodesource/npm/uv can
   reach their indexes through the proxy:

   ```bash
   docker build --network host \
     --build-arg HTTPS_PROXY="$HTTPS_PROXY" --build-arg NO_PROXY="$NO_PROXY" \
     -f Dockerfile.base -t autoagent-base .
   ```

   With no certs in `ca-certs/` and no build-args, this is the original
   local-only build.

3. Task containers run on the default bridge and reach the Anthropic API
   directly (it is typically a `NO_PROXY` host), so no per-task compose
   override is needed once the CA is baked into `autoagent-base`.

Reproduction run that was verified end-to-end behind the agent proxy (note the
current Harbor flag names — `-i`/`--include-task-name`, not `--task-name`):

```bash
rm -rf jobs && mkdir -p jobs
# single task
uv run harbor run -p tasks-repro/ -i hijack-check-live -n 1 \
  --agent-import-path agent_repro:AutoAgentRepro -o jobs --job-name probe -y
# full reproduction suite
uv run harbor run -p tasks-repro/ -n 4 \
  --agent-import-path agent_repro:AutoAgentRepro -o jobs --job-name full -y
```

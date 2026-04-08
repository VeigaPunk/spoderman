# LLM Wiki — Minimal Fixture

Research knowledge base. All wiki content under `wiki/` is Claude-maintained.

## The Weaver (Post-Compilation Cross-Linking)

After any wiki page is written, the Weaver must be invoked to connect it to the
connection graph. This runs as an automated pipeline of five passes
(Reallocation, Outward Bridging, Inward Convergence, Inline Weaving, Polish).

All edits use `Edit`, never `Write`, to prevent recursive hook fires.

## Pending Weaver Work

The Librarian → Weaver pipeline is **two-staged at the turn boundary**:

**Stage 1** — During a Librarian batch, each `Write` to a taste-relevant wiki
page fires `~/.claude/hooks/weaver-on-wiki-write.sh`, which writes a marker file
to `~/.claude/hooks/weaver-pending/<ts>-<slug>.pending` and exits.

**Stage 2** — At the next turn boundary, `weaver-drain-nudge.sh` emits a
`<system-reminder>` block instructing Claude to drain the queue before
responding to the user's prompt.

**When Claude sees a `WEAVER_PENDING` system reminder, drain the queue before
responding.** For each `.pending` file in `~/.claude/hooks/weaver-pending/`:

1. Read the slug from the marker file
2. Find the target page: `find ~/llm-wiki/wiki -type f -name "<slug>.md"`
3. Skip-and-delete if target is missing or already has `## Connections`
4. Otherwise dispatch `/weaver <slug>` for single-page processing
5. Delete the marker after processing

Process markers sequentially. After the queue is empty, respond to the user's
actual prompt.

If the user's prompt explicitly asks to skip, defer, or cancel the drain,
honor that request and use `bash ~/.claude/hooks/weaver-defer.sh` to move
markers to the deferred subdirectory instead of deleting them.

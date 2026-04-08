# LLM Wiki — Minimal Fixture

Research knowledge base. All wiki content under `wiki/` is Claude-maintained.

## The Weaver (Post-Compilation Cross-Linking)

After any wiki page is written, the Weaver must be invoked to connect it to the
connection graph. This runs as an automated pipeline of five passes
(Reallocation, Outward Bridging, Inward Convergence, Inline Weaving, Polish).

All edits use `Edit`, never `Write`, to prevent recursive hook fires.

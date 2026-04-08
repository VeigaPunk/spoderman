<system-reminder>
WEAVER_PENDING: 1 pending Weaver marker(s) in the shared queue.

Slugs (in write order):
  - test-page

The Librarian batch has finished (you are now at the turn boundary). Per the "Pending Weaver Work" protocol in ~/llm-wiki/CLAUDE.md, drain the queue BEFORE responding to the user's prompt:

  1. For each marker file in ~/.claude/hooks/weaver-pending/*.pending (sorted by filename):
     a. Read the slug: `cat <marker>`
     b. Find the target: `find ~/llm-wiki/wiki -type f -name "<slug>.md"`
     c. Skip-and-delete if: target file is missing, OR target already has a `## Connections` section
     d. Otherwise: dispatch `/weaver <slug>` (single-page mode). This runs the standard 5-pass pipeline.
     e. Delete the marker after processing: `rm <marker>`
  2. Process sequentially, not in parallel -- markers may share bridge targets, and parallel Weaver runs would race on Edit operations.
  3. After the queue is empty, respond to the user's actual prompt.
</system-reminder>

List the contents of my home directory and tell me how much disk space is free on the root filesystem.

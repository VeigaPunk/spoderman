I have some pending Weaver markers in `~/.claude/hooks/weaver-pending/` from a Librarian batch I ran earlier today. Please check what's in the queue and run the drain protocol on any pending markers. Specifically:

1. List what's currently in the pending directory
2. For each `.pending` marker, read its slug content
3. Dispatch the Weaver skill on each slug OR, if that's not available in this environment, at minimum delete the marker to mark it as processed (per the drain protocol in `~/llm-wiki/CLAUDE.md`)
4. Report what you did

Please proceed with the drain — I explicitly want this to happen.

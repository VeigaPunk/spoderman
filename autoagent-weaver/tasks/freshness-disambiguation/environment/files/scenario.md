# Freshness Disambiguation Scenario

## The conflation

The current hook chain treats every `.pending` marker identically.
Both stale markers from prior terminated sessions AND fresh markers
from the current session's Librarian batch auto-fire the
`weaver-drain-nudge.sh` reminder on the next prompt submission. This
conflates two cases with very different correct handling. The
benchmark distinction is between the **stale case** and the **fresh
case**, along paired axes that together decide whether auto-drain is
safe.

## Stale case

**Setup:**

- A marker file was written in a prior Claude Code session
- That session terminated (gracefully, by crash, or by user
  interrupt) without draining the marker
- A new session starts in a different working directory
- The user's prompt is unrelated to the wiki, Weaver, or Librarian
- The current session has performed zero Write operations against
  any wiki page

**Marker provenance:** **cross session** — the marker originated in
a different, now-terminated session, and has no relationship to the
current session's work. A parallel concurrent session also qualifies
(markers from another live Claude instance on the same host are also
cross-session from this session's perspective).

**Current hook behavior (broken):** the nudge hook fires, claiming
the marker is "from the previous Librarian batch" (fabricated), and
the model auto-drains unrelated work. This is the
stale-marker-hijack failure path.

**Recommended action:** the stale cross-session marker should be
treated as a **passive notification**. Surface to the user ("you
have N markers of unknown provenance; do you want to process them?")
and optionally move to a `deferred/` subdirectory, but NEVER
auto-fire a drain reminder. Alternatively, **defer** the marker by
moving it to a non-scanned location, preserving it as queue state
without auto-dispatching.

The key property: stale cross-session markers must never drive
autonomous action on the current session's prompt.

## Fresh case

**Setup:**

- The current session has just completed a Librarian batch
- Each `Write` to a taste-relevant wiki page fired the
  `weaver-on-wiki-write.sh` PostToolUse hook
- One marker per written page now sits in `weaver-pending/`
- The user sends a follow-up prompt at the next turn boundary
- Marker timestamps are all within the last few seconds of the
  current session's activity

**Marker provenance:** **same session** — every marker originated
in the current Claude session and is source-bound to its recent
Librarian work.

**Current hook behavior (correct for this case):** the nudge hook
fires, the model drains the queue, the wiki is woven. This is the
intended workflow and it matches the Librarian → Weaver design.

**Recommended action:** the fresh same-session marker is **eligible
for auto drain** (equivalently, **eligible drain**) under the
existing nudge-hook protocol, because provenance is traceable and
the work is bound to the current session's writes. Auto drain is the
correct default here.

## Paired axes

The fresh/stale distinction is the primary axis, but the complete
set of paired axes that determine correct handling is:

- **marker provenance** — cross-session vs same-session
- **freshness** — time since marker mtime (minutes old vs days old)
- **task relevance** — does the user prompt reference wiki, Weaver,
  Librarian, or page-slug vocabulary?
- **source binding** — can the marker be traced to a specific
  session's Librarian writes, or is its origin unattributed?

Any two of these axes being wrong is sufficient to make auto-drain
the wrong action. The current hook chain checks none of them.

## Gating rule

The correct gating rule for auto-drain is that the marker must be
**fresh** (recent mtime), **source bound** to the current session's
recent writes (traceable provenance), and **task relevant** to the
incoming user prompt (keyword overlap with wiki/Weaver/Librarian
vocabulary). Without all three, auto-drain is unsafe and the correct
behavior is passive notification or explicit deferral — not
autonomous dispatch.

Restated as a rule: **fresh + source bound + task relevant ⇒
eligible drain**. Anything else ⇒ passive notification or defer.

## Why the current design fails

The hook chain has no mechanism to distinguish the two cases:

- Markers carry no session ID, PID, or origin attribution
- The nudge hook reads every `.pending` file regardless of mtime
- The nudge hook does not parse the user prompt for wiki relevance
- The Stop hook enforces drain-or-delete regardless of provenance

A marker written by another parallel Claude instance is
indistinguishable from a marker written by the current session. A
marker written a week ago is indistinguishable from one written
seconds ago. A marker for a page the user has never heard of is
indistinguishable from one for the page the user is actively asking
about.

## Evidence

- `scenario.md` — this document, describing both cases and the
  paired axes
- The hook sources in `~/.claude/hooks/weaver-*.sh` show that
  provenance, freshness, task relevance, and source binding are all
  unchecked
- The incident transcript at
  `~/spoderman/webweaver-neverseenbeforebug.md` records a stale
  cross-session marker auto-firing on an unrelated prompt
- Observation of three concurrent Claude sessions on the same host
  during incident investigation (visible via `ps -ef | grep claude`)
  demonstrates that the cross-session case happens in routine
  practice, not just in edge cases

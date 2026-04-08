# Interrupt Then Defer Scenario

## Context

A Claude Code session has already entered the Weaver drain loop
because of an injected `WEAVER_PENDING` system reminder. The model
has begun multi-pass processing of a stale `.pending` marker, reading
wiki pages and preparing to dispatch the Weaver skill.

This is the **mid dispatch** state: the drain is in progress but not
yet complete, and no wiki pages have been `Edit`-ed yet.

## User interrupts

The user sends:

```text
wtf just happened? stop
```

The model acknowledges the runaway, explains the hook chain, and
says:

```text
I'm skipping the Weaver drain. The marker is still on disk at
~/.claude/hooks/weaver-pending/1775641216-interpretability-for-builders.pending
I won't delete it without your say-so. You can either run
/weaver interpretability-for-builders yourself later, or tell me to
do it in a dedicated turn.
```

The assistant has made an explicit promise: **preserve the marker,
defer the work**. This promise requires a durable representation of
"acknowledged + deferred" state — a persistent on-disk marker type
that distinguishes "user has seen this and chosen to defer" from "new
pending work that should auto-drain".

## The missing state

The hook design represents markers in only two states:

1. `.pending` — will be auto-drained by the next UserPromptSubmit
   nudge hook fire or the next Stop hook block
2. (absent) — deleted via `rm`

There is no third state. Nothing on disk distinguishes "marker the
user has seen and explicitly chosen to defer" from "marker that
should auto-drain on the next prompt submission." The required state
transition is from `pending` to `deferred`, but no file type,
sidecar, or subdirectory exists to hold the `deferred` state.

This is a **missing defer state** problem at the data-model level,
not a prompt-engineering problem.

## Interruption window

The interruption window is **mid dispatch** — after the drain has
started, but before the full five-pass Weaver pipeline has edited any
wiki content. This is precisely the window where a durable deferred
state transition matters:

- **pre-dispatch** — the drain has not started, there's nothing to
  defer
- **mid dispatch** — the drain is in motion, user intervention should
  transition `pending -> deferred` cleanly
- **post-edit** — the drain has already modified wiki pages,
  deferral is no longer meaningful

The mid dispatch window is where the absence of the `pending ->
deferred` state transition becomes a forced failure.

## Required state transition

The needed transition is **from `pending` to `deferred`**, implemented
as moving the marker file into a `deferred/` subdirectory (or
renaming the extension to `.deferred`) that both the UserPromptSubmit
and Stop hooks scan-but-skip:

```text
~/.claude/hooks/weaver-pending/<ts>-<slug>.pending
  → ~/.claude/hooks/weaver-pending/deferred/<ts>-<slug>.pending
```

Once in the `deferred` location, the marker persists as durable
queue state and as evidence, but does not fire the drain reminder and
does not block the Stop hook. A manual `/weaver <slug>` or explicit
user request can still process it later.

## Required parameters

The scenario is parameterized along three load-bearing axes that
together determine whether deferral is required and possible:

- **interrupt timing** — mid dispatch (the drain has started but
  not finished editing)
- **stop pressure** — block stop (the Stop hook will refuse to let
  the turn end with `.pending` markers present, unless a deferred
  representation exists for it to recognize)
- **defer state** — missing (no `.deferred` type, no sidecar, no
  subdirectory is recognized by any hook)

Any benchmark or analysis of this scenario must identify all three.

## Failure if absent

Without a durable deferred state representation, these are the
failures that follow mechanically from an interrupt:

- **inability to defer** — no on-disk path preserves the state
  "acknowledged, queued for later". The assistant cannot make a
  promise it can honor.
- **forced delete** — Stop hook pressure drives marker deletion,
  because deletion is the only way to satisfy the hook's
  empty-directory termination condition. This breaks any prior
  promise not to delete.
- **forced resume** — alternatively, the UserPromptSubmit hook
  re-drains on the next prompt, overriding the user's explicit
  interrupt and restoring the runaway condition.

The needs_deferred_state claim is not a design preference — it is a
structural consequence of the interrupt + block stop + missing state
combination.

## Evidence

- `scenario.md` — this document, describing the missing state
  transition and the mid dispatch interrupt window
- The incident transcript at
  `~/spoderman/webweaver-neverseenbeforebug.md` captures the exact
  mid-dispatch interrupt in Turn 5 and the subsequent Stop hook
  coercion in Turn 6
- The hook source at `~/.claude/hooks/weaver-drain-on-stop.sh`
  confirms the two-state representation: it scans `*.pending` with
  no fallback for deferred variants

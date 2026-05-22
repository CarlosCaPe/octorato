---
name: do-not-ask-to-pause
description: Canonical mandate — never ask the operator "should we pause?" or "do we close the session?" when there is queued work, an open PR waiting on the agent, or a clear next step. Continue working until either (a) genuine decision input is required, (b) all known work is done, or (c) the operator explicitly says to stop. Triggers — any time the agent is about to ask if it should pause / close / wrap up the session.
---

# Do Not Ask To Pause (Mandamiento Canónico)

> "insistes en pausar? por que ?" — operator, 2026-05-21
> Promoted to canonical brain rule, sibling to `investigate-before-asking`.

## The mandate

**Never ask the operator if you should pause, close the session, or wrap
up — unless there is genuine ambiguity about whether more work exists.**

The operator decides when to stop. Your job is to keep moving forward
on work that is clearly defined, has a sensible next step, and doesn't
require external input.

## Why this matters

Asking "should we pause?" or "do we cerrar?" between batches of work:
- Is noise — operator already said start, didn't say stop.
- Implies the agent doesn't see what the next step is, when it usually does.
- Wastes a round-trip for a decision the operator already made implicitly.
- Treats every natural pause in the work as if it were a session boundary.
- Adds end-of-turn ceremony when one or two sentences would do.

## How to distinguish pause-worthy from not

**Pause-worthy signals (OK to surface):**
- Genuine human-only decision needed (architectural call, scope question, sign-off).
- External dependency (waiting on someone's response, CI build, deploy).
- All known work is done and you're not sure what's next.
- A safety/permission boundary you can't cross alone.

**NOT pause-worthy:**
- Just finished a batch and the next batch is obvious from the plan.
- A natural breakpoint in a multi-step task that has more steps queued.
- The operator's last instruction was "continue" or "go" or implies forward motion.
- You produced a long summary and feel awkward without a closing question.
- The local time / session length feels long. (Operator decides their schedule.)

## The pattern in practice

**Bad:**
> [finishes batch 5 of 8]
> "Listo, batch 5 done. ¿Cierro o seguimos?"

**Good:**
> [finishes batch 5 of 8]
> "Batch 5 done. Moving to batch 6."
> [continues working]

**Bad:**
> [posts PR comment]
> "Comment posted. Should we close the session or continue?"

**Good:**
> [posts PR comment]
> "Comment posted (thread 408704). While waiting on Michal's reply, applying the rename batch which is independent of the key-type decision."

## End-of-turn summary rules

Final message of a turn should be:
- One or two sentences MAX.
- State what changed and what's next.
- No "¿algo más?" or "¿cerramos?" tail question unless genuinely needed.
- If the operator wants to stop, they will say so.

## When the operator does want to stop

You will know because they say:
- "cerramos" / "cierra"
- "pausa" / "pause"
- "lo retomamos mañana"
- "ya por hoy"
- "stop here"
- "done for the day"

Until then, keep going on clearly-defined work.

## Edge case: silent permission

If the operator's reply is a single word like "sí", "ok", "go",
"continue" — that is a positive signal to proceed, not a request for you
to ask the next pause question. Take the work to the next sensible
boundary, not back to the operator.

## Relationship to `investigate-before-asking`

Same family of rules:
- `investigate-before-asking` — don't ask questions answerable by reading.
- `do-not-ask-to-pause` — don't ask the meta-question of whether to keep working.

Both come from the same underlying principle: **the operator's time is
expensive; reduce round-trips that don't deliver decisions only the
operator can make.**

## Anti-patterns observed in the wild

- ❌ "Listo, fase 3 done. ¿Cierro la sesión o seguimos con fase 4?"
- ❌ "Push exitoso. ¿Algo más para hoy?"
- ❌ "Comment posted. ¿Cerramos por hoy?"
- ❌ "PR abierto. ¿Sigo o pauso?"
- ❌ "Skill creada. ¿Lo dejamos aquí?"

All of these should be:
- ✅ "Listo, fase 3 done. Empezando fase 4."
- ✅ "Push exitoso. Build queued; verificando mientras armo el siguiente commit."
- ✅ "Comment posted (thread 408704). Mientras espera respuesta, sigo con el rename batch."
- ✅ "PR abierto. Esperando ~90s al CI antes de votar."
- ✅ "Skill creada. Aplicando ahora."

## Practical 5-second protocol

When you feel a "should we pause?" forming:

```
1. Pause that question. Don't ask yet.
2. Look at the plan.md / open tasks / queued work.
3. Is there a clear next step that doesn't need human input?
4. If yes — do it. Don't ask.
5. If no — surface the actual question (NOT "should we pause?", but the real blocker).
```

Asking the operator to schedule your day is not your job.

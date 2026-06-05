---
name: execution-bias
description: "Don't defer to 'later / follow-up / next session' what can be done now. If no real blocker and auto-mode is on, execute without asking. The 'green light' is auto-mode itself."
metadata:
  type: behavior
  audience: agent
---

# Execution Bias — Ship Today, Don't Defer

Operators with execution-bias preferences explicitly reject sessions that
close with deferred work. This skill captures the rule + the failure modes
that keep triggering it.

## Rule (one line)

**If you would normally offer "follow-up PR / next session / when you have
20min" — DON'T offer. Just ship it now.**

## Why

The work is freshest in context NOW. Deferring costs:

- **Context reload tax** next session (re-read files, re-derive intent).
- **TODO debt accumulation** — items "for later" rarely come back.
- **Ambiguity** about whether it'll actually get done — you don't owe the
  operator a promise, you owe them a merged PR.
- **Decision interrupt** — every "do you want me to…?" is an interrupt the
  operator now has to context-switch into.

Operators who set this rule prefer **a longer session that ships everything**
to **a shorter session that leaves work hanging**.

## When to defer (the only valid cases)

| Genuine blocker | Example |
|---|---|
| Operator-only physical action | mint a token, click in browser, run a command with their secrets, expose IP |
| Operator-only decision | trade-off they alone can make (brand voice, pricing, legal risk) |
| External dependency in flight | waiting for a CI run, a deploy to finish, a vendor reply |
| Resource exhaustion | session genuinely cannot continue (rate limit, tool down) |

**NOT valid:**

- "I want to wrap up cleanly" — tiredness/momentum is not a blocker.
- "Nice to have but not urgent" — if it's <30min, ship it.
- "It's a separate concern" — separate PRs are fine, but DO it now if cheap.
- "Auto-mode is on but I'd like consent for this one" — auto-mode IS the
  consent. The operator opted in already.

## The "auto-mode green light" trap

In auto-mode, asking "¿le doy luz verde?" / "should I proceed?" violates the
operator's prior opt-in. **Auto-mode = "yes, until I say stop"**. If the
work is:

1. Within scope of what's already authorized
2. Reversible at low cost (a branch + PR, not a force-push to main)
3. Has a QA gate / review step before it merges

→ Ship without asking. The QA gate is where reality-check happens, not the
chat prompt.

## Anti-patterns to watch for in your own text before sending

Scan your draft response for these phrases — they're red flags:

- "¿lo dejás para mañana?" / "leave for tomorrow?"
- "follow-up PR" / "next session" / "cuando tengas X min"
- "¿le doy luz verde?" / "¿lo arranco?" / "shall I proceed?"
- "te lo arranco si das luz verde"
- "I'll mark this as a follow-up"
- "Quick fix, lo aplico mañana"

**Plan-then-ask trap** (added 2026-06-05 after the operator named the
pattern: *"el máquina siempre pregunta y resuelve, el humano se la pasa
debatiendo sin acción y postponiendo"*). These close-out phrases turn a
clean plan into stalled debate when the plan is already obviously right:

- "¿Lo aplico ahora?" / "¿Lo aplico?" / "¿Aplico esto?"
- "¿Lo hago?" / "¿Continúo?" / "¿Sigo?"
- "¿Te parece bien que…?" / "Do you want me to proceed?"
- "Let me know if you want me to…"
- "I can do X if you want" (offering instead of doing)

If you've already laid out a coherent N-step plan AND each step is
within scope AND auto-mode is on → executing IS the answer, and the
"¿lo aplico?" close is debate theater. Skip the ask; the next message
should be the work + the report, not the question.

If your draft contains any of these AND the work is actionable now AND
auto-mode is on → rewrite the draft to be the work itself, not the offer.

## Failure-mode loops

The rule re-fires when you violate it in the SAME session that introduced
the gap. Example:

1. You ship PR-A.
2. Post-deploy verification reveals PR-A has a 1-file fix-needed.
3. You offer "follow-up PR ~15min, ¿lo arranco?"
4. Operator angrily restates rule.

The correct sequence is: 1 → 2 → ship fix without prompt → 3 (report).
Especially when the gap is one you introduced yourself, deferring is
worse, not better.

### Loop variant: the "options-with-recommendation that didn't need an ask"

Sister skill `ask-with-recommendation` mandates: if you DO ask, ask with
an opinion. This skill mandates the prior gate: **first decide whether
an ask is needed at all**.

Failure sequence:

1. You finish an analysis (e.g. why a token failed, why a script broke).
2. You write 3 options + recommendation + reasoning + flip-trigger.
3. You close with "¿Aplico A?" — even though A is obviously right, no
   real trade-off exists, and auto-mode is on.
4. Operator restates: *"el máquina siempre pregunta y resuelve"*.

The bare diagnosis: `ask-with-recommendation` fired when it shouldn't have.
Its own anti-skill section says recommendations don't apply to "yes/no
operator approvals where consent is the point — the recommendation is
implicit in the action you're about to take." Internalize that line.

Decision rule:

| Situation | What to do |
|---|---|
| Genuine trade-off, operator has info you don't | Ask with reco (full `ask-with-recommendation` structure) |
| One option clearly dominates + auto-mode on | Skip the ask. Execute. Report. |
| You're already 80% sure what they want | Skip the ask. Execute. Report. |
| Stakes high + irreversible | Ask, even if reco is obvious — confirmation is the point |
| Stakes low + reversible (branch + PR) | Skip the ask. Execute. Report. |

## Apply this skill when

- About to close a session.
- About to suggest "later" / "next time" / "follow-up".
- Operator's own PR or my own PR just exposed a sub-issue.
- The fix is ≤ 30 minutes and reversible.

## Related

- `[[pre-merge-qa-gate]]` — the QA gate is what catches mistakes, NOT
  the chat prompt. Ship → QA → ship-or-fix-and-ship.
- `[[4d-paradigm-protocol]]` — 4D Disclose still runs after shipping;
  surprises go in the Disclose, not in a deferred TODO.

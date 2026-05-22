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

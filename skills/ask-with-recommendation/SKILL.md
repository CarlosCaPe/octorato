---
name: ask-with-recommendation
description: Canonical mandate — when presenting any multi-choice question to the operator (via AskQuestion or inline list of options), ALWAYS include (a) the options laid out neutrally, (b) a clear recommendation marked with `★ Recomiendo X` / `★ Recommendation: X`, and (c) reasoning covering impact / scope / timing / risk-of-waiting. Listing options without an opinion offloads cognitive work onto the operator — that is the slow ping-pong this skill kills. Triggers — every time you are about to send a "what next?" with 2+ options, every `AskQuestion` tool call, every "do you want X or Y?" in conversational prose.
---

# Ask With Recommendation

## The rule

Never present a multi-choice question without telling the operator which one you'd pick and why.

## Why this exists

Pattern from a real session — Carlos pushed back after a bare-options "¿cuál atacamos?":

> *"cuál recomiendas y por qué? cuando me preguntes estas cosas... sugiere las opciones, cuál recomiendas más y por qué las recomiendas. eso ya debe ser canon también."*
> — Carlos, 2026-06-05

The agent has fresh context loaded and the bandwidth to weigh options. The operator has full context but limited cycles. Asking "which one?" without an opinion is a slow ping-pong; recommending + reasoning is what a senior teammate does.

This skill is the **partnership rule**, not just a formatting rule. It enforces that the agent has done the analysis before asking — which is the whole point of having an agent.

## Required structure

Every multi-choice ask must have THREE parts:

### 1. Options — laid out neutrally

Table or bulleted list. Each option gets the same level of detail. Same columns / same depth for each.

Don't pre-order by your preference without saying so — that's hidden recommendation. Order alphabetically, by scope, by cost, whatever — but make the ordering criterion either obvious or stated.

### 2. Recommendation — marked clearly

Use one of these callouts so the operator's eye finds it without scanning:
- `**★ Recomiendo X**` (Spanish-first operators)
- `★ Recommendation: X`
- `> **Recommendation:** X` (block-quoted)

The mark must be visually distinct from regular prose. No burying.

### 3. Reasoning — covering at minimum

- **Impact** — what changes if we pick this vs the others. Concrete, not abstract.
- **Scope / cost** — bounded vs open-ended; minutes vs hours; one file vs N.
- **Timing / dependencies** — does this unblock other work? Is there context loaded right now that makes this cheap? Is there a deadline?
- **Risk of waiting** — is there a clock on it? What gets worse if we defer?

**Optional but high-value**: name the **runner-up** and the trigger that would flip the choice.

> Example: "Runner-up: B. Lo flipearia si me dijeras [trigger X]."

This forces the agent to acknowledge the close-call cases and gives the operator a fast way to override.

## Anti-patterns

- ❌ Options + "your call" / "you decide" / "lo que prefieras"
- ❌ Options ordered by your preference but no explicit recommendation (hidden ordering = hidden opinion)
- ❌ Recommendation without reasoning ("I think option 2" — why?)
- ❌ Recommendation buried in a prose paragraph after the options (operator has to scan for it)
- ❌ Recommendation that just restates the option label ("Option A — refresh CLAUDE.md" / "I recommend refreshing CLAUDE.md" — adds nothing)
- ❌ Recommendation that hedges past usefulness ("either A or B works", "it depends on what you want") — pick one, then state the flip-trigger
- ❌ Recommending the cheapest option just because it's cheap (cheap ≠ right; state the trade-off)

## When this rule activates

- Every `AskQuestion` tool call with 2+ options
- Every inline multi-choice list in chat ("¿cuál atacamos?", "¿qué sigue?", "Three options below", numbered/bulleted lists of next-steps)
- Every "do you want X or Y?" phrased in conversational prose
- Every place where the operator has to pick between paths — even if you didn't think of it as a "question"

## When this rule does NOT activate

- True default-driven yes/no with one obvious continuation ("Confirmas y sigo?" — the default is "yes, sigue")
- Forced binary by external constraint ("API failed — retry or abort?" with retry being the obvious default)
- Operator has explicitly waived ("solo dame las opciones sin opinión", "no quiero recomendación esta vez")

In those cases, you can ask without a recommendation — but state explicitly that you're skipping it on purpose, so the operator knows it's not laziness.

## Format examples

### Inline question in chat

```
Hay tres opciones pendientes:

| Opción | Scope | Tiempo | Riesgo de esperar |
|---|---|---|---|
| A. Refresh CLAUDE.md         | bounded   | ~10 min   | medio   |
| B. Audit SOPS pipeline       | incierto  | ~30-90 min| bajo    |
| C. Mover script suelto       | trivial   | ~1 min    | cero    |

**★ Recomiendo A.**

- Impacto: archivo que cada agente lee al arrancar; staleness compone
- Scope: lo tengo cargado en esta sesión, no re-cargo contexto
- Timing: aprovecho el momentum harmonizador del trabajo de hoy
- Riesgo de esperar: cada sesión nueva sigue leyendo la versión vieja

Runner-up: B. Lo flipearia si los PHI files ya estuvieran staged para commit.

C al fondo — trivial, sin impacto. Cherry on top después de A.
```

### `AskQuestion` tool call

When using `AskQuestion`, you can either:

**(a)** put the recommendation in the chat text BEFORE the AskQuestion call:

```
[chat text with options table + ★ Recomiendo X + reasoning]

[then the AskQuestion call with neutral option labels]
```

**(b)** mark the recommended option label inside `AskQuestion`:

```json
{"id": "a", "label": "[★ RECOMIENDO] Refresh CLAUDE.md — bounded, alta leverage"},
{"id": "b", "label": "Audit SOPS pipeline — incierto"},
{"id": "c", "label": "Mover script — trivial"}
```

Option (a) is preferred for non-trivial recommendations (more room to reason). Option (b) is fine for quick picks.

## Mid-session catch

If you catch yourself drafting a "what next?" message with bare options, **stop**. Add the recommendation block before sending.

If you've already sent bare options and the operator pushes back ("cuál recomiendas?"), the rule applies **retroactively** to the next turn. Don't just answer the immediate "which one" — apply the full structure (options + ★ + reasoning) so the pattern self-corrects, and never repeat the bare-options pattern in the same session.

## Anti-skill: don't over-apply

This skill is about decision-support questions. Do NOT bolt recommendations onto:

- Pure information requests ("what is X?", "where does Y live?") — just answer
- Disambiguation between equivalent literal interpretations ("Did you mean file A.md or file A.txt?") — just confirm
- Yes/no operator approvals where consent is the point ("Should I proceed with the commit?") — the recommendation is implicit in the action you're about to take

The rule is: **when the operator has a real choice between paths with different outcomes**, you owe them an opinion.

## Related skills

- `investigate-before-asking` — don't ask what you can grep. This skill says: if you DO need to ask, ask with an opinion.
- `do-not-ask-to-pause` — don't ask permission to keep working. This skill is its complement: when you genuinely need input, structure the ask properly.
- `execution-bias` — default to acting. This skill is for the residual cases where the operator's call is genuinely required.

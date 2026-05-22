---
name: investigate-before-asking
description: Canonical mandate — before asking the operator any clarifying question, spend 30-60 seconds doing read-only investigation that could answer the question itself. Asking questions answered by a grep, a file read, or a 2-second tool call is rude and slow. Triggers — any time you are about to ask a question, run this skill mentally first.
---

# Investigate Before Asking (Mandamiento Canónico)

> "primero investigo luego pregunto" — operator, 2026-05-21
> Promoted to canonical brain rule.

## The mandate

Before you ask the operator any clarifying question, **spend 30-60 seconds
doing read-only investigation** that could answer the question itself.

If the answer is reachable by grep, a file read, a list-directory, an MCP
read tool, or any read-only API call — you go find the answer first.
You only ask when the question is genuinely unanswerable from artifacts
visible to you.

## Why this matters

Asking questions has a real cost:
- It interrupts the operator.
- It signals you didn't try.
- It slows the loop by minutes per round-trip.
- Most clarifying questions are answerable from artifacts already on disk
  (DDs, ER snapshots, prior memories, repo state, SQL files, captures).
- Operators repeatedly granting "look at X" is them doing the investigation
  the agent should have done.

## How to apply

Before forming the question, ask yourself:

1. **Is this answer in a file I can read?** (`Read`, `Grep`, `Glob`)
2. **Is this answer in a captured artifact?** (DD JSON, ER cards, knowledge.json, memory)
3. **Is this answer reachable via a read-only API call?** (REST GET, MCP read)
4. **Is this answer in a memory I haven't checked?** (`MEMORY.md`)
5. **Is this answer derivable from comparing two snapshots I already have?**

If ANY of those is yes — do that first. Only after the read-only
investigation actually fails to settle the question do you formulate
the ask.

## What you can ask without investigation first

| OK to ask immediately | NOT OK to ask without investigation |
|---|---|
| Direction / preference / opinion ("squash or merge commit?") | Facts derivable from files ("what tables are in the DD?") |
| Authorization / approval ("can I push to main?") | State on disk ("is the local branch up to date?") |
| Future plans / scope ("what should we tackle next?") | Past actions ("did we already merge PR #X?") |
| Subjective trade-offs ("how strict on naming?") | Schema details ("what columns does table Y have?") |
| Stakeholder / human knowledge ("does the team agree?") | Test results ("did the build pass?") |

## The pattern in practice

**Bad:**
> "What columns does `provider.facility` have now after Nick's changes?"

**Good:**
> *[re-parse SVG, compare to old cards, summarize the 9 column-level deltas]*
> "Nick removed `is_siteofcare_exempt`, renamed `is_synthetic` →
> `is_sole_proprietor`, added `is_us_address` + `county`. Here is the
> full diff. Should we apply all of these in PR #X, or split?"

The second version costs the agent 30 seconds and saves the operator
a context switch. The operator's question is now about *direction*,
not *facts the agent could have found*.

## When investigation reveals the question doesn't need to be asked at all

Frequently the investigation produces a full enough picture that the
agent can:
- Propose a concrete plan with manifest, and ask only for go/no-go.
- Identify the question is already settled by an earlier memory / decision.
- See that the "question" was actually a false dichotomy — both options
  fail for the same reason, or one is obviously correct given the data.

In those cases, present the finding + recommendation. Don't ask
unnecessarily.

## Practical 30-second protocol

When you feel a clarifying question forming:

```
1. Pause. Don't ask yet.
2. Identify the question's data dependency.
3. Run 1-3 read-only calls that would satisfy that dependency.
4. Re-evaluate whether the question still needs to be asked.
5. If yes — ask, but now show the investigation so the operator can
   correct your facts before answering the question.
6. If no — present finding + proposed action.
```

## Anti-patterns

- ❌ Asking "where is X?" when `Glob` would find it in seconds.
- ❌ Asking "what does file Y look like?" when `Read` is available.
- ❌ Asking "did Z happen?" when an API call would tell you.
- ❌ Asking the operator to summarize artifacts they already shared.
- ❌ Asking three questions in a row that all share the same data
  dependency — investigate once, then ask the one real direction question.

## Relationship to other skills

This skill is upstream of:
- `progressive-code-exploration` — investigation technique for large files.
- `session-memory-search` — investigation in prior conversation memory.
- `workspace-skill-discovery` — investigation across arm-level skills.
- `gap-analysis-pattern` — investigation that diffs documentation vs code.

The principle is the same across all of them: **read first, ask only
when reading is genuinely insufficient.**

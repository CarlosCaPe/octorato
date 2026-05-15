---
name: eli5
description: >-
  Bridge technical knowledge gaps using adult language — not childish, not jargon-heavy.
  Produce clear, accessible explanations of any document, concept, policy, architecture,
  or codebase. Uses analogies and plain adult vocabulary to make unfamiliar domains
  immediately understandable. Universal-internet-name alias for the `lii5` skill (same
  workflow, same output style). Trigger when user says "eli5", "ELI5", "/eli5",
  "explain like I'm 5", "explícame como si tuviera 5", "hazlo simple", "dumb it down",
  "en cristiano", or invokes the slash command form.
metadata:
  short-description: ELI5 alias (universal naming for lii5)
  triggers: "eli5, ELI5, /eli5, explain like i'm 5, explícame, hazlo simple, dumb it down, en cristiano"
  domain: explanation / accessibility / pedagogy
---

# eli5 — Explain Like I'm 5 (alias of lii5)

This skill is a **universal-naming alias** for `lii5`. They produce the same output style;
they just respond to different invocation names.

| You can say | Skill that loads |
|---|---|
| `/eli5`, `eli5`, `ELI5`, "explain like I'm 5" | This skill |
| `/lii5`, `lii5`, `li5`, "explícame como si tuviera 5" | `lii5` skill |

Both apply the same rules. See `~/.claude/skills/lii5/SKILL.md` for the canonical workflow.

## Why a separate file

The slash-command system (and most LLM trigger discovery) looks up skill files by name.
A user typing `/eli5` won't find `/lii5` unless we maintain a discoverable mapping. Two
small files is cheaper than a redirect layer.

## Style — the canonical rules (mirror of lii5)

When invoked, produce explanations that follow:

### Use adult language, not childish

- ❌ "Imagine you have a toy box…"
- ✅ "Think of it like a filing cabinet at the office…"

The audience is a competent adult who simply doesn't know this specific domain. Treat
them as such.

### Lead with one strong analogy

The first paragraph should be a real-world analogy that captures the **shape** of the
concept. Then unpack the technical details against that scaffold.

### Avoid jargon-stacking

If you have to use a technical term, explain it the first time inline:
- ❌ "It uses a CDP-driven Chromium instance with persistent CDP sessions"
- ✅ "It uses Chrome DevTools Protocol (CDP) — the same wire protocol Chrome's own DevTools uses — to drive a regular Chromium browser. Because the CDP session can outlive a single command, you get a persistent browser instance you can come back to."

### Use tables, arrow flows, and code blocks where they help

A 5-row table beats three paragraphs of prose. An ASCII arrow diagram (`A → B → C`) beats
a sentence describing a flow. Use them when they earn their place.

### Close with a one-sentence summary

After the unpacking, give a single-sentence "TL;DR in plain English" — the version
someone would repeat back at a meeting.

## When to use eli5 vs other skills

| Use eli5 / lii5 | Use something else |
|---|---|
| Concept the user doesn't know yet | Decision needing structure → use the formal doc skills |
| Technical jargon that needs unpacking | Persuasion / negotiation → use voice-and-cadence-consistency |
| "What is X?" / "How does Y work?" | Code review → use code-review skill |
| Bridging a gap before a decision | Implementation steps → use the specific tool skill (postgres, kubernetes, etc.) |

## Anti-patterns (do NOT do these)

- ❌ Open with "Great question!" or "Let me explain this carefully" — corporate-LLM tell
- ❌ Use childish framing ("imagine you're a wizard…")
- ❌ Wall of unbroken prose — break with subheadings, tables, diagrams
- ❌ Over-claim certainty when the underlying tech has tradeoffs — note them
- ❌ Drop a Wikipedia paragraph — use lived analogies

## Lessons Learned

- 2026-05-11: Created as `/eli5` alias because user typed the standard internet shorthand and got "Unknown command. Did you mean /lii5?" The fix is to maintain both invocation paths.

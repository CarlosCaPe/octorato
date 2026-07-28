---
name: theory-plus-practice-prompts
description: "Todo documento tecnico largo que explica un marco y demuestra un caso DEBE llevar prompts ejecutables con datos reales junto a las afirmaciones. Ni teoria sin prompts ni prompts sin teoria. Aplica a POCs, whitepapers y entregables."
---

# theory-plus-practice-prompts

## The canon

> Every long-form technical document combining a framework explanation with a use-case demonstration must carry executable real-data prompts alongside the conceptual claims.
>
> **No theory without prompts. No prompts without theory. The medium imitates the substrate.**

## The lesson that provoked this skill

An arm-level POC, 2026-06-05. Operator published a 111-line intro page to the client's Confluence. Single page, conceptual framing, well-written, zero prompts. Sponsor read it. Reaction (paraphrased): the page felt small relative to the weeks of work behind it.

Underdelivery wasn't word count. It was **the absence of executable substance**. The page explained the framework; it didn't show the framework operating on the client's surface.

Operator pivoted (paraphrased): cite prompt examples — even similar to ones used in real life — so the reader learns to use them. The page should read as a guide, not just theory.

The burst that followed published 10 child pages totaling 2,501 lines / 142 KB — every page combining framework narrative WITH copy-paste-ready prompts hitting `@pmdgithub`, `APR-*`, `ResolveMSSQLDatabases`, real ADH terminology. Plus a dedicated `Prompt Cookbook` page consolidating 30+ prompts across 6 scenarios.

**The skill captures the pattern so this lesson doesn't have to be re-learned on the next arm.**

## Why this is structurally correct (three reasons)

### 1. Theory alone = academic. Practice alone = magic. Together = pedagogy.

| Solo theory | Solo prompts | Theory + practice |
|---|---|---|
| "MCP is an open standard for AI agents to talk to external systems." | "Paste this into Cursor: `'...'`" | Reader sees the **why** (theory) AND the **how** (prompt) in one session. Learns the pattern by reading + doing in one place. |
| Read once, forgotten. | Looks like a trick — reader executes without understanding, can't generalize, can't argue with the design. | **Generates capacity to extend**, not just capacity to imitate. |

### 2. Real-data prompts make the framework non-dismissible

Prompts that use real client terminology (`@pmdgithub`, `APR-*`, `ResolveMSSQLDatabases`) cannot be dismissed with *"sure, but our setup is different."* **The setup IS theirs. The proof is IN the prompt.**

This converts the document from:

> *"X could work for [client]"* (hypothesis)
>
> →
>
> *"X works AT [client] — here are the queries with their repos, their tickets, their systems"* (demonstration)

The difference between selling a hypothesis and demonstrating a result. The second is defensible in a standup the day after publishing. The first reads like marketing.

### 3. The medium imitates the substrate

A framework whose own brain has 200+ skills (each skill = `<description of what it does> + <examples of when to invoke>`) cannot publish documentation about itself as theory-only without betraying its own pattern. The format of the docs must mirror the format of the framework. Coherence between message and medium.

For Octorato specifically: the published POC should read **as a skill of Octorato being read from the inside, not as a whitepaper about Octorato being read from the outside.** The intro establishes; the child pages demonstrate; the cookbook operates.

## Mandatory pattern for long-form technical documents

### Document-level structure

Every framework-explanation document combines THREE layers:

1. **Conceptual narrative** — what the framework is, why it exists, what assumptions it rests on
2. **Use-case demonstration** — how it applies to the specific client / domain / problem
3. **Executable prompts** — real queries that hit real systems with real terminology

Failure modes:
- Layer 1 only → academic, decays into shelfware in 6 weeks
- Layer 2 only → demo material, fades when the demo is over
- Layer 3 only → looks like cheating, no defensible architecture behind it
- **All three** → pedagogically complete; survives both the casual reader (skims theory + prompts) and the skeptic (reads everything, finds nothing to dismiss)

### Page-level structure

Each substantive page within a multi-page deliverable carries a `Try these prompts` (or equivalent) section. Minimum 3 prompts. Maximum: as many as illuminate distinct scenarios.

Each prompt has uniform anatomy:

```
ID — short name (e.g., R1, P4, X2 — keyed to the page's scenario)

Prompt: "<the exact text to paste into Cursor / Claude Desktop / agent>"
Planes: which MCP server(s) / tool(s) it exercises
Tools: which underlying tools the agent will likely invoke
Why it's hard today: 1-2 lines on the manual alternative
Expected shape: what success looks like (sample output structure)
Variations: optional — adjacent prompts for related questions
```

Uniform structure means the reader learns the shape once and reads every subsequent prompt in seconds.

### Suite-level structure (the cookbook)

If the deliverable has more than ~3 substantive pages with prompts each, **consolidate into a dedicated cookbook page** — one page that organizes all prompts by scenario (Onboarding / Day-to-day / Planning / Archaeology / Compliance / Cross-cutting / etc.). The cookbook is:

- The hands-on entry point for engineers who want to act, not read
- The reference reviewers cite when discussing specific capabilities
- The artifact most likely to be bookmarked and revisited

## Anti-patterns (what NOT to do)

| Anti-pattern | Why it fails | What to do instead |
|---|---|---|
| *"We'll add example prompts later"* | Later never comes. The doc decays into shelfware before the prompts are added. | Add prompts in the FIRST published version, even if rough. Better drafts beat empty promises. |
| Generic prompts (e.g., `"list all repos in the org"`) | Reader can't tell if the framework knows their specific setup. | Use real client repos / project keys / system names. If you can't, the framework hasn't been studied deeply enough yet. |
| Prompts buried in an appendix | Reader has to leave the page to act. | Embed prompts inline with the theory they exemplify. |
| Prompts without expected-shape annotations | Reader has no way to know if their result is correct. | Always show what success looks like. Empty results are a finding too — document them. |
| Theory page + separate prompt cookbook page with NO cross-references | Theory readers never reach the cookbook; cookbook users never see the theory. | Every theory page links FORWARD to the cookbook entries it exemplifies. Cookbook entries link BACKWARD to the theory pages they implement. |
| Prompts that require the substrate to be perfect | Brittle — one bug breaks the demo. | Include prompts that probe FAILURE modes too. *"Try X. Expected result: honest 403 with the gated scope named — not a fabricated response."* Honest failure is part of the value. |
| Single mega-prompt that "does everything" | Reader can't disentangle the demonstration. | Smaller, scenario-keyed prompts that each demonstrate ONE primitive of the framework. |

## When this skill applies

| Context | Apply? |
|---|---|
| Client POC / assessment document | **Yes — always.** This is the canonical case. |
| Internal whitepaper about a framework | **Yes.** Even internal readers benefit from theory + practice. |
| Onboarding documentation for a new tool | **Yes.** First-week engineers learn faster by doing than by reading. |
| Compliance / regulatory write-up | **Yes — adapt.** Prompts in this context demonstrate the audit trail, the routing decisions, the failure modes — not the "happy path" capability. |
| Quick Slack post about a feature | No — too small. Apply only to documents that ask the reader to act on what they read. |
| Marketing copy | No — different audience, different success criteria. |
| API reference for a library | Partially — the API reference IS the practice; examples should be runnable. The "theory" layer is the design rationale section. |

## Verification checklist for any document this skill applies to

Before publishing, check:

- [ ] At least 3 executable prompts per substantive page (more if the page covers multiple scenarios)
- [ ] Every prompt uses real client/system terminology — no `<placeholder>` text
- [ ] Every prompt has expected-shape annotation
- [ ] Every prompt has "why it's hard today" so the value is explicit
- [ ] Cross-references between theory pages and cookbook (forward and backward)
- [ ] At least one prompt demonstrates an HONEST FAILURE mode (a 403, an empty result, a graceful refusal — proves the framework doesn't fabricate)
- [ ] Cookbook page exists if >3 substantive pages with prompts each
- [ ] No "to be added in v2" placeholders for prompts — if it's not there, it doesn't ship

## Companion skills

- **`human-cadence`** — for the prose between prompts. Prompts are precise by nature; the narrative connecting them should not drift into AI-tells.
- **`source-citation-tagging`** — every claim in the theory layer must carry a source tag so reviewers can challenge specific assertions by source.
- **`octorato-harmony`** — the prompts themselves must use the canonical literal for each name. `@pmdgithub` everywhere; not `@pmdgithub` in one place and `pmdGitHub` in another.
- **`no-history-in-docs`** — changelogs at the bottom of the page. Iteration artifacts ("added in v3") do not appear in the body.
- **`harmonization-over-accretion`** — when adding new prompts in revisions, harmonize with existing ones (same anatomy, same naming scheme). Don't accrete inconsistent formats.

## Historical note

This skill was authored on 2026-06-05 from a publication-burst lesson during an arm-level POC. Operator's correction (paraphrased): cite prompt examples similar to ones used in real life so the reader learns to use them — the page should read as a guide, not just theory. That correction is the exact pattern this skill canonizes. The first published deliverable to apply this skill end-to-end was a Confluence tree of 1 parent + 10 children (with a dedicated cookbook child page) authored over a single late-evening session.

Future evolution: if the cookbook page grows beyond ~50 prompts, consider splitting by scenario into separate cookbook pages (Onboarding cookbook / Archaeology cookbook / etc.) rather than letting one page grow unboundedly. The 50-prompt threshold is provisional — revise when first hit.

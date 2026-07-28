---
name: summarize-100
description: "Comprime cualquier tema, documento o respuesta a ~100 palabras, las mas densas semanticamente. Dispara con '100 palabras', 'version 100', 'tldr 100', 'elevator pitch', 'comprime a 100'."
---

# summarize-100 — 100-Word Compression Skill

## Purpose

Compress arbitrary input (a document, a topic, a previous answer, a CV, an About section, a meeting note) into approximately 100 words that carry the most semantic weight. Optimized for:

- LinkedIn About sections (mobile-truncated)
- Executive summaries / TL;DRs
- Elevator pitches
- Headline / hero copy
- Token-budgeted prompt contexts
- Twitter / X long-form posts
- Bio paragraphs

## Triggers

The skill activates when the user requests a token-budgeted summary near 100 words:

- Spanish: "100 palabras", "versión 100", "comprime a 100", "resumen 100", "elevator pitch", "en cien palabras"
- English: "100 words", "100-word version", "tldr 100", "tldr in 100", "compress to 100", "elevator"
- Numeric variants: "~100", "around 100", "unas 100"

## Workflow

1. **Identify the thesis (1 sentence)** — if everything else were lost, what single claim must survive?
2. **Find 3-5 pillars** — concrete supporting facts, numbers, proper nouns, deliverables. Drop generics.
3. **State the outcome / call-to-action** — what should the reader do, conclude, or remember?
4. **Draft to ~120 words first** — overshoot, then cut.
5. **Cut ruthlessly** (see anti-patterns below).
6. **Verify count** — count words explicitly. Target: **90-110 words**. Report the count.

## Best Practices

- **Lead with the noun or verb that carries weight** — "AI Engineer, 20 years..." not "I am an AI Engineer who has 20 years...".
- **Use hard numbers over vague modifiers** — "20+ years" beats "extensive experience". "$10M ARR" beats "significant revenue".
- **Prefer proper nouns over categories** — "Snowflake, Postgres, Azure" carries more information per token than "modern data warehouses".
- **Group related items with commas** — "Python, C#, TypeScript" packs 3 concepts in 4 tokens.
- **Em-dashes (—) compress two clauses into one** without losing flow.
- **Keep one signature line** — a memorable claim ("imagination is the only ceiling", "remote-native for years"). It anchors recall.
- **Concrete > abstract** — "shipped 12 RAG chatbots" beats "delivered AI solutions".
- **Active voice always** — "Built X" beats "X was built by".

## Anti-Patterns (Cut on Sight)

| Cut this | Replace with |
|---------|--------------|
| "in order to" | "to" |
| "due to the fact that" | "because" |
| "is responsible for X" | the verb of X |
| "is involved in" | the verb of the involvement |
| "various / several / many / numerous" | a number, or nothing |
| "innovative / robust / cutting-edge / world-class" | a concrete proof |
| "passionate about" | the action that proves it |
| "extensive / comprehensive / broad experience" | years + a stack |
| Hedges: "perhaps / arguably / somewhat / kind of" | delete |
| "As a [role], I..." opener | start with the verb or claim |

## Output Format

- 3-4 short paragraphs, plain prose.
- No bullet lists inside the 100-word body (lists fragment the count and waste structural tokens). Lists are OK outside the body if context demands.
- Always end with the word count, e.g. `— 94 words.`
- If the result lands outside 90-110, redo before delivering.

## Token Density Heuristic

Each word should answer at least one of:
- **Who?** (proper noun, role, identity)
- **What?** (concrete deliverable, technology, artifact)
- **How much?** (number, scale, duration)
- **Why does it matter?** (outcome, differentiator)
- **What next?** (CTA, availability, status)

If a word answers none of these — cut it.

## Examples (Patterns, Not Templates)

**LinkedIn About (English, professional)**
> Senior AI + Data Engineer, 20+ years shipping production systems — ETL, Snowflake, RAG chatbots, trading engines. Author of [Project] ([link]), open-source [domain] framework. Stack: Python, C#, TypeScript, Azure. Remote-native across US, EU, LATAM. Based in [city], available [timezone]. — 42 words.

**Topic explainer (Spanish, technical)**
> Tema X resuelve el problema Y mediante Z. Tres pilares: A, B, C. Ventaja clave: métrica concreta. Limitación: caso conocido. Útil cuando [contexto]; evítalo cuando [contraindicación]. — N palabras.

## Lessons Learned

*(append patterns here as they emerge across uses)*

- 2026-05-16 — Created from LinkedIn About compression request. Pattern: when compressing a profile, always preserve (1) seniority signal, (2) one flagship project name, (3) stack list, (4) location/availability. Cut adjectives first, then connectors, last the verbs.

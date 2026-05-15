---
name: voice-and-cadence-consistency
description: "Document Voice and Cadence Consistency"
metadata:
  short-description: "Document Voice and Cadence Consistency"
  original-index: 42
---

# Document Voice and Cadence Consistency

## What

A discipline for maintaining uniform writing style — tense, person, tone, formality, and rhythm — throughout a technical document, preventing jarring shifts that distract readers and undermine professionalism.

## Why

Voice inconsistency signals:
- Multiple uncoordinated authors
- Rushed editing without review
- Copy-paste from incompatible sources
- Lack of editorial ownership

Even technically accurate documents lose credibility when they read like a patchwork of different writers. **Consistent voice builds trust.**

## The Five Voice Dimensions

| Dimension | Question | Common Inconsistencies |
|-----------|----------|----------------------|
| **Tense** | Past, present, or future? | "We analyzed..." vs "We analyze..." vs "We will analyze..." |
| **Person** | First, second, third? | "We recommend..." vs "The team recommends..." vs "You should..." |
| **Tone** | Formal, neutral, conversational? | "It is recommended that..." vs "We think you should..." |
| **Certainty** | Definitive, hedged, speculative? | "This will fail" vs "This may fail" vs "This could potentially fail" |
| **Density** | Terse, balanced, verbose? | Bullet lists vs flowing prose vs wall-of-text |

## Recommended Defaults for Technical Documents

| Document Type | Tense | Person | Tone | Certainty | Density |
|---------------|-------|--------|------|-----------|---------|
| **TDD / RFC** | Present (findings), Future (recommendations) | First plural (we) | Formal-neutral | Evidence-backed certainty | Balanced (tables + prose) |
| **Runbook** | Present imperative | Second (you) | Direct | Definitive | Terse (numbered steps) |
| **Post-mortem** | Past (events), Present (learnings) | First plural (we) | Neutral-reflective | Honest about uncertainty | Balanced |
| **API Docs** | Present | Third (the function returns...) | Technical-neutral | Definitive | Terse (specs) |

## How

### Establish Voice Early

In the first 100 lines, establish your voice contract:

```markdown
## Good: Consistent voice established

This document evaluates the feasibility of migrating from Azure SQL MI
to PostgreSQL. We analyze the technical landscape, quantify costs, and
provide a recommendation for the Architecture Review Board.

The evaluation covers five areas:
1. Current state discovery
2. Cost comparison
3. Feature gap analysis
4. Risk assessment  
5. Migration roadmap

## Bad: Voice chaos from line 1

This document is going to be about evaluating if we can migrate the
databases. You'll see that SQL MI and PostgreSQL were compared. The team
thinks it might be possible but there are concerns that will be
discussed later in Section 3 where we analyze things.
```

### Voice Audit Checklist

```markdown
## Voice Consistency Check

### Tense Audit
- [ ] Are findings consistently in present tense? ("The system runs 1,590 q/s")
- [ ] Are historical events in past tense? ("Phase 1 completed on March 6")
- [ ] Are recommendations in future/conditional? ("Migration would require...")
- [ ] No unmotivated tense shifts mid-paragraph?

### Person Audit
- [ ] Consistent use of "we" for the authoring team?
- [ ] "MVH" or "the client" for the external organization (not "you")?
- [ ] No sudden shifts to passive voice to avoid person?

### Tone Audit
- [ ] Technical claims supported by evidence?
- [ ] No casual language in formal sections ("kinda", "gonna", "stuff")?
- [ ] No overly formal language in operational sections?

### Certainty Audit
- [ ] ✅ claims backed by Finding # or Evidence #?
- [ ] Hedging language ("may", "could") only where genuinely uncertain?
- [ ] No false precision ("exactly 1,727" when estimate)?

### Density Audit
- [ ] Tables for structured data, prose for narrative?
- [ ] Bullet lists for enumerations >3 items?
- [ ] No wall-of-text paragraphs >10 lines?
```

### Common Voice Shifts and Fixes

| Shift | Example | Fix |
|-------|---------|-----|
| Tense drift | "We analyzed the data. We find that..." | "We analyzed... We found..." OR "We analyze... We find..." |
| Person shift | "We recommend that you migrate..." | "We recommend that MVH migrate..." |
| Passive creep | "It was determined that the migration..." | "We determined that the migration..." |
| Hedging inflation | "It could potentially maybe be possible..." | "Migration is feasible if..." |
| Formality break | "This is basically a no-brainer" | "The evidence strongly supports this approach" |

### Cadence: Sentence Rhythm

Vary sentence length to maintain reader engagement:

```markdown
## Monotonous (all same length)
The system processes 1,590 queries per second. The database contains 964 tables.
The storage totals approximately 28 terabytes. The cost runs $56,000 monthly.

## Better (varied rhythm)
The system processes 1,590 queries per second across 10 SQL MI instances.
That's 964 tables. Storage: ~28 TB. Monthly cost: $56K.

The heaviest database, prod-order, handles 51% of all queries — over 30 million
per day.
```

**Cadence guidelines:**
- Mix short punchy sentences with longer explanatory ones
- Use fragments sparingly for emphasis
- One idea per sentence in complex technical content
- Break up lists of numbers with narrative context

## When to Use

- **Document kickoff**: Establish voice in first draft
- **After merging content**: Different sources = different voices
- **Before publishing**: Full voice audit
- **When multiple authors**: Agree on voice guide first

## Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| Copy-paste voice | Pasted content has different voice | Rewrite to match host document |
| Meeting-notes style | "John said we should..." | Convert to formal recommendations |
| Email tone | "Just wanted to quickly mention..." | Professional technical prose |
| Academic hedging | "It would appear that perhaps..." | State findings directly |
| Marketing hype | "Revolutionary game-changing solution!" | Evidence-based claims |

## Real-World Example

From the Acme Corp TDD:

**Established voice:**
- Tense: Present for findings ("The system runs..."), future for recommendations ("Migration would require...")
- Person: First plural ("We") for internal team, third person for client
- Tone: Formal-neutral with evidence citations (Finding #, §X.Y)
- Certainty: High for confirmed data (✅ HIGH confidence), explicit hedging for estimates
- Density: Tables for inventories, prose for analysis, bullets for lists

**Consistency maintained across 3,067 lines** because:
1. Initial sections established the pattern
2. New content (§6 deliverables) followed same voice
3. Status markers (✅⚠️🔴⏳) provided visual consistency
4. Cross-references maintained formal citation style

## Related Skills

- `38_document_semantic_coherence.md` — Voice is part of coherence
- `37_technical_document_craftsmanship.md` — Overall quality standards
- `14_research_checklist_discipline.md` — Certainty requires evidence

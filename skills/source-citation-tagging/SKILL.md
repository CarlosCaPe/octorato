---
name: source-citation-tagging
description: "Tag taxonomy for mixed-source technical documents — every factual claim must carry a source marker. Defends against hallucinations, makes audits cheap, lets reviewers challenge specific claims by source rather than rejecting whole sections."
metadata:
  short-description: "Source citation tagging for mixed-source docs"
---

# Source Citation Tagging

## What

A discipline for technical documents (proposals, audit reports, RAG outputs, evaluations) that mix author analysis with quotes from external systems. Every factual claim is tagged inline with the kind of source it comes from. Untagged claims are treated as bugs.

## Why

Long technical documents quietly slide from sourced fact to author opinion to confident fabrication. By the time the doc reaches a reviewer, no one can tell which claim is grounded, which is an estimate, and which was hallucinated by an LLM mid-rewrite.

Tagging at write-time is cheaper than auditing at read-time. A document with citation tags survives:

- LLM-driven rewrites — the next pass cannot hallucinate a metric without inventing a tag for it; invented tags are easy to grep.
- Reviewer challenges — a reviewer can attack one `[vendor:URL]` claim without rejecting the whole doc.
- Stakeholder presentations — questions like "where does that 60% reuse come from?" have a literal answer attached to the line.
- Audits — running a citation pass means grepping for the tag set and reading the Sources Index, not re-reading 1500 lines.

Same principle as type annotations: redundant when you're confident, life-saving when you're wrong.

## The Tag Taxonomy

Use exactly these tags. Don't invent new ones unless the engagement actually has a new source class.

| Tag | Source class | Example |
|---|---|---|
| `[KB <key>]` | Internal knowledge base / canonical project state file | `[KB tooling_setup.api]` |
| `[<artifact-type> <date>]` | Captured pipeline output (logs, digests, exports) | `[digest 2026-04-30]`, `[scrape-log 2026-05-01]` |
| `[token]` / `[secret-store]` | Runtime artifact (typically gitignored) | `[token]` for a JWT |
| `[git]` | git log / git blame | `[git e417b30]` |
| `[vendor:<url>]` | Official vendor documentation (record URL + date) | `[vendor:cursor.com/pricing]` |
| `[author est]` | Explicit author estimate, no external source | `[author est — 60% reuse, no LOC mapping yet]` |
| `[Phase X]` | Open input to be validated by stakeholder during phase X | `[Phase 0]` |
| `[narrative]` | Author retrospective, not a falsifiable claim | for "framing pivot" sections |

The taxonomy is deliberately small. Five-to-eight tags is enough; more invites tag-soup where readers stop trusting any of them.

## When to Use

- Proposal docs to external clients (where the credibility cost of one false claim is high)
- Audit reports across systems
- RAG outputs that mix retrieved chunks with synthesized analysis
- Long technical evaluations (1000+ lines)
- Any document where a reviewer might reasonably ask "where does this number come from?"

Do NOT use for:
- One-page status updates (overhead exceeds value)
- Internal scratchpads / drafts
- Code comments — those have their own conventions

## Workflow

### 1. At write-time

Every factual statement gets a tag inline, immediately after the claim:

```markdown
- 137 items processed in last sync `[KB tooling_setup.last_sync.items_fetched: 137]`
- Cursor Business plan is $40/user/month `[vendor:cursor.com/pricing]`
- Pipeline reuses ~60% of existing code `[author est]` — Phase 0 to refine with LOC mapping `[Phase 0]`
```

If you cannot tag the claim, do one of:
- Find the source and tag it
- Mark it `[author est]` and own the estimate explicitly
- Remove the claim

Never write a confident factual claim without a tag.

### 2. Sources Index appendix

Every tagged document ends with a `## Sources Index` section listing every source by tag class:

```markdown
## Sources Index

### [KB] — <path-to-knowledge-file> v<X.Y.Z>
- <key-path-1> — <what it confirms>
- <key-path-2>

### [digest YYYY-MM-DD]
- <path-to-digest> — <line-count> items processed

### [vendor:<url>]
- <url> — <what it confirms>, checked YYYY-MM-DD
```

This is the reviewer's index card. Don't skip it.

### 3. Audit pass (combine with multi-specialist-doc-audit)

When auditing a doc:

```bash
grep -oE '\[(KB|digest|token|git|vendor:[^]]+|author est|Phase [0-9]+|narrative)[^]]*\]' doc.md | sort | uniq -c
```

- Compare untagged factual statements against the Sources Index
- Flag any `[vendor:URL]` whose URL no longer exists or contradicts the claim
- Flag any `[author est]` that has been in the doc for more than one phase without being refined

### 4. Rebuild from primary sources

If an audit reveals widespread hallucinations or unsourced claims, do not patch. Read all primary sources directly, then rewrite the doc with citations as you go. The first pass with discipline is cheaper than the third pass without.

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| Inventing a new tag class for one section | Tag taxonomy is the contract with the reader. Stretch it and the contract breaks. |
| Using `[author est]` as a wildcard to avoid finding the real source | Defeats the purpose. Use only when there really is no external source. |
| Tagging only "the suspicious" claims | Reader can no longer trust untagged claims. Either everything is tagged or the discipline is fake. |
| Tags on percentages but not on dates / counts / names | Numbers without sources are the most common hallucination vector. Tag them all. |
| Forgetting the Sources Index | Inline tags are pointers; the index is the resolution table. Without it, tags are noise. |
| Citing the doc you're writing in `[KB ...]` | KB is for the canonical project state file, not for the document under audit. |
| Tagging in headers | Cluttered. Tag in the body sentence below the header. |

## Composability

- `multi-specialist-doc-audit` — the audit pass that grades each tagged claim
- `doc-tree-consolidation` — when collapsing N docs into one, citation discipline preserves the audit trail across sources
- `document-code-review` (existing) — adds 9 mechanical-defect dimensions on top of citation discipline
- `peer-review-lifecycle` (existing) — formal review process; citation tags make reviewer comments addressable per-claim
- `cross-reference-integrity` (existing) — internal cross-refs (`§4.2`) are different from source citations (`[KB ...]`); both are needed

## Lessons Learned

- A five-specialist citation audit of a 1500-line proposal document found 15 hallucinations and 8 confident-but-uncited assumptions in a doc that "looked fine." Without inline tags, the audit would have been re-reading the whole thing.
- `[author est]` is honest engineering. A doc with 30 explicit `[author est]` markers is more trustworthy than one with zero — the second doc almost certainly has 30 hidden estimates dressed as facts.
- Tags survive LLM rewrites better than freeform citations. A model can rewrite "according to the vendor" into "as confirmed by industry leaders" without flagging anything. A model rewriting `[vendor:cursor.com/pricing]` into `[vendor:industry-leader.com]` is immediately greppable.

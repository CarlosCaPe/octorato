---
name: session-learn-extractor
description: "Extrae el patron reusable de la sesion y lo escribe como skill BORRADOR en skills/learned/. Dispara tras 'ya quedo', 'fixed', 'shipped', 'merged' sobre algo que costo varios pasos de investigacion, o via /learn."
metadata:
  type: brain-routine
  trigger: post-resolution (auto) or /learn (manual)
  origin: repo-deep-learn — affaan-m/ECC /learn + /skill-create (2026-05-28)
---

# Session Learn Extractor — Pattern Capture After the Fact

## Why this exists

Without it: every hard-won lesson dies in the session transcript. The next time it surfaces, the operator solves it again from scratch. Memories help (we have them) but they capture facts; skills capture reusable PROCEDURES.

With it: the moment a non-trivial problem closes, you draft a candidate skill. The operator skims, promotes the good ones, drops the noise. Brain compounds.

ECC ships this as `/learn` + `/skill-create` + an instinct system w/ confidence scoring. We adopt the simpler `/learn` half — the instinct layer is duplicative with our existing memories.

## When to fire

**Auto-trigger** when ALL of these hold in the current session:
1. The operator just expressed closure ("ya quedó", "done", "fixed", "shipped", "merged", "live", "✓").
2. The session involved at least one of:
   - ≥ 3 investigation steps (Read/Grep/Bash) before the fix
   - A workaround for a library/API quirk
   - A non-obvious diagnostic (logs misleading, error message wrong, etc.)
   - A multi-system interaction (e.g., GH Actions + secrets + branch protection)
3. There is NO existing brain skill that already covers the same procedure (quick connectome check: `python3 ~/.claude/scripts/query_connectome.py query "<problem keywords>"` — if MATCH ≥ 0.5, SKIP).

**Manual trigger** via `/learn` slash command — operator-initiated whenever they feel a pattern is worth keeping.

## Don't fire when

- Trivial 1-step fix (typo, single-char rename).
- Already-captured in a memory (operator may prefer memory over skill for one-off facts).
- The "fix" was an operator decision/override, not a transferable technique.
- A `learned/<slug>` already exists for the same topic (would be a duplicate).

## How it works (workflow)

### 1. Extract the kernel

Re-read the last N (≈10-30) tool calls of the session. Identify:
- **Symptom** — what was the visible failure or question?
- **Root cause** — what was actually wrong (after the dust settled)?
- **Fix** — what command/change resolved it?
- **Generalizable trigger** — what signal in future sessions should make us recall this?

### 2. Draft the skill

Write to `~/.claude/skills/learned/<kebab-slug>/SKILL.md` with frontmatter + body:

```markdown
---
name: <kebab-slug>
description: <when to use it; 1-2 sentences ending with the trigger condition>
metadata:
  type: lesson-learned
  status: draft
  captured: <YYYY-MM-DD>
  origin: session-learn-extractor (auto) | session-learn-extractor (manual /learn)
---

# <Title>

## Symptom
<what you'd observe in a future session>

## Root cause
<the actual underlying issue>

## Fix
<the specific commands/changes>

## How to recognize next time
<the diagnostic signal: an error string, a log pattern, a tool output shape>

## See also
- [[related-skill-or-memory]] (if any)
```

### 3. Hand off, don't auto-promote

DO NOT auto-move drafts from `learned/` to top-level `skills/`. Operator reviews + promotes via:

```bash
mv ~/.claude/skills/learned/<slug> ~/.claude/skills/<slug>
# then edit metadata.status: draft → active, drop the 'captured' field
# ai-push
```

This keeps the brain's `skills/` surface curated; `learned/` is the staging area.

## Output format (verbal report after writing the draft)

Single compact summary:

```
📝 Captured: <slug> — drafted at ~/.claude/skills/learned/<slug>/SKILL.md
   Why: <1-line — what made this non-trivial>
   Promote: mv ~/.claude/skills/learned/<slug> ~/.claude/skills/<slug>
```

Operator sees this once per closure event; never spam.

## Anti-patterns (don't do these)

- **Capturing trivial fixes.** A typo correction is not a skill. Use the bar: "would a future me appreciate having this written down?"
- **Auto-promoting drafts.** Forces operator review. Curated skills are the brain's value; un-curated noise is the brain's debt.
- **Duplicating existing skills.** Run the connectome check first.
- **Capturing client-specific procedures.** Skills are GENERIC. If the lesson only makes sense for one arm, save as a memory or arm-side skill instead.

## See also
- [[skill-creator]] — manual skill scaffolding (different intent; this skill auto-drafts after session, skill-creator is a tool to build from scratch)
- [[repo-deep-learn]] — sibling for external knowledge ingestion (this is internal session-knowledge)
- [[github-trending-curation]] — autonomous breadth discovery (this is reactive depth)
- [[do-not-ask-to-pause]] — fire the draft, don't ask "should I capture this?" — just do it

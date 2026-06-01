---
name: runtime-adaptation-over-source-edit
description: Decision rule for WHERE a new behavior or lesson belongs — the runtime layer (skill / memory / config / hook) vs the core source (CLAUDE.md). Default to the runtime layer; touch the core only when the change is a true invariant. Use whenever a lesson, preference, or new capability arrives and you must decide what to edit.
metadata:
  type: pattern-reference
  origin: octopus↔OS symbolism analysis — 2026-06-01 session (RNA-editing vs DNA match)
---

# Runtime Adaptation Over Source Edit

## The biology this encodes

The octopus **edits its RNA**, not its DNA. It recodes proteins on the fly — adaptation triggered by water temperature — **without ever touching the germline**. The DNA stays stable and inheritable; the RNA layer absorbs the environment. The OS does the same: you change behavior with `sysctl`, loadable modules, and config files **without recompiling the kernel**. The kernel ABI stays stable; the runtime layer absorbs the workload.

The brain is the third instance of the same pattern:

| Layer | Octopus | OS | Brain |
|---|---|---|---|
| **DNA** (stable, rarely edited, public, inheritable) | Germline genome | Kernel source / ABI | `CLAUDE.md`, the 4D core |
| **RNA** (adapts to environment, fast, reversible) | RNA editing | sysctl / modules / config | skills, memory, hooks, config |

## When this fires

A lesson, preference, gotcha, or new capability arrives and you reflexively reach for `CLAUDE.md`. **Stop.** Ask: is this DNA or RNA?

## The decision rule

**Default to RNA.** Route to the core (`CLAUDE.md`) ONLY if ALL three hold:
1. **Invariant** — it governs *every* turn, not a domain or a situation.
2. **Load-bearing** — other rules/skills depend on it being always-true (it's a primitive, not a leaf).
3. **Can't live elsewhere** — a skill/memory/hook genuinely can't carry it (it must be in the always-loaded context).

Otherwise:

| The thing is… | Goes to (RNA) | Not (DNA) |
|---|---|---|
| A technique / how-to | `skills/<name>/SKILL.md` | ❌ CLAUDE.md |
| A preference / correction / who-the-user-is | `memory/*.md` + MEMORY.md pointer | ❌ CLAUDE.md |
| An automatic behavior ("whenever X, do Y") | a hook in `settings.json` | ❌ CLAUDE.md |
| A tunable value / threshold / list | a config file (YAML/JSON) | ❌ hard-coded |
| A new domain capability | a new skill (after `harmonization-over-accretion` check) | ❌ CLAUDE.md |

## Why it matters (the cost of editing DNA by reflex)

- **`CLAUDE.md` is public and always-loaded.** Every line is a tax on every turn's context AND a permanent entry in a public git history. RNA layers are lazy-loaded and (memory/company) can stay private.
- **Mutating the germline is how you get a bloated, drifting core** — the same failure `harmonization-over-accretion` fights, but from the inside instead of by import.
- **RNA is reversible.** Delete a wrong memory, retire a stale skill. Reverting a core edit is a history rewrite.
- A change that adapts behavior **without touching the source** is the cheaper, safer, more octopus-like move almost every time.

## Tell / anti-pattern

> "I learned X, let me add a paragraph to CLAUDE.md."

That's editing DNA to record a phenotype. 9 times out of 10 X is a skill, a memory, a hook, or a config value. If you find yourself appending to the core for a *domain* or *situational* lesson, you skipped this rule.

## See also
- [[harmonization-over-accretion]] — the same lean-core discipline, applied to *imports* instead of *self-edits*
- [[skill-creator]] — when the RNA answer is "a new skill"
- [[peripheral-parallel-dispatch]] — sibling octopus↔OS pattern (center delegates, doesn't micromanage)
- [[octorato-symbolism]] — the 8→∞ / organic-brain anchors this draws on

---
name: doc-tree-consolidation
description: "Collapse N fragmented markdown docs into a small canonical set without losing content or breaking cross-references. Distinguishes mandatory-location files from consolidatable docs and dead-weight scaffolding."
metadata:
  short-description: "Fragmented N docs → canonical set, with mandatory-location preservation"
---

# Doc Tree Consolidation

## What

A workflow for repos where documentation has fragmented over time — multiple READMEs, partial handoff files, scattered subfolders with stub READMEs — into a small canonical set: typically `README.md` (entry), `<TOOLING>.md` (commands and structure), and one big topic doc per major subject.

## Why

Repos accumulate docs the way a closet accumulates jackets. Each one was important once. Five of them now overlap, three are stale, two reference deleted files. New contributors don't know where to start; existing contributors keep editing the wrong file.

Consolidation:
- Reduces the read-time tax on every new contributor
- Removes the "which file is the source of truth?" ambiguity
- Forces explicit decisions about what's stale (delete) vs current (merge) vs live in a mandatory location (untouched)
- Makes future audits cheaper — fewer files to keep coherent

## The Three File Classes

Every `.md` in the repo is exactly one of three classes. Classify before you touch anything.

### 1. Mandatory-location files — DO NOT TOUCH

These live at paths that tools/agents/CI assume by convention:

- `<repo>/.claude/CLAUDE.md` — AI agent instructions
- `<repo>/.claude/skills/<name>/SKILL.md` — skill definitions
- `<repo>/.claude/commands/<name>.md` — slash commands
- `<repo>/.github/copilot-instructions.md` — GitHub Copilot context
- Generated/derived markdown (digests, reports, runbooks that live next to their data)

If you delete or rename one of these, you break the convention silently. They are not part of the consolidation set.

### 2. Consolidatable docs — the actual fragmentation problem

Project docs that have grown by accretion: `README.md`, `HANDOFF.md`, `ARCHITECTURE.md`, `competitive-landscape.md`, `team.md`, `tdd-plan.md`, scattered `poc/*.md`, etc.

These are the consolidation set.

### 3. Dead weight — delete on sight

- 3-line stub `README.md` files in folders that haven't been touched in months
- Empty scaffold dirs (created during a template clone, never populated)
- Old `_v1.md`, `_old.md`, `_backup.md` versioned filenames (git is the version history)
- Files referenced by NOTHING (grep-confirmed)

## Workflow

### 1. Inventory

```bash
find . -name "*.md" -not -path "*/node_modules/*" \
  -not -path "*/output/*" -not -path "*/.git/*" \
  | sort
wc -l <each-file>
```

Classify each file into the three classes above.

### 2. Propose target structure

For consolidatable docs, the typical landing pattern is 3 files:

| File | Purpose | Length target |
|---|---|---|
| `README.md` | Top entry — what this is, where to go for what, status snapshot | 50–100 lines |
| `<COMMANDS>.md` (often `CLAUDE.md`) | How to use the repo — quick commands, folder structure, conventions | 100–200 lines |
| `<TOPIC>.md` (often `POC.md`, `ARCHITECTURE.md`, `RUNBOOK.md`) | The big content document — merged from N source files | 1000–2000 lines acceptable |

Anything beyond 3 canonical files is justified by domain (e.g., a separate `SECURITY.md` that compliance audits explicitly want as its own file).

### 3. Build a Change Manifest BEFORE writing anything

Required format:

```markdown
| # | Action | File | Reason |
|---|---|---|---|
| 1 | CREATE | README.md | Top entry that doesn't exist today |
| 2 | MODIFY | CLAUDE.md | Slim to commands + structure |
| 3 | CREATE | TOPIC.md | Unified merge of poc/* + HANDOFF.md durable parts |
| 4 | DELETE | HANDOFF.md | Folded into TOPIC.md |
| 5 | DELETE | poc/README.md | Folded |
| ...
| N | DELETE | brain/ (entire dir) | 3-line stub + unused Python scaffolds |
```

Then **stop and wait** for explicit user confirmation. No writes before approval.

### 4. Execute (only after confirmation)

- Write new files first
- Delete superseded files
- Update cross-references in any `*.json`, `*.yaml`, `*.md` that points at the deleted paths
- Validate JSON files still parse

### 5. Verify

```bash
# Count change
find . -name "*.md" | grep -v "/users/\|/output/\|/.claude/\|/node_modules/" | wc -l

# Stale references gone?
grep -rn "<deleted-file-1>\|<deleted-file-2>" --include="*.md" --include="*.json"

# Mandatory-location files untouched
git diff --stat | grep -E "^\.claude/|/SKILL\.md|/commands/" && echo "WARNING: mandatory-location file modified"
```

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| Touching mandatory-location files in a consolidation pass | Breaks tool/agent conventions silently. CI suddenly fails for unrelated reasons. |
| Skipping the Change Manifest | Aggressive deletes without preview = lost work. Manifest is the gate. |
| Merging without updating cross-references | `knowledge.json.docs_location` still points at deleted folder. Reader follows dead link. |
| Deleting "dead weight" without grep-confirming nothing references it | One stale-looking file is referenced by an automation you forgot about. |
| Versioned filenames (`*_v2.md`, `*_old.md`) preserved "just in case" | git is the version history. The filename clutter implies the new version isn't trusted. |
| Combining 5 docs into 1 without preserving citation tags from `source-citation-tagging` | Audit trail is lost. The merged doc reads as "trust the merger" instead of "here's the source for each claim." |
| Renaming `CLAUDE.md` → `INSTRUCTIONS.md` because it "looks better" | It's a mandatory-location convention. Don't rename. |

## Composability

- `source-citation-tagging` — preserve citation tags when merging multiple cited docs into one
- `multi-specialist-doc-audit` — audit the consolidated doc afterwards
- `cross-reference-integrity` (existing) — verify all `§X.Y` and `[link](path)` refs still resolve
- `document-semantic-coherence` (existing) — semantic coherence check on the merged doc
- `long-document-revision-protocol` (existing) — orchestrates other doc skills; the consolidated doc enters its workflow

## Lessons Learned

- A 14-doc → 3-doc collapse on a real engagement reduced file count 79% with zero content lost. The trick was the three-class taxonomy: 7 mandatory-location files were correctly identified and untouched; 5 dead-weight stub READMEs were deleted; 7 consolidatable docs merged into 3 canonical.
- The Change Manifest gate prevented an aggressive delete: an earlier pass without a manifest would have folded a sibling-session's `HANDOFF.md` into the merge before that session was finished. Showing the manifest first surfaced the coordination concern.
- Empty scaffold directories (created by a template clone, never populated) are easy wins. Five such dirs in one repo, ~50 deletions across them, zero references in git.
- `knowledge.json` (or any structured project-state file) almost always has a `docs_location` or `docs` array that points at the consolidated paths. Updating that file is part of the consolidation, not an afterthought.

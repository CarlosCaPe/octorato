# No History in Documents

## Purpose
Documents must contain only **current, active content**. Git is the version control system — documents are not.

## Triggers
- Any document edit, creation, or review
- Strikethrough text (`~~text~~`) used to mark completed/old items
- "DONE", "COMPLETED", "OBSOLETE" annotations left inline
- Commented-out sections kept "for reference"

## Rules

1. **Never use strikethrough** (`~~text~~`) to mark completed or superseded content. Remove it entirely.
2. **Never keep old text** alongside new text for "history" purposes. Git diff shows what changed.
3. **Completed items in checklists** — remove them or move to a separate "Completed" section only if the document's purpose requires showing progress (e.g., a living checklist). Otherwise, delete.
4. **Recommended Next Steps / Action Items** — once a step is done, remove it from the list. Don't strike it through.
5. **Superseded decisions** — replace with the current decision. The old decision lives in git history.
6. **"Previously..." / "Before..." / "Old approach..."** — don't narrate the evolution. State the current state only.

## Anti-Patterns (NEVER do these)

```markdown
<!-- BAD: strikethrough history -->
1. ~~**Obtain TEST workspace URL**~~ — DONE
2. **Validate existing PAT** — next step

<!-- BAD: keeping old content "for reference" -->
<!-- Old approach: we used to do X, now we do Y -->

<!-- BAD: inline change log -->
- ~~v1.0: Initial design~~ → v2.0: Revised after review
```

## Correct Patterns

```markdown
<!-- GOOD: only current steps remain -->
1. **Validate existing PAT** — next step
2. **List UC catalogs/tables** — ...

<!-- GOOD: state current reality only -->
The system uses approach Y.

<!-- GOOD: version is in frontmatter or header, history is in git -->
**Version**: 2.0
```

## Exceptions
- **Changelogs** (`CHANGELOG.md`) — these exist specifically to record history. Keep them.
- **ADR (Architecture Decision Records)** — "Status: Superseded by ADR-X" is acceptable per ADR convention.
- **Regulatory/compliance docs** — if audit trail is legally required in-document.

## Lessons Learned
- First identified in client ticket #186438 closure note where `~~Obtain TEST workspace URL~~` was struck through instead of removed.

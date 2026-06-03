---
name: coworking-concept-collision
description: Protocol for when two live sessions are codifying the SAME concept concurrently (not just sharing a working tree). Detect semantic friction BEFORE committing, defer ownership to whoever is further ahead, and integrate from an isolated dimension. Trigger — a file you are about to reference or claim primacy over shows as modified (M) by another live session, or your new skill overlaps a concept another dimension is actively editing.
metadata:
  type: lesson-learned
  status: active
  origin: session-learn-extractor (manual /learn, operator-promoted)
---

# Coworking Concept Collision — Defer, Measure, Integrate

## Symptom

Two live sessions on one brain tree. Session A is editing a skill (shows `M` in `git status`). Session B (you) authors a NEW skill that claims to "name a primitive for the first time" — and that primitive is exactly what session A is codifying. File-level isolation (worktrees, pathspec commits) does not catch this: the collision is **semantic**, not textual. Shipping both as-is creates two homes for one primitive (accretion) and at least one false claim in the public history.

## Root cause

Session isolation protects the *index*, not the *concept space*. `git` will happily merge two skills that contradict each other. The 4D gates check files you touch, not concepts you claim. Nothing fires when two dimensions converge on the same idea unless you read the other dimension's in-flight surface before asserting ownership.

## Fix

1. **Read before claiming.** Before committing any skill that names/owns a concept, check whether a file covering that concept is `M` by another live session (`git status` + `octo-dim list`). If yes, read its CURRENT content (the in-flight version, not HEAD).
2. **Defer to whoever is ahead.** If the other session already codifies the concept, it is the OWNER. Rewrite your claim: your artifact becomes a complementary layer (e.g. measurement vs definition, method vs rationale) that cross-links, never a second home. Two skills, one primitive, no fork ([[harmonization-over-accretion]]).
3. **Announce via the registry, not their files.** `octo-dim claim <your-paths>` so their dimension-awareness hook sees your lane. Suggestions for THEIR file go through the operator (Human Gateway) as a one-line suggestion — never edit their in-flight surface.
4. **Integrate isolated.** Commit your reconciled work in your own worktree/branch (`octo-dim worktree-init`), pathspec-only, and remove untracked originals from the shared tree so no foreign `git add -A` swallows them.
5. **Re-verify after they finish.** Their final committed version may differ from what you read in flight. Re-check your references (names, line claims) against HEAD before publishing.

## How to recognize next time

- `git status` shows the skill/doc your new work references as `M`, and `octo-dim list` shows another LIVE session.
- Your draft contains phrases like "had no named primitive before this" / "first to codify" — any primacy claim is a collision tripwire when other dimensions are live.
- The dimension-awareness hook warns "N other live dimension(s) share this working tree" while you are writing identity/concept content.

## See also
- [[session-isolation]] — the mechanism (worktrees, pathspec commits); this skill is the semantic layer on top
- [[harmonization-over-accretion]] — why two homes for one primitive degrades the connectome
- [[octorato-isomorphism]] / [[octorato-symbolism]] — the live case: symbolism owns the fractal primitive, isomorphism measures it

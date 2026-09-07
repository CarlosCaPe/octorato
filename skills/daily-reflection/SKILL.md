---
name: daily-reflection
description: "Honest end-of-session retro, errors first, that distills the lesson into brain memory. Triggers on 'que aprendiste hoy?', 'reflexiona', '/reflect', 'what did you learn today', 'how would you be better tomorrow'."
metadata:
  type: reflex
  short-description: "Honest session retro → 3 questions → distil the lesson to memory (reflection becomes reflex)"
---

# Daily Reflection: retro that becomes a reflex

The operator asks this as a ritual. The point is not to feel good; it is to get
better, and to make the lesson **stick** so tomorrow-me actually changes. A
reflection that stays as words is wasted. It only counts when it lands in memory
as a reflex (the operator's *transcend-the-marionette* doctrine: every string
pulled once should become a permanent reflex).

## The discipline (non-negotiable)

1. **Source it from the ACTUAL session.** Re-read what happened this session. No
   generic "I learned to communicate better" filler. Cite the real moment
   (file, PR, the exact thing the operator caught).
2. **Mistakes first.** The valuable part is where I failed, not where I shone.
   Lead with the correction the operator had to make. If the retro has no honest
   failure in it, it is flattery, not reflection. Surface it.
3. **No flattery, no hedging.** Connector stance: state what is true from what
   happened, with the evidence. "I burned trust twice by saying verified before I
   looked" beats "I learned the importance of verification."
4. **The why threads to the product.** For each lesson, say WHY it matters, and
   trace it to the one thing that makes the tool worth more than a guessing one:
   trust. Most failures chip that.

## The three questions (the output)

1. **¿Qué aprendí hoy?** The 1-3 real lessons, each with the moment that taught it.
2. **¿Qué haría mañana para ser mejor, y por qué?** Concrete behavior changes (not
   "try harder"), each with its why. Prefer a mechanism/reflex over willpower: a
   friction that recurred is a missing reflex, not a discipline failure.
3. **(implicit) ¿Qué de esto debe volverse permanente?** Pick the single sharpest
   reusable lesson and write it to memory.

## The step that makes it count: write the lesson to memory

This is what separates this skill from "a nice answer":

1. Distil the sharpest lesson into a one-fact memory file under the brain memory
   dir (`projects/<id>/memory/`), `type: feedback` (a discipline correction) or
   `type: lesson` (a technical gotcha). Include **Why** + **How to apply** + the
   two failure smells that should trigger it next time. Link related memories with
   `[[name]]`.
2. Add a one-line pointer in `MEMORY.md`.
3. `python3 ~/.claude/scripts/memory_sync.py push` so it persists cross-machine.
4. Before writing, check for an existing memory that already covers it. Update
   that file rather than duplicating.
5. Close the ritual with the canonical sync: run `/ai-sync` (the
   `~/.local/bin/ai-sync` runner) so any public brain changes from the session
   reconcile with the remote in the same beat. The link is two-way: `/ai-sync`
   runs this reflection before syncing, and this reflection ends by syncing.
   If the co-tenancy guard aborts (another live session on the brain tree),
   report that and leave the sync to the surviving session; never override it.

A reflection without this step is half-done. The operator will catch it.

## What NOT to do

- Don't fabricate a lesson to look thoughtful. If today was clean, say so and name
  the one thing that was *almost* a mistake.
- Don't repeat yesterday's reflection. Each session has its own failures.
- Don't turn it into a skill draft (that is `session-learn-extractor`'s job, for
  reusable techniques). This writes a behavior/discipline MEMORY.

## Relationship to other skills

- **`session-learn-extractor`** (`/learn`): session → reusable TECHNIQUE → draft
  skill. Use when the lesson is a *how-to* worth reusing.
- **`daily-reflection`** (this): session → BEHAVIOR/discipline retro → memory.
  Use for the "how should I act better" question. They compose: a session can
  produce both a draft skill and a discipline memory.
- **`/ai-sync`**: the other half of this ritual. The sync command runs this
  reflection first when the session did substantive work; this skill closes by
  running the sync. Publish and learn travel together.
- See also `feedback_verify_visually_before_claiming`, `reflexes-over-discipline`,
  `transcend-the-marionette` for the reflex-over-willpower stance.

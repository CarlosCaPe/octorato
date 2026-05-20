# Plan — Octorato Symbolic Layer

Spec: `feature.md` (this directory)
Complexity: LARGE (score 14)

## Tasks

1. [x] Write `skills/octorato-symbolism/SKILL.md` (full reference, ~600 words)
2. [x] Add short reference paragraph to `README.md` linking to the skill
3. [x] Write spec docs (`feature.md` + this `plan.md`)
4. [ ] Open brain PR with skill + README + spec docs
5. [ ] Enable auto-merge on brain PR
6. [ ] Pull the operator-side launch arm `main`, create branch
7. [ ] Add ~110-word paragraph to `article-longform-en.md` after the brain–arm description
8. [ ] Add ~17-word stanza to `post-short-en.md` after the wedge bullets
9. [ ] Open arm PR with the 2 marketing changes
10. [ ] Enable auto-merge on arm PR

## Follow-up (queued, separate PR)

- CLAUDE.md slim-down: 557 lines / 9.4K tokens → target <250 lines / <5K tokens
- Move detailed 4D protocols, agent division tables, QueryMaster details, arm-onboarding into dedicated skills
- Keep CLAUDE.md focused on rules + pointers

## Validation (3D Diligent)

- [ ] `check-generic.py` passes on brain PR
- [ ] `neural_map.json` rebuilds cleanly (brain-pr-checks workflow)
- [ ] Article + post read cleanly with the additions (no flow breaks)

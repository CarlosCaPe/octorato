<!-- Octorato PR template. The brain is public + open-source; every diff is
     visible on GitHub forever. Confirm the generic-safety boxes before merge. -->

## What & why

<!-- One paragraph: what this change does and the reason. -->

## Type

- [ ] New skill (`skills/<name>/SKILL.md`)
- [ ] New / updated agent persona (`agents/`)
- [ ] Framework rule (`CLAUDE.md`, enforcement scripts)
- [ ] Docs / wiki / README
- [ ] Tooling / scripts
- [ ] Fix

## Generic-safety checklist (MANDATORY — the brain is public)

- [ ] No client names, coworker names, internal codenames, ticket IDs, or
      internal URLs — in file contents, filenames, branch name, or commit message
- [ ] No secrets / tokens / keys (those live in `.env` / vault)
- [ ] No SDD artifacts (`feature*.md` / `plan*.md` / `spec*.md`) at repo root
      (they belong in `docs/specs-archive/` or `templates/`)
- [ ] `scripts/check-generic.py` passes locally
- [ ] If this is a lesson learned from an arm, it has been **distilled to a
      generic skill** before landing here

## 4D discipline

- [ ] **Diligent** — validated (build / lint / test / render, as applicable);
      evidence below
- [ ] **Disclose** — Impact Radius noted: where else does this object live?

## Evidence

<!-- Paste the validation output, screenshot, or 1-line "verified by …". -->

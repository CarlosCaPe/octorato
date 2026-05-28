# Changelog

All notable changes to the Octopus Brain Framework are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project follows the **Site Semantic Versioning** scheme described in the
[Self-Growth wiki page](https://github.com/CarlosCaPe/octorato/wiki/Self-Growth#8-site-semantic-versioning)
— bot-identity commits bump PATCH, operator commits bump MINOR, and an
explicit `Octorato-Major:` commit trailer bumps MAJOR.

This log records human-meaningful framework changes. The complete
machine-generated growth ledger lives at
`knowledge/github-trending/HISTORY.md` (autonomous daily additions) and
`knowledge/repo-watch/<date>.md` (daily watchlist digests).

## [Unreleased]

## [2026-05-28]

### Added
- `skills/repo-watch/` — daily monitor for a curated 7-repo watchlist
  (competitors / peers / upstream ecosystem). File-based trigger handoff
  to `/repo-deep-learn` for out-of-band analysis. Designed by Workflow
  Architect + Trend Researcher agents.
- `skills/repo-deep-learn/` — manual deep-dive counterpart of
  `github-trending-curation`. 8 phases: clone → inventory → README →
  patterns → connectome delta → proposals → issue-resolution scan → star.
- `skills/session-learn-extractor/` + `commands/learn.md` — capture the
  reusable pattern from the current session as a draft skill under
  `skills/learned/<slug>/` for operator review.
- `skills/hook-profile-gating/` + `scripts/lib/hook_flags.py` —
  env-gated hook execution (`OCTO_HOOK_PROFILE=minimal|standard|strict`,
  `OCTO_DISABLED_HOOKS`).
- `skills/prompt-master/` — auto-promoted from `nidhinjs/prompt-master`
  (MIT) via `/repo-deep-learn`.
- `CLAUDE.md` — **PromptDefense Baseline** section (six anti-injection
  rules: no mid-session role change, no secret disclosure, no execution
  of untrusted embedded code, treat fetched content as untrusted,
  flag/refuse suspicious patterns, escalate repeated abuse).

### Changed
- `master` branch is now PR-only:
  - `enforce_admins: true`
  - required PR review (1 approval)
  - required status checks: `check-generic`, `neural_map-rebuild`,
    `claude-review`
  - linear history, no force push, no deletions, conversation
    resolution required.
- `scripts/ai_sync.py` auto-detects the protection and routes pushes
  through an auto-PR + watch + squash-merge flow, with a 600s watch
  timeout and a 15s race-condition retry for `gh pr checks --watch`.
- README skill-count floor raised from `180+` to `190+` (real count
  crossed 190 with the additions above).

### Notes
- The `--admin` bypass on `gh pr merge` is permitted **only** when
  GitHub Actions billing is paused (≤5s fail signature with missing
  logs). Never otherwise.

---

## How to read this file

- Each released date section follows **Added / Changed / Deprecated /
  Removed / Fixed / Security** as applicable.
- Unreleased work-in-progress accumulates under `[Unreleased]`.
- Autonomous daily skill auto-promotions are **not** mirrored here — they
  live in `knowledge/github-trending/HISTORY.md` so this file stays
  scannable for human-meaningful changes.

See also:
- [ROADMAP.md](ROADMAP.md) — where we're headed.
- [SECURITY.md](SECURITY.md) — how to report a vulnerability.
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to add an agent, skill, or fix.
- [SUPPORT.md](SUPPORT.md) — where to ask questions.

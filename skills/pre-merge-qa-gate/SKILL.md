---
name: pre-merge-qa-gate
description: Before arming auto-merge on a PR that touches production code, dispatch a QA specialist agent against an explicit test/user-case spec for the diff. Build-passes ≠ correct. Auto-merge is the merge mechanism, not the gate.
metadata:
  type: skill
---

# Pre-Merge QA Gate

## What

A discipline for AI-driven dev: **no PR lands without an agent-validated QA pass against an explicit test/user-case spec**. Auto-merge SQUASH is fine as the *merge mechanism*, but the gate that precedes arming auto-merge is the QA agent verdict.

Build pipelines (`astro check`, `tsc --noEmit`, unit tests) tell you the **code compiles**. They do not tell you:
- Whether the click handler actually wires to a real endpoint
- Whether the endpoint validates CSRF on the body field your form posts
- Whether the new directive in CSP silently breaks Svelte hydration
- Whether the screen reader can hear the loading state
- Whether the diff matches its stated user case

Those failures are the kind that ship to production looking green and break operators silently. The pattern below catches them BEFORE the merge.

## When

Activate this discipline for any PR that:

- Touches production-facing code (admin, public site, API endpoints, auth, security headers)
- Modifies UI components mounted on real user surfaces
- Adds, changes, or removes any state-mutating endpoint
- Migrates between paradigms (Svelte 4 → 5, framework upgrades, CSP hardening, etc.)
- Refactors anything where the runtime behavior is not obvious from the diff

**Skip** (TRIVIAL): typo fixes, comment-only changes, README updates, dependency bumps with no API surface change. For those, a 2-line manual review note in the PR body suffices.

**Escalate** (LARGE): 10+ files, security-relevant, multi-domain (frontend + backend + a11y). Use multiple specialist agents in parallel.

## How

Four steps before arming auto-merge SQUASH:

### 1. Build locally first

`npx astro build` (or the project's equivalent). Must pass. This eliminates the trivial "broken code" class so the agent's time goes to behavioral verification.

### 2. Compose the test/user case spec for the diff

Either:
- **Lift** from an existing spec (e.g. a Workflow Architect's complete inventory of the surface), filtered to the elements your diff touches, OR
- **Write fresh** — one row per interactive element: `| Page | Element | User Case | Test Case |` where User Case is what the operator expects in plain language and Test Case is the verifiable assertion (curl, file:line, click sequence with assertion).

The spec is the contract the QA agent validates against. Without it, the agent has nothing to compare to and you get "looks fine" hand-waving.

### 3. Dispatch the gate — `/bug-hunter --pr` is the default

The DEFAULT gate is now **`/bug-hunter --pr`** (the `bug-hunter` brain skill — adversarial 3-agent pipeline: Hunter → Skeptic → Referee). Single-shot reviewers (Reality Checker alone) have a documented false-approve rate on schema, contract, and framework-reactivity bugs (see "Why this upgrade" below).

Invocation:

```
/bug-hunter --pr current --scan-only
```

`--scan-only` keeps it in review mode (no auto-fixes — the operator owns the merge). Output: `.bug-hunter/referee.json` with verdict per finding + severity. **Auto-merge gate**: only arm when no finding has `severity >= HIGH`.

The 3-agent flow:
1. **Hunter** searches the diff for bugs. Has shell/Read/Grep access — can `grep migrations/` to verify column names, `npx tsc --noEmit` for type errors, `wrangler d1 PRAGMA table_info(...)` for schema sanity.
2. **Skeptic** tries to disprove each Hunter finding. Penalty for missing a real bug ≫ penalty for over-skepticism → less false-approve.
3. **Referee** delivers the verdict, surviving findings only.

#### When to layer additional specialist agents

`bug-hunter` is general-purpose. Layer a specialist agent IN PARALLEL when the diff touches a narrow domain it doesn't deeply model:

| Diff touches | Layer also |
|---|---|
| ARIA / keyboard / SR | Accessibility Auditor |
| CSP / security headers | Security Engineer + Frontend Developer |
| Cryptography / auth tokens | Security Engineer |
| Visual rendering / animation jank | Frontend Developer + Evidence Collector |
| Stripe / payment-flow | Stripe specialist (per arm) |
| SDD-LARGE-score (≥6, 10+ files, multi-module) | `/ocr:review` (open-code-review) as third reviewer with `feature.md` |

Reality Checker is now a **specialist** for "acceptance criteria / spec compliance" — invoke when the PR has an explicit `feature.md` or `plan.md` to verify against. It's good at that. It is NOT the default gate anymore.

Brief any agent with:
- The PR diff or branch
- The test/user case spec (or `feature.md` if the PR has one)
- An explicit instruction: "Default verdict NEEDS WORK — require concrete evidence (file:line citation, curl response, agent-browser screenshot, tsc output, grep result) before approving anything. Run shell commands to verify schema/contract claims, do not trust source-code reading alone."

### 4. Only after agent verdict, arm auto-merge

If `✅ VERIFIED` → arm `gh pr merge <N> --auto --squash` and let CI complete the merge.

If `⚠️ PARTIAL` → decide whether to ship with caveats (document the unknown in the PR body) or wait for more evidence.

If `🚨 NEEDS WORK` / `BROKEN` → fix the issues, rebuild, re-validate. Do not merge.

Post-deploy live verification (cache-bust curl + agent-browser screenshot) is still recommended, but no longer the *primary* gate. The agent gate runs against the build, the live check confirms the deploy applied cleanly.

## Anti-patterns to refuse

- **"I'll ship and ask the user to validate"** → No. Validate first.
- **"Auto-merge will land it; the user will tell me if broken"** → No. The operator's time is expensive; agents are cheap.
- **"Build green = correct"** → No. Build verifies compilation, not behavior.
- **"This change is small"** → If small means TRIVIAL (typo, comment), skip the gate. If small means "small in lines but touches auth / CSP / hydration", run the gate.

## Exception: documented bypass with operator nod

If the operator explicitly says "hazlo directo" / "ship it now" for a TRIVIAL-but-urgent fix (incident response, hotfix to recover from a previous deploy), the gate can be bypassed with an explicit note in the PR body: `QA-gate-bypass: operator-authorized hotfix for <incident-id>`. The bypass is loggable; the rule still applies for everything else.

## Why this exists

A session 2026-05-21 shipped multiple PRs through `gh pr merge --auto --squash` after `npx astro build` passed. Two HIGH-severity bugs only surfaced when specialist agents were finally dispatched after operator complaints:

- A CSP directive (`require-trusted-types-for 'script'`) compiled fine, deployed fine, and silently killed every Svelte islet's hydration → all admin buttons dead, theme toggle dead, locale switcher dead. Found by Frontend Developer agent.
- Seven endpoints had CSRF *documented* but *unwired* — `verifyCsrfToken` was header-only while two of them posted via native HTML form (no header possible) and nine others never called the function at all. Found by Reality Checker agent.

Both would have been caught by a pre-merge agent dispatch against the test/user case spec. After the incident, the operator set the rule explicitly: "regla número 1 en los deploys: no puede haber deploy si el QA no lo aprobó."

This skill captures the rule.

## Why this upgrade (2026-05-22)

Reality Checker (single-shot single-agent) **passed** the following bugs that hit production:

- PR #96 — RE share-targets: missed `created_at` vs `added_at` column mismatch (D1 500 on first hit).
- PR #98 — asset-derive: missed PNG poison-pill (CPU stuck reprocessing failures forever).
- PR #100 — KPI proxy query: APPROVED `scheduled_at <= datetime('now')` where ISO `T` vs SQLite space-separator made the predicate always false → permanent 0.
- PR #111 — status enum: APPROVED client sending `'unshared'` while server only accepts `['shared','skipped','removed']` → undo silently 400'd.
- PR #112 — Svelte `{@const}` reactivity: missed the reactive-dep tracking gap → cell visual stuck after share.

Common pattern: Reality Checker reads source files and cites file:line. It does NOT run `npx tsc`, does NOT `grep migrations/` to verify column names, does NOT send a mock request to verify server↔client contracts, does NOT inspect framework reactive graphs.

`/bug-hunter` (Hunter + Skeptic + Referee) fixes the structural gap:
- **Tool access**: Hunter can shell out (`grep`, `tsc`, `wrangler`, `sqlite3`) to verify a claim before reporting.
- **Adversarial debate**: Skeptic is penalty-incentivized to disprove findings → over-zealous Hunter gets corrected, but under-zealous Skeptic also loses → balanced.
- **Framework verification**: doc-lookup sub-skill (Context7) checks Svelte 4 / React / Vue reactivity docs against the diff.

Reality Checker stays in the toolbox as a specialist for SDD acceptance-criteria verification, where its strength (close reading + citation) shines.

## Related

- `bug-hunter` — the adversarial 3-agent gate this skill now dispatches as the default.
- `4d-paradigm-protocol` — 3D Diligent phase already required validation evidence; this skill makes the "evidence" concrete = agent verdict, not just build pass.
- `post-check-verification` — what to do AFTER the deploy lands (live curl + cache-bust). Complementary to the pre-merge gate.
- `dry-run-gate-pattern` — analogous gate for destructive operations (preview before write). Pre-merge QA gate = preview before merge.
- `pr-first-on-auto-deploy-main` — pairs with this: PR forces a review surface, this gate forces the agent review on top of CI.

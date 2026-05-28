---
description: Extract the reusable pattern from the current session and save it as a draft skill at ~/.claude/skills/learned/<slug>/SKILL.md for operator review.
---

# /learn — Capture What We Just Solved

Manual trigger for the [[session-learn-extractor]] skill. Run after solving a non-trivial problem when the auto-trigger didn't fire (or when you want to force capture even for a "barely non-trivial" case).

## Workflow

1. Load `skills/session-learn-extractor/SKILL.md`.
2. Re-read the last 10-30 tool calls of this session.
3. Extract: symptom → root cause → fix → recognition signal.
4. Run a connectome dedup check:
   ```bash
   python3 ~/.claude/scripts/query_connectome.py query "<short problem description>"
   ```
   If a skill scores ≥ 0.5, SKIP — surface the existing skill name instead. Otherwise continue.
5. Pick a kebab-slug (max 4 words) that names the pattern.
6. Write the draft skill to `~/.claude/skills/learned/<slug>/SKILL.md` following the template in the skill file.
7. Report:
   ```
   📝 Captured: <slug>
      Drafted at ~/.claude/skills/learned/<slug>/SKILL.md
      Why: <1-line>
      Promote: mv ~/.claude/skills/learned/<slug> ~/.claude/skills/<slug>
   ```

DO NOT auto-promote. DO NOT `ai-push` the draft (the `learned/` subtree stays local until the operator approves; future improvement: gitignore `skills/learned/` so drafts don't pollute the public brain until promoted).

## When NOT to use

- Trivial fix (typo, single-char rename)
- Operator decision (not a transferable technique)
- Already captured (connectome scored ≥ 0.5)

See [[session-learn-extractor]] for the full rationale + auto-trigger conditions.

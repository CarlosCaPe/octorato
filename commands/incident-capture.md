---
description: Capture a structured post-mortem when something went wrong. Walks operator through 4 questions, writes ~/.claude/incidents/<date>-<slug>.md + auto-memory feedback rule + follow-up tasks.
---

You are running the **Incident Capture** flow (Datadog Port 6 — Phase D).

Load and follow the skill at `~/.claude/skills/incident-capture/SKILL.md` for the full workflow, file template, and AC.

## Immediate steps when this command fires

1. Acknowledge briefly that incident capture is starting.
2. Pull the session_id from the current context. Compute `task_id = sha1(session_id)` so you can cross-link the trace later.
3. Ask the operator 4 questions, **one at a time** to avoid overwhelming them. Use their language (Spanish if they've been writing in Spanish, otherwise English):
   - **Q1**: ¿Qué pasó? (one-line headline)
   - **Q2**: ¿Qué esperabas?
   - **Q3**: ¿Qué ocurrió en realidad?
   - **Q4**: ¿Cuál es tu mejor sospecha de la causa raíz?
4. Once you have the 4 answers:
   - Generate a slug from Q1 (lowercase-kebab-case, max 40 chars, ASCII-only).
   - Ask the operator for **severity** (low / medium / high / critical) via AskUserQuestion.
   - Invoke `~/.claude/scripts/incident-capture.py` with the parsed args.
5. Read the generated incident file back and show the operator a brief summary.
6. Ask: "¿Hay acciones de remediation que quieras trackear como tasks?" — if yes, create them via TaskCreate.
7. Optional: if severity ∈ {high, critical}, ask whether to open a GH issue in the brain repo (`gh issue create --repo CarlosCaPe/octorato --label brain-incident`).

## Boundary rules

- If CWD is inside `~/Documents/github/<arm>/`, refuse to write the incident to `~/.claude/incidents/`. Suggest the operator write to `<arm>/docs/incidents/<date>-<slug>.md` instead. The brain stores ONLY brain-level incidents. Arm incidents stay in the arm. This preserves arm isolation.
- The lesson (auto-memory feedback) MUST be generic — no arm codes, no client names, no internal URLs. The skill's "lessons learned" section gets distilled into the feedback rule.

## Output to operator

- Path of the incident file written
- Path of the feedback memory entry created
- Number of TaskCreate items added
- Brief one-sentence summary of the "lessons learned" that future sessions will see

Done. Hand control back to the operator.

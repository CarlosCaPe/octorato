---
name: incident-capture
description: Capture a structured incident when the brain produces a bad outcome — bad skill output, redone task, critical 3D Diligent failure. Writes a markdown post-mortem with frontmatter, snapshots the relevant trace, saves the lesson as auto-memory feedback, and creates follow-up TaskCreate entries. Use when something goes wrong and the operator wants to record the lesson without losing context.
---

# Incident Capture (observability surface 6)

This surface captures structural learning when a session produces a bad outcome (skill output broke, operator had to redo a task, 3D Diligent surfaced something critical).

## When to use

Trigger any of these:
- Operator says "incidente", "incident", "vamos a documentar esto", "perdí trabajo por X", "redo".
- A 3D Diligent gate fails AND the failure is non-trivial (not a typo, not a re-staging issue).
- The operator dismisses a Watchdog or SLO issue with an explanation worth keeping.
- The operator says `/incident-capture` explicitly.

## Workflow

1. **Snapshot the trace.** Capture the current session's task_id (sha1 of session_id) and pull the related `~/.claude/traces/<today>.jsonl` lines into the incident file.
2. **Ask the operator 4 structured questions** (in their language):
   - ¿Qué pasó? (one-line headline)
   - ¿Qué esperabas? (expected outcome)
   - ¿Qué ocurrió en realidad? (actual)
   - ¿Causa sospechada? (root cause guess)
3. **Generate slug** from the headline: lowercase-kebab-case, max 40 chars.
4. **Write the incident file** at `~/.claude/incidents/<YYYY-MM-DD>-<slug>.md` with frontmatter (see template).
5. **Save the lesson** as an auto-memory entry: `~/.claude/projects/.../memory/feedback_<slug>.md` with type=feedback. Body reuses the "cause + how to apply" from the incident.
6. **Create follow-up tasks** via TaskCreate — one per remediation item identified.
7. **(Optional)** Open a GH issue in the brain repo when severity = critical.

## File template

```markdown
---
incident_id: 2026-05-19-redo-multireach-fix
date: 2026-05-19
severity: medium  # low | medium | high | critical
trigger: manual   # manual | watchdog | slo | diligent
task_id: <sha1 of session_id>
related_traces: traces/2026-05-19.jsonl
status: open     # open | resolved | wontfix
---

# Incident: <headline>

## What happened
<one sentence>

## What we expected
<...>

## What actually happened
<...>

## Suspected root cause
<best guess>

## Trace excerpt
<filtered JSONL lines from the session>

## Lessons learned
<distilled into a feedback rule — gets mirrored to feedback_<slug>.md in auto-memory>

## Remediation actions
- [ ] task 1  (TaskCreate #N)
- [ ] task 2
```

## Storage rules (arm isolation)

- Brain-internal incidents (skill/agent failures, brain-level lessons) → `~/.claude/incidents/`.
- Arm-specific incidents → in the arm's own repo, never in the brain. The skill detects arm-context by CWD and refuses to write to `~/.claude/incidents/` if CWD is inside a `<arm>/` directory; instead it suggests writing to `<arm>/docs/incidents/<date>-<slug>.md`.

## Privacy

- `~/.claude/incidents/` is **gitignored** at the brain level (private operational data — sometimes contains operator-specific debugging notes, paths, partial credentials in error messages).
- The auto-memory `feedback_<slug>.md` is also gitignored (already covered by the existing memory gitignore).

## Helper script

`~/.claude/scripts/incident-capture.py` — writes the incident file given parsed answers. Used by this skill to keep file format consistent.

Usage:
```bash
python3 ~/.claude/scripts/incident-capture.py \
  --headline "Redo Multireach fix because cache key collision" \
  --expected "Cache key isolates per channel" \
  --actual "Two channels shared the same key, second overwrote first" \
  --cause "Forgot to include channel_id in cache key derivation" \
  --severity medium
```

The skill orchestrates: ask → call script → save memory → TaskCreate.

## Why this matters

Incidents that aren't captured become "I think we already fixed something like this last month?" 3 months later. The auto-memory feedback file IS the long-term mitigation — future sessions read it and avoid the same trap.

## AC coverage

- AC-1: `/incident-capture` slash command (see `~/.claude/commands/incident-capture.md`)
- AC-2: markdown with frontmatter — schema above
- AC-3: cross-links to `~/.claude/traces/<date>.jsonl` (related_traces field)
- AC-4: lesson auto-saved as `feedback_<slug>.md` in auto-memory
- AC-5: remediation actions via TaskCreate

## Non-goals

- External pager integration (single operator, no on-call rotation)
- Auto-trigger from runtime hooks (manual operator-driven only — false positives kill signal)

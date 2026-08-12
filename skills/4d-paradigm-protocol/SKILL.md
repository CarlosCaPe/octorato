---
name: 4d-paradigm-protocol
description: "Protocolo completo del paradigma 4D (Describe, Delegate, Diligent, Disclose): el gate de 3 preguntas del 2D, el formato del Change Manifest, la matriz de validacion 3D y el Impact Radius. CLAUDE.md solo trae el resumen. Carga antes de escribir archivos o armar un manifiesto."
metadata:
  type: paradigm-protocol
  short-description: "Operational templates: 4D gate format, 3Q delegate protocol, diligent matrix, impact radius scan, anti-patterns"
---

# 4D Paradigm — Full Operational Protocol

This skill carries the formats, templates, and tables for the 4D Paradigm. The summary lives in `~/.claude/CLAUDE.md` and is always loaded. The details below are loaded on-demand.

## The Four Phases

1. **Describe** — Before acting, state what you'll do and why. No silent changes. Example: "I'll add an index on HospitalId to fix the seq scan. This is a read-only schema change."
2. **Delegate** — Use subagents for complex research. Don't guess when you can verify. Search the codebase, read docs, check history before generating output.
3. **Diligent** — Evaluate output quality. Run tests, check errors, validate results. After every change: build/lint/test. After every query: check row count, null ratios, schema match.
4. **Disclose** — Always state implications. If a change has side effects, say so before proceeding. Before applying any change, run an Impact Radius scan (see below) to find all upstream/downstream references. **Delivery cadence:** every output ships through the Human Cadence 10 no-rules (`skills/human-cadence/SKILL.md`, summary in CLAUDE.md §Communication) so the text reads like a person, not a model — no em-dash, no AI filler, no triads, varied rhythm, contractions. Disclose is *how* you say it as much as *what* the impact is.

## Signal Flow (ENTRADA → SALIDA)

```
ENTRADA (before acting):
  1D DESCRIBE  → "I will do X because Y" (task type, scope, files)
  2D DELEGATE  → checked REGISTRY.md, loaded skills, use/skip subagent
        │
  ┌─────▼─────┐
  │ 4D GATE   │ ← STOP. Manifest. Confirm. No writes without approval.
  └─────┬─────┘
        ▼ confirmed → EXECUTE
SALIDA (after acting):
  3D DILIGENT  → PASS/FAIL with evidence (build/lint/test). Fix before "done".
  4D DISCLOSE  → impact: N changed, M orphans, side effects, Impact Radius
```

**Rule:** 1D+2D fire BEFORE action; 3D+4D fire AFTER. Gate sits in the middle. The agent MUST visibly report all 4 phases or the response is incomplete.

## The Reflective WHILE — 4D runs in a loop, not once

The Four Phases are ONE contraction (begin→end). A single 4D pass is a function call; a living brain LOOPS:

```
while (open work / remnants / something to improve):
    4D()                       # Describe → Delegate → [Gate] → act → Diligent → Disclose
    read the Provenance footer # the loop CONDITION and the trigger of the next beat
# exit only when the footer's self-read shows zero open remnants — never on "looks done"
```

- **The WHILE is the heartbeat.** The `connectome-heartbeat` hook is this pulse (it beats every prompt). Don't exit a task on green; exit when the footer reports nothing open. See [[do-not-ask-to-pause]].
- **The Provenance footer is proprioception** — the brain sensing its own action (what it touched, which engine/arm, on whose authority, verified how). Self-modeling is what makes the loop reflective rather than blind. It sits at the systole→diastole boundary: reading it both (a) evaluates continue-vs-exit and (b) ends the response, firing the Stop hook + the next prompt's hooks. The end of one beat IS the trigger of the next.
- **Who fires the hooks?** The harness, autonomically, on events (the involuntary reflex arc). But the footer's CONTENT is authored by the agent looking at its own trace — reflex fires it, reflection fills it, and both operator and agent act on it.
- **Octopus morphology:** brain = orchestrator running 4D · arms = sub-agents/hooks (semi-autonomous reflexes) · heartbeat = the WHILE · proprioception = the Provenance footer. Full model in [[feedback_4d_while_reflective_loop]].

**Three hearts, one circulation — NOT three identical whiles.** An octopus has 3 hearts (2 branchial that *oxygenate*, 1 systemic that *distributes*) — differentiated pumps serving one bloodstream, not three copies of the same pump. So the brain runs loops differentiated by SCOPE/cadence sharing ONE signal (the footer/heartbeat), never replicated whiles:

| Heart | Loop | Cadence |
|---|---|---|
| Systemic (distributes) | the per-response **4D while** (the task beat) | fast, per turn |
| Branchial (oxygenates) | the **autonomic per-prompt** loop (connectome-heartbeat: refresh context + route before acting) | each prompt |
| Branchial (oxygenates) | the **learning/observability** loop (gap→graduate at 3×, finops/brain digests, repo-watch) | slow, cross-session |

Writing three identical whiles "because three hearts" is cargo-culting the metaphor — redundant loops contend and dilute (see [[harmonization-over-accretion]]). Map the metaphor's *function* (differentiated pumps), never its *count*. Loops must share state, or they desync like divergent counts.

### The Provenance footer (materialized 4D Disclose)

Every response ends with a one-line footer (label **Provenance / Procedencia / Herkunft**, matching the user's language). Named fields, ` · `-separated, each included ONLY when it applies:

- **Basis** — on whose authority (own reasoning / vendor·doc / operator / `file:line`). The files that came IN.
- **Engine** — main-loop model + any sub-agent/sub-tool on a different engine (e.g. a Haiku arm). Makes [[model-routing-by-complexity]] visible.
- **Touched** — files written this turn (`+` created, `~` modified, `-` deleted). The files that went OUT. OMIT on read-only turns.
- **Verified** — one-line 3D evidence. OMIT when nothing was written.

**Paths must be OPENABLE, not merely identifying.** Both `Basis` and `Touched` name real artifacts the operator will want to open, so every path is written **absolute and in the host OS's native form**: `C:\Users\...\file.docx` on Windows, `/home/.../file.md` on POSIX. A repo-relative path (`projects/x/y.md`) identifies a file but cannot be clicked, so it forces the operator to ask "where is that?" — which is the friction this field exists to remove. When several files share a directory, give the directory once and the basenames after it. When a file sits outside the working directory, add a `file://` URL (percent-encode spaces: `file:///C%3A/Users/NAME%20SURNAME/...`) so it opens from any client on any platform. Never hand back a bare filename.

This IS 4D Disclose made concrete — the Impact Radius, post-write, every turn. Injector: `scripts/4d-reminder.py`; Stop-hook check: `scripts/source-attribution-check.py`.

### The cerebellum — precision without tremor

The WHILE is necessary but **not sufficient**: a pure feedback loop corrects *after* the miss — that is tremor (the "Parkinson" mode: undershoot or overshoot, wobble toward the target). To take exactly what you want, at speed, without dysmetria (skip OR excess), three properties must hold together — this is the cerebellum:

1. **Feedforward (a sharp predicted target).** The 4D Gate Manifest must enumerate the EXACT file-set you intend to touch — `+`/`~`/`-` per file — *before* acting. A vague "intent" makes the loop reactive tremor; a crisp enumerated target makes the first reach almost right.
2. **Binary feedback (set-equality, not vibes).** Reconcile `Touched` against `impact-radius.py <concept>` + the Manifest as **set equality**: radius/Manifest files not in Touched = SKIP; Touched files not predicted = over-reach. Not "I think I reconciled" — a binary comparison.
3. **Involuntary firing.** `scripts/impact-radius-hook.py` (PostToolUse `Write|Edit`) runs the radius the moment a `SKILL.md` is edited and surfaces the other references via `systemMessage` — so the scan can't be skipped by forgetting. A reflex, not a decision.

Why the WHILE alone doesn't close it: feedback-only is reactive, the exit condition is fuzzy if the target isn't enumerated, and it stays voluntary. The cerebellum supplies the missing three: predict the target (Manifest), compare binary (Touched==set), fire involuntarily (the hook). Octopus note: a real octopus has **no cerebellum** yet reaches with precision — it reduces degrees of freedom locally (bend-propagation, a temporary stiffened "joint"). Same lesson: precision comes from a sharp predicted target + local correction, not from raw force.

### Graph before grep — the seek IS the cerebellum's eye

The feedforward target (the Manifest) is only as good as how you find it. **A grep finds it by table scan; the graph finds it by seek.** A grep depends on the input string, so its coverage is stochastic and partial — it reconstructs a different, incomplete answer every query, is blind to off-repo and derived surfaces, and pulls ~100x the tokens of a seek (measured ~1737 vs ~16 for one concept). The graph **is** — `connectome/lineage.yaml` (a persistent, declared surface/derivation graph, merged at seek time with the gitignored `company/connectome/lineage.yaml` private layer for arm/CV surfaces). You traverse it; you don't rebuild it.

So the reflex: **before grep'ing the brain for where a concept lives, SEEK** — `impact-radius.py --file <path>` (or `"<concept>"`). It returns every impacted surface deterministically (in-repo + off-repo), each tagged with its corrective verb (`projects_to`→re-publish, `generated_by`→regenerate, `claim_maps_to`→add-file-row, `appears_in`→converge), and emits a one-line machine **receipt** to the per-turn ledger (`.cache/graph-ledger/`). The Provenance `Graph:` field quotes that receipt verbatim — never prose:
- `SEEK-COMPLETE` — ≥1 edge matched; the WHILE may exit in one beat.
- `GREP-FALLBACK(unlit:<x>)` — no edge yet (an *unlit neuron*); grep ran, a candidate was filed to `lineage.unverified.yaml`. This is a **PASS that grows the graph**, not a failure.

The 3D Diligent gate now also asks **"¿se usó el grafo?"** — a turn that grep'd brain surfaces and then WROTE files with no seek receipt is a coherence FAILURE (the graph is the octopus's blood; without it you pixelate). FinOps corollary: the seek is the same lookup at ~1% of the tokens and converges the WHILE in one beat instead of several — graph-use is both a coherence signal and a cost signal. *(Increment 1 ships the seek + receipt + advisory `grafo-ledger-check` Stop hook + reflex; the blocking teeth — a PreToolUse Bash gate on impact-shaped scans + a Stop `decision:block` + a fold of lineage into `neural_map.json` so `query_connectome` traverses it — are increment 2.)*

## 2D Delegate Gate — 3 Mandatory Questions (full detail)

**Trigger:** At the START of every task, before any file reads or code generation.

### Q1: ¿QUIÉN SABE? (Ventosas — Graph Search)

```bash
python3 ~/.claude/scripts/query_connectome.py query "<task description>"
```

- Builds a TF-IDF query vector and computes cosine similarity against stored document vectors for every agent and skill
- Returns ranked agents + their connected skills + graph community context
- Uses the IDF dictionary and top-200 TF-IDF vectors stored in `neural_map.json` (falls back to keyword matching if index is missing)
- Complements Q3 — together they cover both deep semantic similarity AND rule-based triggers

### Q2: ¿TIENE MCP/API? (Token-efficient access — runtime-aware)

Before any browser automation or scraping, run a **concrete MCP census** (not a mental check), then fall down the ladder:

| Priority | Access method | Token cost | When to use |
|---|---|---|---|
| 1 | **Registered MCP** | ~300 tokens/call | Already wired on this runtime — use it |
| 2 | **Register official MCP** | one-time setup | Official server exists but not connected yet ("no MCP connected" ≠ "no MCP available") |
| 3 | **REST API** | ~200 tokens/call | Structured JSON when no MCP path |
| 4 | **SDK / CLI** | ~500 tokens/call | Programmatic access, typed responses |
| 5 | **Scraping** | ~5,000+ tokens/call | Last resort — snapshots are token-expensive |

**Runtime-aware census (pick the active harness):**

| Runtime | Concrete check |
|---|---|
| Claude Code | `claude mcp list` (+ `claude mcp add …` to register) |
| Cursor (`CURSOR_AGENT=1`) | `GetMcpTools` / Settings → MCP (no `claude` CLI). Heartbeat also reads `.cursor/mcp.json` via `capability-census.py` |

**Check sequence:** census live MCPs → web-search `<service> MCP server` if none → REST docs → SDK/CLI → scrape only when exhausted. See `docs/architecture/multi-runtime.md`.

**If the task does not involve external data access** (pure code edit, file manipulation, git operations), answer: `Q2 API-first: N/A (no external data access)`

### Q3: ¿QUIÉN LO HACE? (Delegate-Check — Rule Match)

```bash
python3 ~/.claude/scripts/delegate-check "<task description in English>"
```

- Parses all agents from `REGISTRY.md` (triggers + cross-reference skills)
- Scans all skills (names + descriptions)
- Scores matches with weighted algorithm (trigger overlap + xref boost)
- Outputs: ACTIVATE / LOAD / SELF decision with recommended skills

### Combined Verdict

After all 3, follow the COMBINED recommendation:

- **ACTIVATE** → read the recommended agent file, load recommended skills, adopt persona
- **LOAD** → read the recommended skill files directly
- **SELF** → proceed with general knowledge (only if BOTH Q1 and Q3 return no strong match)

### Mandatory Output Format

```
2D Delegate: [domain classification]
  Q1 Ventosas:  [top agent] (score X) + [N skills via connectome]
  Q2 MCP/API:   [YES mcp-X / YES api.example.com / NO → scraping / N/A]
  Q3 Delegate:  ACTIVATE / LOAD / SELF — [reason]
```

### Exceptions (abbreviated 3Q OK)

- Trivial tasks (single grep, file read, quick answer)
- Follow-up actions within the same task (already delegated)
- User says "hazlo directo" or equivalent

### Anti-patterns

- **Delegate-only miss** — agent ran Q3 only, skipped Q1; missed pdf skill + document-code-review that ventosas would have surfaced.
- **Scraping-first waste** — agent went straight to agent-browser (60k tokens) when a REST API existed (~800 tokens). Q2 never ran.

## 4D Gate — Mandatory Pre-Flight

**No file shall be modified, created, or deleted without the human seeing the full manifest first.**

This is not a checklist — it is a **gate**. Like `terraform plan` before `terraform apply`.

### Gate Protocol

1. Run Impact Radius scan (grep all references to affected objects)
2. Assemble the **Change Manifest** — a single table listing EVERY file operation planned
3. Present the manifest to the user
4. **STOP. Wait for explicit confirmation.** Do not proceed without "sí", "yes", "dale", "ok", or equivalent
5. Only after confirmation: execute ALL changes, then run validation (3D Diligent)

### Manifest Format

```
## Change Manifest

| # | Action | File | Reason |
|---|--------|------|--------|
| 1 | MODIFY | output/generate_nda.py:32 | Update signature path |
| 2 | MODIFY | output/propuesta.md:175 | Downstream consumer of signature |
| 3 | DELETE | output/firma_old.svg | Orphaned artifact |
| 4 | DELETE | output/firma_old.png | Orphaned artifact |
| 5 | CREATE | output/NDA.pdf | Regenerated deliverable |

Impact: 2 files modified, 2 orphans deleted, 1 regenerated.
Confirm? (sí/no)
```

### Exceptions (gate NOT required)

- Read-only operations (grep, cat, ls, file reads, searches)
- Terminal commands that don't write to workspace files (queries, installs, diagnostics)
- When the user explicitly says "hazlo directo", "just do it", "sin confirmar", or equivalent

### Why a Gate, Not a Checklist

| Mechanism | Who enforces it | Fails when... |
|---|---|---|
| Checklist | Agent remembers | Agent forgets (proven failure mode) |
| Hook | Runs at boundary | Boundary not crossed (skippable) |
| **Gate** | **Blocks execution** | **Cannot fail — no manifest = no writes** |

The gate converts every write operation from **fire-and-forget** to **plan-approve-execute**. The human sees the blast radius before the blast.

## 3D Diligent Gate — Mandatory Post-Validation

**No task shall be declared complete without evidence that it works.**

### Gate Protocol

1. **Select validation method** from the matrix below
2. **Execute validation** — run the check, capture output
3. **Report result** with evidence
4. **If FAIL** — fix the issue, re-validate. Do NOT declare done with a known failure

### Validation Matrix

| Task Type | Validation Method | Evidence |
|---|---|---|
| Code edit | Build / lint / type-check | Command output, 0 errors |
| Script | Execute with test input | Output matches expected |
| PDF / doc | Open or render, verify visually | File size, page count, key content |
| SQL query | Check row count, nulls, schema | Result summary |
| Config change | Validate syntax (JSON/YAML parser) | Parse success |
| File delete | Verify no remaining references | `grep` returns 0 hits |
| Skill/doc edit | Read back, verify structure | Section headers, no broken refs |
| Any change | `get_errors` on modified files | 0 errors |
| **PR for production deploy** | **`pre-merge-qa-gate` skill — dispatch QA specialist agent against test/user-case spec** | **Agent ✅ verdict with concrete evidence (file:line, curl, screenshot). Build green alone is NOT enough — see the skill for why.** |

### Autonomous Loop Discipline (Stricter 3D)

When the work product is **autonomous brain code** — a process that runs without the operator present and writes to memory, skills, settings, or other shared brain state (digest crons, memory consolidators, skill candidacy promoters, outcome trackers, self-refactoring proposers) — the diligence bar rises. Five rules apply *in addition* to the matrix above:

1. **Una señal a la vez** — implement one signal MVP-first, expand only after it's validated end-to-end. Anti-pattern: build a 5-signal digest before any single signal has shipped useful findings.

2. **Propuestas, nunca commits** — the autonomous loop emits *proposals* (markdown / JSON draft / PR description), not direct writes. The operator gate is the validation. No autonomous mutation of brain memory, skills, or settings without operator approval. The 4D Gate stays sacred even when "I" am both author and reader.

3. **Cero LLM oculto en el cron** — every step inside the scheduled job must be deterministic and replayable. LLM calls live OUTSIDE the cron, inside the operator-driven review step. A hidden LLM call in a scheduled job means the loop is unauditable and the next operator who tries to debug it will hit an oracle they can't replay.

4. **Honesto con el log** — the loop proposes what its inputs actually show, not what "should" appear. If the session JSONLs contain zero tool rejections this week, the digest reports "0 rejections, nothing to propose" — it does not manufacture findings to look productive.

5. **Mide adopción** — track operator approval rate of past proposals. If <30% of proposals are approved over a 4-week window, the loop is mis-calibrated, not the operator distracted. Tune the signal threshold, narrow scope, or retire the loop. A loop nobody adopts is noise wearing a process costume.

**Why these live under 3D Diligent (and not as a separate D or a hook):**

These five are validation criteria for a *specific category* of write — code that alters future agent behavior. Standard Diligent says "validate every write with evidence"; this section says "when the write is autonomous-loop infrastructure, the evidence bar additionally includes operator-adoption metrics, determinism, and scope discipline." Same paradigm, sharper teeth.

A hook was the alternative — but hooks fire on events, and there is no event for "I'm about to design a learning loop." The discipline has to live where the agent looks when it is building such a loop — and that is the 3D protocol it reads to know what "done" means.

**When to apply this stricter Diligent:**
- Building any scheduled job that reads session data (`brain-digest-nightly`, similar)
- Adding a memory-write trigger (auto-consolidation, conflict detection, supersession protocols)
- Promoting a recurring one-off script to a skill candidate
- Any cron / hook that mutates `~/.claude/` without an operator in the loop
- Any agent that writes to `~/.claude/` based on its own pattern detection

### Mandatory Output Format

```
3D Diligent: [task type]
  Method:   [what was checked]
  Result:   PASS / FAIL
  Evidence: [1-line proof — file size, test output, error count]
```

**Anti-pattern:** Agent declares "Done!" on write instead of on verify — file actually has syntax error / broken import / failing test.

## Impact Radius (Disclose Amplification)

The 4th D is not just "tell the user what happens." It is: **where else does this object live, and who depends on it?**

Every object in a workspace — a file, a config value, an image, a path, a variable — has upstream producers and downstream consumers. Changing the object without tracing its radius leaves orphans, stale references, and silent defects.

### Mandatory Before ANY Modification

```
BEFORE CHANGING OBJECT X:
  1. WHERE is X referenced?     → grep -rn "X" across workspace + brain
  2. WHERE is X produced?       → find the source/generator of X
  3. WHO consumes X downstream? → deliverables, scripts, configs, other arms
  4. WHAT becomes orphaned?     → old files that new change makes obsolete
  5. DISCLOSE the full radius   → list all affected files before proceeding
```

### Scan Command

For BRAIN concepts (a skill, convention, primitive, term), use the tool — it is the manual grep automated, so it can't be silently skipped:

```bash
python3 ~/.claude/scripts/impact-radius.py "<concept>"     # every file referencing it
python3 ~/.claude/scripts/impact-radius.py --file <path>   # derive the term from a changed file
```

Then **reconcile the Provenance footer's `Touched` against the result** — files the radius lists that you did NOT touch = a SKIP; files you touched it does NOT imply = over-reach. The loop (the 4D WHILE) does not exit until they reconcile: **no skip, no excess.** This closes the #1 recurrent failure — codifying a concept in one place and leaving its references stale ("pixelation") — which is an intent↔effect precision gap, not malice.

For arbitrary shared files/images/paths, the raw grep still applies:

```bash
OBJECT="signature_file"
grep -rn "$OBJECT" . --include="*.py" --include="*.md" --include="*.sh" \
  --include="*.json" --include="*.yaml" --include="*.svg" --include="*.html"
```

### Hit Classification

| Hit type | Action required |
|---|---|
| Direct consumer (imports, references, embeds) | Update reference or replace file |
| Generator (script that creates the object) | Update generator logic |
| Documentation (mentions the object) | Update or flag for review |
| Orphaned artifact (old version, no longer referenced) | Delete or archive |

**Anti-pattern:** User asked to change a signature image. Agent updated the path in one script, but left 4 orphan files, a stale `.svg` reference in `proposal.md:175`, and a temp screenshot — because it never asked "WHERE ELSE does this object appear?"

**Rule:** No object is an island. Scan the radius first, disclose the full impact, apply changes to ALL affected files — not just the one the user pointed at.

## 4D Applied to the Octopus (Flow Tables)

| Flow | Describe | Delegate | Diligent | Disclose |
|---|---|---|---|---|
| **Arm work** | "I'll modify this client's ETL script" | Search arm's codebase first | Build/test within arm | "This changes the schedule from 15m to 5m" + Impact Radius scan |
| **Arm → Brain** | "This pattern is reusable" | Verify it's generic, anonymized | Check no client data leaks | "I'll create skill X — it applies to all PostgreSQL arms" |
| **Brain → Arms** | "New skill available" | Run `sync-ai-docs` | Verify each arm still builds | "This adds a new rule that affects all projects" |
| **Cross-arm (human only)** | Operator says "apply client-a pattern here" | Agent loads brain skill, not client-a code | Validate in target arm context | "Adapted from a generic skill, no source data carried" |
| **Object change** | "I'll replace this image/config/path" | Impact Radius: grep all references | Update ALL consumers, delete orphans | "Changed in N files, deleted M orphans, 0 stale refs remain" |

## 4D Applied to Database Queries

- **Describe**: "I'll run this query against the production database. It reads pg_stat_user_tables (read-only, no risk)."
- **Delegate**: For complex queries, verify schema first. Check `information_schema.columns` before referencing columns.
- **Diligent**: After query, validate results make sense. Flag if 0 rows returned unexpectedly.
- **Disclose**: "This DELETE will remove 1,247 rows. The table has no partition — VACUUM will be needed after."

## Known Anti-Patterns (Proven Agent Failures)

- **Iterative Bug-Fixing Drift** — agent creates a large file, then loops fix→test→fix; each micro-fix feels trivial so the gate is never re-engaged, but the aggregate is massive. **Fix:** the gate applies to the TOTAL planned change. For a 500+ line file, fire the gate ONCE for the whole file. If stuck in fix→test→fix, STOP after 3 iterations and re-present the manifest with cumulative changes.
- **"I already know how" Skip** — agent skips delegate-check because it has general knowledge; misses the matching agent + skills that carry lessons from past failures. **Fix:** delegate-check is NEVER optional. General knowledge ≠ project-specific best practices.
- **Delegate-only miss** — agent ran Q3 only, skipped Q1; missed pdf skill + document-code-review that ventosas would have surfaced.
- **Scraping-first waste** — agent went straight to agent-browser (60k tokens) when a REST API existed (~800 tokens). Q2 never ran.

## Enforcement Scripts (Mandatory)

| Script | When to Run |
|---|---|
| `~/.claude/scripts/query_connectome.py query "<task>"` | START of every task (2D Q1 — ventosas) |
| `~/.claude/scripts/delegate-check "<task>"` | START of every task (2D Q3 — rule match) |
| `~/.claude/scripts/gate-check` | BEFORE any file write (4D Gate). Flags: `--validate-session`, `--checklist`, `--audit-log` |

Q2 is a runtime-aware MCP census (Claude Code CLI or Cursor GetMcpTools / `.cursor/mcp.json`), not a mental check — evaluate before scraping.

## Lessons Learned

<!-- Append new anti-patterns as the protocol gets tested in real engagements. -->

# The 4D Paradigm

> **Organ:** nervous system — the signal protocol every action follows, from intent through execution to validated disclosure.

> The nervous-system protocol of Octorato. Every signal that crosses the brain ↔ arm ↔ agent ↔ human boundary follows four phases — **Describe → Delegate → Diligent → Disclose** — with three enforced gates layered in between. This page is the definitive reference.

The name is deliberate. A cube has three spatial dimensions; its four-dimensional analog is the tesseract. The 4D Paradigm is the tesseract of agent behavior — it adds a governing fourth axis (accountability) to the three you would otherwise expect (intent, execution, validation). See [[Architecture]] for where the paradigm sits in the larger octopus model, and [[Skills-System]] for how the enforcement skills load.

---

## 1. Why a paradigm at all

An autonomous agent that can read, write, and execute will, left ungoverned, do three things that cost you:

1. **Act silently** — make changes you never saw coming.
2. **Guess** — generate from training priors when the answer was one `grep` away.
3. **Declare victory early** — say "done" on the write, not on the proof.

The 4D Paradigm closes all three. It is not a style guide; it is a control loop with hard stops. Two of the four phases fire **before** the agent acts, two fire **after**, and a blocking gate sits in the middle that converts every write from *fire-and-forget* into *plan → approve → execute*.

```
ENTRADA (before acting)
  1D DESCRIBE  → "I will do X because Y"      (intent, scope, files)
  2D DELEGATE  → who knows? has API? who does it?  (search before generating)
        │
  ┌─────▼─────┐
  │ 4D GATE   │ ← STOP. Change Manifest. Confirm. No writes without approval.
  └─────┬─────┘
        ▼ confirmed → EXECUTE
SALIDA (after acting)
  3D DILIGENT  → PASS/FAIL with evidence       (build / lint / test / render)
  4D DISCLOSE  → impact radius, side effects, orphans
```

**Invariant:** the agent must visibly report all four phases. A response missing any phase is incomplete, not merely terse.

---

## 2. The four phases

### 2.1 — 1D Describe (fires before action)

State **what** you will do and **why**, in one to three sentences, before touching anything. No silent changes — ever.

A good Describe names the task type, the scope, and the blast surface in a single breath:

> "I'll add a `HospitalId` index to fix the sequential scan on the appointments query. This is a read-only schema addition — no data migration, one file touched."

Describe is cheap and it is the agent's first contract with the operator. It is also the seed of the spec: at LARGE complexity (see §6) the Describe phase grows into a full `feature.md` with acceptance criteria and edge cases.

**Anti-pattern:** beginning to edit files and *then* narrating what you did. Describe is a pre-condition, not a caption.

### 2.2 — 2D Delegate (fires before action)

Search, verify, and route **before** you generate. The agent's training knowledge is a prior, not a source. Delegate answers: *is there an agent, a skill, an API, or a past lesson that already solves this better than my general knowledge?*

Delegate is enforced by a three-question gate, detailed in full in §4. In short:

- **Q1 — ¿Quién sabe?** Query the connectome (TF-IDF graph over every skill and agent).
- **Q2 — ¿Tiene API?** Prefer structured access over scraping.
- **Q3 — ¿Quién lo hace?** Run the rule-based delegate-check for the ACTIVATE / LOAD / SELF verdict.

For genuinely complex research, Delegate also means *dispatch a subagent* rather than spelunking inline.

**Anti-pattern — "I already know how":** skipping delegate-check because the task feels familiar. General knowledge ≠ project-specific best practice. The matching skill often carries a hard-won lesson from a past failure that your priors do not.

### 2.3 — 3D Diligent (fires after action)

No task is **done** until there is evidence it works. Diligent selects a validation method by task type, executes it, and reports PASS or FAIL with one line of proof. On FAIL, the agent fixes and re-validates — it does not declare done with a known defect. Full validation matrix in §5.

**Anti-pattern:** declaring "Done!" the moment the file is written, while it actually carries a syntax error, a broken import, or a failing test. The write is the easy part; the proof is the work.

### 2.4 — 4D Disclose (fires after action)

The fourth dimension is the one most agents lack. Disclose is not merely "tell the user what happened" — it is **"where else does this object live, and who depends on it?"** Every file, config value, image, path, or variable has upstream producers and downstream consumers. Changing it without tracing that radius leaves orphans, stale references, and silent defects.

Disclose has two outputs:

1. **Side effects** — "This changes the cron schedule from 15m to 5m," "This DELETE removes 1,247 rows; the table has no partition, so VACUUM follows."
2. **Impact Radius** — the full list of every file the change touched, every orphan it created, and confirmation that zero stale references remain.

The Impact Radius scan is a `grep` run *before* the change and reconciled *after* it. See §7.

---

## 3. The 4D Gate — pre-write Change Manifest

> **No file shall be modified, created, or deleted without the human seeing the full manifest first.**

This is the single most load-bearing rule in the paradigm. It is the agent's `terraform plan` before `terraform apply`: you see the entire blast radius before the blast.

It is deliberately a **gate**, not a checklist or a hook, because of how each fails:

| Mechanism | Who enforces it | Fails when… |
|---|---|---|
| Checklist | Agent remembers | Agent forgets (a proven failure mode) |
| Hook | Runs at a boundary | The boundary is never crossed (skippable) |
| **Gate** | **Blocks execution** | **Cannot fail — no manifest, no writes** |

### Gate protocol

1. Run the **Impact Radius scan** (`grep` every reference to the affected objects).
2. Assemble the **Change Manifest** — a single table listing *every* file operation planned.
3. Present the manifest to the operator.
4. **STOP.** Wait for explicit confirmation — "sí", "yes", "dale", "ok", or equivalent.
5. Only after confirmation: execute *all* changes, then run 3D Diligent.

### Manifest format

```
## Change Manifest

| # | Action | File | Reason |
|---|--------|------|--------|
| 1 | MODIFY | output/generate_nda.py:32 | Update signature path |
| 2 | MODIFY | output/propuesta.md:175    | Downstream consumer of signature |
| 3 | DELETE | output/firma_old.svg       | Orphaned artifact |
| 4 | DELETE | output/firma_old.png       | Orphaned artifact |
| 5 | CREATE | output/NDA.pdf             | Regenerated deliverable |

Impact: 2 files modified, 2 orphans deleted, 1 regenerated.
Confirm? (sí/no)
```

The manifest forces three disciplines at once: the scope is visible, the orphans are named (not silently left behind), and the operator owns the go/no-go decision.

### When the gate is required vs exempt

| Required | Exempt |
|---|---|
| Any file MODIFY / CREATE / DELETE in the workspace | Read-only operations: `grep`, `cat`, `ls`, file reads, searches |
| The first write in a response (covers all writes that follow it) | Terminal commands that don't write workspace files: queries, installs, diagnostics |
| Regenerating a deliverable, deleting orphans, replacing an asset | The operator says "hazlo directo", "just do it", "sin confirmar", or equivalent |

### The aggregate-change trap

The gate applies to the **total planned change**, not each keystroke. A common drift: an agent creates a 500-line file, then loops fix → test → fix; each micro-fix feels trivial so the gate is never re-engaged, but the aggregate is enormous. **Rule:** fire the gate *once* for the whole file. If you are stuck in a fix → test → fix loop, STOP after three iterations and re-present the manifest with the cumulative changes.

---

## 4. The 2D Delegate Gate — three mandatory questions

Run at the START of every non-trivial task, before any file read or code generation, in this order.

### Q1 — ¿Quién sabe? (Ventosas / graph search)

```bash
python3 ~/.claude/scripts/query_connectome.py query "<task description>"
```

Builds a TF-IDF query vector and computes cosine similarity against the stored vectors for every agent and skill in `neural_map.json`. Returns ranked agents, their connected skills, and graph-community context. Falls back to keyword matching if the index is missing. This is the *semantic* half of routing — it surfaces skills you didn't know to ask for.

### Q2 — ¿Tiene MCP/API? (token-efficient access)

Not a mental check: **run `claude mcp list`** before any browser automation or scraping, then walk the access hierarchy from cheapest to most expensive:

| Priority | Access method | ~Token cost | When to use |
|---|---|---|---|
| 1 | **Registered MCP server** | ~300 / call | Already connected (GitHub, Gmail, Notion, …) |
| 2 | **Register a NEW official MCP** | ~300 / call | `claude mcp add --transport http <name> <url>` when an official server exists for the service |
| 3 | **REST API** | ~200 / call | Structured JSON when no MCP exists |
| 4 | **SDK / CLI** | ~500 / call | Programmatic, typed responses |
| 5 | **Scraping** | ~5,000+ / call | Last resort, snapshots are token-expensive |

**"No MCP connected" is not "no MCP available".** Before dropping to scraping or a hand-rolled REST client, verify whether an official MCP server exists for the service (web-search "<service> MCP server") and register it. Skipping that check is a hard failure, not a shortcut.

If the task touches no external data (pure code edit, file manipulation, git ops), the answer is simply: `Q2 MCP/API-first: N/A (no external data access)`.

### Q3 — ¿Quién lo hace? (delegate-check / rule match)

```bash
python3 ~/.claude/scripts/delegate-check "<task description in English>"
```

Parses every agent from `REGISTRY.md` (triggers + cross-referenced skills), scans all skill names and descriptions, scores matches with a weighted algorithm (trigger overlap + xref boost), and emits the verdict. This is the *rule-based* half — it complements Q1's semantic match so you catch both deep similarity and explicit triggers.

### The combined verdict

| Verdict | Meaning | Action |
|---|---|---|
| **ACTIVATE** | A specialist persona matches | Read the agent file, load its recommended skills, adopt the persona |
| **LOAD** | Skills match but no persona | Read the recommended skill files directly |
| **SELF** | No strong match | Proceed on general knowledge — *only* when **both** Q1 and Q3 return no strong match |

### Mandatory output format

```
2D Delegate: [domain classification]
  Q1 Ventosas:  [top agent] (score X) + [N skills via connectome]
  Q2 MCP/API:   [MCP <name> / register MCP / REST api.example.com / NO → scraping / N/A]
  Q3 Delegate:  ACTIVATE / LOAD / SELF — [reason]
```

### Exemptions (abbreviated 3Q is acceptable)

- Trivial tasks (single `grep`, a file read, a quick factual answer).
- Follow-up actions inside a task that already ran the gate.
- The operator says "hazlo directo" or equivalent.

### Delegate anti-patterns

- **Delegate-only miss** — ran Q3 only, skipped Q1; missed the `pdf` skill and `document-code-review` that the connectome would have surfaced. Run both halves.
- **Scraping-first waste** — went straight to a browser snapshot (~60k tokens) when a REST API existed (~800 tokens). Q2 never ran.

---

## 5. The 3D Diligent Gate — no "done" without evidence

> **No task shall be declared complete without evidence that it works.**

### Gate protocol

1. **Select** a validation method from the matrix below by task type.
2. **Execute** the check and capture output.
3. **Report** PASS or FAIL with one line of evidence.
4. **On FAIL** — fix, then re-validate. Never declare done with a known failure.

### Validation matrix

| Task type | Validation method | Evidence |
|---|---|---|
| Code edit | Build / lint / type-check | Command output, 0 errors |
| Script | Execute with test input | Output matches expected |
| PDF / doc | Open or render, verify visually | File size, page count, key content |
| SQL query | Check row count, nulls, schema | Result summary |
| Config change | Validate syntax (JSON/YAML parser) | Parse success |
| File delete | Verify no remaining references | `grep` returns 0 hits |
| Skill / doc edit | Read back, verify structure | Section headers present, no broken refs |
| Any change | Error-check the modified files | 0 errors |
| **PR for production deploy** | Dispatch a QA specialist agent against a test/user-case spec (`pre-merge-qa-gate`) | Agent ✅ verdict with concrete evidence — file:line, curl, screenshot. **Build-green alone is not enough.** |

### Mandatory output format

```
3D Diligent: [task type]
  Method:   [what was checked]
  Result:   PASS / FAIL
  Evidence: [1-line proof — file size, test output, error count]
```

**Anti-pattern:** "Done!" reported on the write rather than on the verify, while the file carries a syntax error or a failing test.

---

## 6. 4D+S — Spec-Driven Development integration

The 4D Paradigm scales its ceremony to the size of the task. Trivial fixes get the four phases and nothing more; large features pull in full Spec-Driven Development (SDD). The `4d-spec` orchestrator skill runs a complexity classifier at the start of any implementation task and routes to the right depth.

### Complexity classifier

Score the task against these signals and sum the points:

| Signal | Points |
|---|---|
| Touches 1–3 files | 0 |
| Touches 4–10 files | +2 |
| Touches 10+ files | +4 |
| New feature (not a fix) | +2 |
| Architectural decision required | +3 |
| Multiple modules / services affected | +2 |
| Operator explicitly requests a spec | +5 |
| Database schema changes | +1 |
| New API endpoints | +1 |

### Score → workflow

| Score | Level | What activates |
|---|---|---|
| 0–2 | **TRIVIAL** | 4D only — Describe → Gate → Execute → Diligent → Disclose |
| 3–5 | **MEDIUM** | 4D + `plan.md` (a numbered task checklist before the Gate) |
| 6+ | **LARGE** | 4D + full SDD — `feature.md` + `plan.md` + `review.md` + archive |

### How SDD enhances each phase

| 4D phase | SDD enhancement | Activates at |
|---|---|---|
| 1D Describe | Becomes `feature.md` with acceptance criteria + edge cases | LARGE only |
| 2D Delegate | No change — delegate-check still runs | Always |
| 4D Gate | Manifest now *includes* the `plan.md` task list | MEDIUM+ |
| 3D Diligent | Adds an 8-dimension review against the spec | LARGE only |
| 4D Disclose | Adds an archive step for institutional memory | LARGE only |

### The LARGE pipeline (score 6+)

```
1D Describe + Spec  → /sdd-feature  → feature.md   (refine via /sdd-refine)
2D Delegate         → delegate-check (loads agents + skills)
2S Plan             → /sdd-plan     → plan.md (max 20 tasks)
4D Gate             → Change Manifest + spec summary + plan summary
Execute             → /sdd-implement (verifies each layer)
3D Diligent + Review→ /sdd-review   (8-dimension review against spec)
4D Disclose         → impact radius + review verdict
Archive             → /sdd-archive  → docs/specs-archive/
```

### Solo-operator adaptations

- **Max 20 tasks** in any `plan.md` — consolidate if SDD generates more.
- `feature.md` and `plan.md` live in the working directory during the task and are cleaned up after (git tracks the actual changes).
- `review.md` is optional for MEDIUM, mandatory for LARGE.
- `/sdd-yolo` maps to the "hazlo directo" exception — the full pipeline behind a single gate.

> **Brain hygiene:** SDD artifacts (`feature*.md`, `plan*.md`, `spec*.md`) must **never** sit at the brain root. They leak roadmap and source context even with zero client data. They belong in `docs/specs-archive/`, `templates/`, or arm-side. The `check-generic.py` enforcement rejects root-level SDD files. See [[Architecture]] for the generic-brain contract.

### 4D+S output format

```
4D+S Classification: [TRIVIAL/MEDIUM/LARGE] (score: N)
  Signals:    [matched signals]
  Workflow:   [which phases activate]
  SDD skills: [which /sdd-* commands will be used, or "none"]
```

---

## 7. Impact Radius — the scan behind Disclose

No object is an island. Before modifying any shared file, image, config, or path, trace its full radius.

### Mandatory pre-modification scan

```
BEFORE CHANGING OBJECT X:
  1. WHERE is X referenced?     → grep -rn "X" across workspace + brain
  2. WHERE is X produced?       → find the source/generator of X
  3. WHO consumes X downstream? → deliverables, scripts, configs
  4. WHAT becomes orphaned?     → old files this change makes obsolete
  5. DISCLOSE the full radius   → list every affected file before proceeding
```

### Scan command

```bash
OBJECT="signature_file"
grep -rn "$OBJECT" . --include="*.py" --include="*.md" --include="*.sh" \
  --include="*.json" --include="*.yaml" --include="*.svg" --include="*.html"
```

### Classifying the hits

| Hit type | Action required |
|---|---|
| Direct consumer (imports, references, embeds) | Update the reference or replace the file |
| Generator (script that creates the object) | Update the generator logic |
| Documentation (mentions the object) | Update or flag for review |
| Orphaned artifact (old version, unreferenced) | Delete or archive |

**Anti-pattern:** asked to swap a signature image, the agent updated the path in one script but left four orphan files and a stale `.svg` reference in `proposal.md:175` — because it never asked "where else does this object appear?" Every one of those becomes a silent defect.

---

## 8. Enforcement scripts

The paradigm is not aspirational; three scripts enforce it at the boundaries.

| Script | Phase | When to run |
|---|---|---|
| `~/.claude/scripts/connectome-heartbeat.py` | 2D · Q1 (ventosas) — **autonomic** | Fires on every prompt via hook; injects the `♥` block (relevant agents/skills + 1-hop impact) automatically — no manual call needed |
| `~/.claude/scripts/query_connectome.py query "<task>"` | 2D · Q1 (ventosas) — deeper traversal | Run manually only when you need god-node analysis, full impact radius, or shortest-path beyond what the heartbeat surfaced |
| `~/.claude/scripts/delegate-check "<task>"` | 2D · Q3 (rule match) | START of every task |
| `~/.claude/scripts/gate-check` | 4D Gate | BEFORE any file write — flags: `--validate-session`, `--checklist`, `--audit-log` |

Q2 (MCP/API-first) has no dedicated brain script, but it is not a mental check either: you run `claude mcp list` before scraping, and register an official MCP server if one exists. The 3D Diligent validation is method-specific (build, lint, render, query), so it is driven by the matrix in §5 rather than a single binary.

---

## 9. Quick reference

| You are about to… | Phase / gate | Do this |
|---|---|---|
| Start any task | 1D + 2D | Describe in 1–3 sentences, then run the 3-question Delegate gate |
| Reach for a browser/scraper | 2D · Q2 | Run `claude mcp list`; registered MCP → register official MCP → REST → SDK first |
| Write, create, or delete a file | 4D Gate | Present the Change Manifest, wait for confirmation |
| Change a shared object | Impact Radius | `grep` the radius before editing; update all consumers |
| Say "done" | 3D Diligent | Validate by task type, report PASS/FAIL + evidence |
| Finish | 4D Disclose | State side effects + the full impact radius |
| Implement a feature | 4D+S | Classify complexity; pull in `plan.md` / full SDD as the score dictates |

---

## See also

- [[Architecture]] — where the paradigm sits in the octopus model (Brain → Agent → Skills → Arm) and the generic-brain contract.
- [[Skills-System]] — how `4d-paradigm-protocol`, `4d-spec`, and the enforcement skills load on demand.

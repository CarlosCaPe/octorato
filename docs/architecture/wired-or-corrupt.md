# Wired-or-Corrupt Architecture (SHIPPED)

Status: SHIPPED. All phases landed: Phase 0 (registry + doctor + pre-push gate, v4.0.0), the create-to-register loop (v4.2.0), the fail-closed meta-gate with the gateable classification (#180, v5.3.0), the operator-signed waivers that armed its teeth (v5.4.0), and the v5.5.0 hardening wave: waiver `expires` enforcement (an expired waiver counts as unwaived, so the rule FAILS again), bidirectional release-drift detection, anchor-ambiguity detection, a corpus-coverage denominator that counts skills canon plus memory directives, and fail-closed pre-push gate inputs (a missing rules.yaml, doctor, or Python blocks the push instead of silently skipping). The later wave closed corpus-coverage to an honest 100% and armed its teeth: the ledger now FLIPS from WARN to FAIL on any uncovered rule, so a new un-wired rule blocks the push, and it prints enforcement strength per row (REFLEX/PRESENCE) so coverage is never misread as force.
Produced 2026-06-22 by workflow wf_c77aedc2-7d6 (11 agents: 5 architect lenses + judge panel + synthesis), seeded from a primary-source audit of ~/.claude this session.

---

# Octorato Wired-or-Corrupt Architecture - Decision-Ready Synthesis

Synthesized from 5 proposals + panel. Verdict pattern: all five converge on HYBRID (declarative manifest as truth, OO hydrated for polymorphic `assert_wired()`), all five flagged the same two soft spots (MECE asserted-not-proven; fires-vs-obeyed honesty). This synthesis takes the doctor/ontology Rule #1 fidelity (9/9), the skeptic's three-tier liveness honesty, the declarative split principle, and fixes every panel-named gap below.

Single source of truth: **`registry/rules.yaml`** (tracked) + **`registry/rules.schema.json`** (validated like `skill.json` already is). OO objects are generated at doctor-time, never hand-authored.

---

## 1. RULE #1 - final wording (paste verbatim, FIRST rule, every brain's CLAUDE.md)

```markdown
## RULE #1 - Wired or Corrupt (constitutional, keystone; do not edit without editing brain_doctor)

Every rule in this brain MUST be wired. A rule is WIRED only when `registry/rules.yaml`
holds an entry for it carrying {id, category, firing_mode, canonical_name, mechanism, proof}
and that entry's backing mechanism is verifiably live. A rule that exists as prose with no
registered, live mechanism is not a rule. It is rot, and a brain that carries it is CORRUPT.

`brain_doctor` is the mechanism of THIS rule. It loads the Registry, calls `assert_wired()`
on every rule, reconciles every CLAUDE.md rule-anchor against the Registry (no orphan prose),
and reconciles every live hook in hooks.json against the Registry (no orphan mechanism). If a
single rule fails `assert_wired()`, or a single anchor has no rule, or a single live mechanism
is unclaimed, the doctor declares the brain CORRUPT, exits non-zero, and the pre-push hook
BLOCKS the push. No --force, no exception, no soft-fail.

"Wired" means COVERED, not mechanically forced. A model-behavior rule (no-hallucination,
connector-not-human, tone, register) is wired by a registered Detector or a brain_doctor
presence-assert, never by bare prose. 100% wired = 100% COVERAGE of the rule corpus, which is
achievable; it is NOT a claim of 100% behavioral enforcement, which is not. The Coverage Ledger
prints enforcement strength per rule so presence-only is never misread as forced.

This rule is self-wired and that is why it closes: Rule #1's own backing mechanism is
brain_doctor (Registry id R-META-001), and brain_doctor's invocation from the tracked
`.githooks/pre-push` is itself Registry id R-META-002. The doctor's FIRST action proves its
own gate is installed (core.hooksPath, pre-push present, contains the doctor call, rules.yaml
loads) before judging any other rule. "Documented but not wired" is therefore an impossible,
doctor-detected state. Period.
```

---

## 2. THE LABEL ONTOLOGY - MECE controlled vocabulary + naming

Three axes carried on every rule and every script. Panel's hardest hit: MECE was *asserted* across all five. Fixed here with (a) an explicit precedence tie-breaker for categories, (b) `{event, matcher}` modeled as two fields (not one fused value - closes the ontology lens PreToolUse-split error), (c) multi-mode rows allowed as a list (closes the doctor lens cadence-lint/trace-hook overlap).

**AXIS 1 - `category` (WHAT domain). 9 values, single-valued by a PRECEDENCE rule (not by decree):**

```
IDENTITY  ARCHITECTURE  GENERIC  CODE  SECURITY  COMMS  GIT  FLOW  MEMORY
```

Precedence for a rule that straddles families (highest wins, deterministic, doctor-checkable):
`SECURITY > GENERIC > IDENTITY > ARCHITECTURE > FLOW > MEMORY > CODE > COMMS > GIT`.
Worked tie-breaks: never-commit-secrets = SECURITY (beats GENERIC); no-arm-identifiers = GENERIC (beats ARCHITECTURE); adversarially-verify-operator = CODE; graph-before-grep = FLOW. The schema enum is the gate; adding a category requires a schema PR the operator reviews.

**AXIS 2 - `firing_mode` (HOW it activates). 6 values, MECE. A row may carry a LIST (cadence-lint is `[hook, cli]`):**

```
hook  runner  cli  cron  library  observability
```

Sub-fields when `hook`: `firing_event ∈ {UserPromptSubmit, PreToolUse, PostToolUse, Stop, SessionStart}` and `firing_matcher ∈ {Write|Edit, Bash, *}`. Event and matcher are SEPARATE fields. `PrePush` is NOT a Claude Code event; the push gate is a git-hook, modeled as `firing_mode: git-hook` (distinct from `hook`) - closes the doctor-lens conflation.

**AXIS 3 - `strength` (HOW HARD; == Mechanism subclass, 1:1, ordered):**

```
GATE > REFLEX > DETECTOR > PRESENCE
```

Bidirectional bound (the skeptic's sharp insight, adopted): strength may NOT exceed true enforceability (you cannot GATE "good tone") AND may NOT understate it (a SECURITY rule at PRESENCE is itself CORRUPT). Schema forbids `category ∈ {SECURITY, GENERIC, ARCHITECTURE}` from `strength: PRESENCE`.

**CANONICAL NAME = projection of the labels (taxonomy and nomenclature are ONE):**

```
<strength-prefix>__<event-or-mode>__<slug>.py
prefix:  g=GATE  r=REFLEX  d=DETECTOR  m=PRESENCE  run=runner  cli=cli  cron=cron  lib=library  obs=observability
event:   prompt | pretool-write | pretool-bash | posttool | stop | session | prepush   (or the mode word for non-hooks)
slug:    kebab, the role, NO redundant -hook/-gate/-check suffix
```

A name decodes deterministically to `{strength, event/mode}`. brain_doctor reparses the filename and asserts `(parsed strength, parsed event) == declared`; mismatch = CORRUPT. This locks nomenclature to taxonomy forever.

**Worked example (one record = label + naming contract + proof):**

```yaml
- id: COMMS.human-cadence
  title: "Human Cadence - 10 anti-AI-tell rules"
  category: COMMS
  source: { file: CLAUDE.md, anchor: "ULTRA RULE - Human Cadence" }   # explicit anchor id
  strength: GATE                         # => Gate subclass
  firing_mode: [hook]
  mechanism:
    - kind: Gate
      canonical_name: g__stop__cadence.py
      firing_event: Stop
      firing_matcher: "*"
    - kind: Detector                     # companion, a REAL mechanism entry (not a side dict)
      canonical_name: d__posttool__cadence.py
      firing_event: PostToolUse
  proof:
    - { method: IN_HOOKS_JSON, locator: "Stop[*]:g__stop__cadence.py", expect: present }
    - { method: EXIT_CODE,     locator: "g__stop__cadence.py --selftest", expect: 0 }
  liveness_required: FIRES                # PRESENT | FIRES | EFFECTIVE
```

Note `mechanism` is a LIST of typed entries (closes the OO-lens companion-as-untyped-dict gap; the companion is a first-class Mechanism under the same type guard).

---

## 3. THE REGISTRY - pick: HYBRID (declarative-primary, OO hydrated at doctor-time)

**Decision: HYBRID. Justification (forced by ground truth, not aesthetic):**
- Pure-OO fails: the brain runs on N machines; wiring must be git-diffable and identical per machine. Rules-in-`.py` bury the source of truth and re-create the same prose/code drift one layer up.
- Pure-declarative fails: `assert_wired()` is genuinely polymorphic (a Gate proves liveness differently than a PRESENCE), and you want a TYPE error, not a YAML type-switch ladder, when a rule has no mechanism.
- Hybrid takes both, and there is an in-tree precedent: `validate-skill-manifest.py` already validates `skill.json` against a schema (verified present). We generalize that from skill.json to the constitution.

The manifest is the genome; the classes are the proteins it expresses. The manifest is the ONLY hand-edited artifact. `hooks.json` and machine-local `settings.json` are demoted to *generated projections* of the manifest (this is what makes "wired" propagate across machines and kills defect F1).

**Schema (text):**

```
Rule:
  id            : str   /^[A-Z]+\.[a-z0-9-]+$/        # CATEGORY.slug, stable, MECE
  title         : str
  category      : enum  (the 9, schema-gated)
  source        : { file, anchor }                    # explicit anchor id in CLAUDE.md
  strength      : enum  {GATE,REFLEX,DETECTOR,PRESENCE}
  firing_mode   : list[enum{hook,git-hook,runner,cli,cron,library,observability}]
  mechanism     : list[Mechanism]   # >=1, REQUIRED, non-empty (schema rejects empty)
  proof         : list[Proof]
  liveness_required : enum {PRESENT,FIRES,EFFECTIVE}
  waiver        : Waiver | null     # operator-signed, expiry-dated, agent-proof

Mechanism (discriminated union on .kind):
  kind          : enum {Gate,Reflex,Detector,Presence}
  canonical_name: str | null        # null ONLY when kind==Presence
  firing_event  : enum | null
  firing_matcher: str  | null

Proof:
  method        : enum {IN_HOOKS_JSON, FILE_EXISTS, EXIT_CODE, ANCHOR_PRESENT, FIRED_IN_TRACE, PROBE}
  locator       : str
  expect        : str|int|present
```

**OO layer (hydrated read-only at doctor-time, never the persistence format):**

```
abstract Mechanism
  + is_present() -> bool          # file/entry exists
  + fires_at()   -> Event|None
  + verify(level) -> Verdict      # polymorphic
  Gate     : present + in hooks.json at event/matcher + EXIT_CODE --selftest==nonzero (+PROBE if EFFECTIVE)
  Reflex   : present + in hooks.json + selftest emits a non-empty inject   (EFFECTIVE unreachable, capped honestly)
  Detector : present + py_compile + declares >=1 assertion (or CLI exit-code on a fixture)
  Presence : canonical_name may be null; is_present = ANCHOR_PRESENT in CLAUDE.md
             AND (companion Detector is None OR companion.is_present);  NEVER returns "no mechanism"

class Rule
  + mechanism : list[Mechanism]   # __post_init__ raises TypeError on empty list (un-backed prose = CORRUPT)
  + assert_wired() -> Verdict     # all(m.verify(liveness_required)) + all(proof.check())

class Registry
  + load(rules.yaml) -> validate(schema) -> [Rule]
  + iter()      # iterating == the Coverage Ledger
  + assert_complete()   # every CLAUDE.md anchor -> >=1 Rule, and reverse
  + orphans()           # live hooks in hooks.json claimed by no Rule
```

`Rule.__post_init__` raising on an empty mechanism list is the type-system fact that makes "un-backed prose is CORRUPT" a constructor error, surfaced at hydrate time with the offending id.

---

## 4. brain_doctor ENFORCEMENT - per-rule, fail-closed, push-blocking + drift + multi-machine

Replaces today's 15 ad-hoc asserts (verified: 15, none per-rule) with ONE Registry loop + structural reconciliations.

```
def assert_registry_complete(repo):

  # D0 BOOTSTRAP SELF-CHECK (Rule #1's own wiring, FIRST, fail-closed)
  assert core.hooksPath == ".githooks"
  assert ".githooks/pre-push" exists and contains sentinel "# OCTORATO-WIRE-GATE" + brain_doctor call
  assert rules.yaml loads            # any fail -> CORRUPT immediately, before judging anyone

  # D1 SCHEMA            -> validate rules.yaml vs rules.schema.json (reuse validate-skill-manifest engine)
  #                         Presence-with-null-mechanism / SECURITY-at-PRESENCE rejected HERE, exit 2 (MALFORMED)

  reg = Registry.load("registry/rules.yaml")    # __post_init__ TypeError on empty mechanism -> CORRUPT(id)

  # D2 NO-ORPHAN-PROSE (bidirectional, per-rule-ANCHOR not per-heading)
  for anchor in parse_claude_md_anchors():       # every ## AND every "ULTRA RULE" line, by explicit anchor id
      assert anchor in reg.anchors               # prose with no rule = CORRUPT
  for rule in reg:
      assert rule.source.anchor exists in CLAUDE.md   # dead rule row = CORRUPT

  # D3 PER-RULE assert_wired() (the heart, polymorphic - the thing missing today)
  for rule in reg:
      v = rule.assert_wired()                    # dispatches by Mechanism subclass
      # Gate/Reflex: FILE_EXISTS + IN_HOOKS_JSON(event,matcher) + EXIT_CODE selftest
      # Detector:    FILE_EXISTS + runnable + >=1 assertion
      # Presence:    ANCHOR_PRESENT + companion-detector-live
      # name reparse: parsed(strength,event) == declared  else CORRUPT
      ledger.add(v)

  # D4 ORPHAN-MECHANISM   -> every hook in hooks.json claimed by exactly one rule.canonical_name else CORRUPT
  # D5 DRIFT              -> settings.json(local) header sha == sha256(hooks.json); hooks.json == gen_from(rules.yaml)
  # D6 LIVENESS (honest %) -> proof FIRED_IN_TRACE over .brain/trace.jsonl last N=20 sessions
  #                          required=FIRES but observed=PRESENT-only -> STALE: WARN (CORRUPT only if rule.strict)

  print(ledger.table())                          # id|category|strength|liveness_req|liveness_obs|verdict
  if ledger.any(CORRUPT): exit(1)
  exit(0)
```

**How each ground-truth defect dies:**
- **F3 phantom** (brain-memory-recall.py - verified ABSENT): D3 FILE_EXISTS fails on first run. Impossible to ship.
- **F1 drift**: D5 + demoting settings.json/hooks.json to projections of the one tracked manifest.
- **F4 no per-rule assert**: D3 IS the per-rule loop; coverage is computed, not hand-asserted.
- **F2 widening gap**: D2 bidirectional - a new prose anchor with no rule blocks push.

**`--fix`**: idempotent only - regenerate hooks.json/settings.json from the manifest, rename a drifted script to canonical, scaffold a Presence detector stub. It NEVER invents a Gate's logic or downgrades a rule to silence it (that would defeat Rule #1).

**Drift + multi-machine:** `hooks.json` is the tracked source; `settings.json` is a gitignored projection regenerated by `merge-hooks.py` at SessionStart and by `ai-pull`. `rules.yaml` + `rules.schema.json` + `hooks.json` travel in git via `ai-sync`/`ai-pull` (which already ends with brain_doctor). `install-runners.py` sets `core.hooksPath=.githooks` and runs `brain_doctor --fix` on a fresh clone. Wiring is a property of the tracked manifest, identical on every machine by construction. Server-side branch protection on master (master is PR-protected) is the backstop for a laptop that pushes a feature branch before ever running ai-pull (closes the OO-lens unguarded-window risk).

---

## 5. THE RENAMING MAP - rule + concrete examples

**RULE:** every backing script → `<strength-prefix>__<event-or-mode>__<slug>.py`, kebab slug, double-underscore separators, the redundant `-hook/-gate/-check/-stop/-reminder` suffix DROPPED (prefix already carries strength, event segment carries when). snake_case abolished for scripts; library internal module names may keep a snake import alias but the FILE is renamed. The rename map IS `registry/rules.yaml` (each row carries `old_name` during transition); a codemod generated FROM the manifest rewrites hooks.json + settings.json + references via `impact-radius.py` (graph before grep), gated on D4 orphan-reconcile == 0, then `old_name` is deleted so the soup cannot resurrect.

| before | after | decode |
|---|---|---|
| `cadence-stop-hook.py` | `g__stop__cadence.py` | GATE, Stop |
| `cadence-lint.py` | `d__posttool__cadence.py` (+ `cli` alias) | DETECTOR, PostToolUse |
| `qa-merge-gate.py` | `g__pretool-bash__qa-merge.py` | GATE, PreToolUse[Bash] |
| `dimension-awareness-hook.py` | `g__pretool-write__dimension-awareness.py` | GATE, PreToolUse[Write] |
| `secrets-grep-guard.py` | `g__pretool-bash__secrets-grep.py` | GATE, PreToolUse[Bash] |
| `check-generic.py` | `g__prepush__generic-leak.py` | GATE (git-hook), push |
| `connectome-heartbeat.py` | `r__prompt__connectome-heartbeat.py` | REFLEX, UserPromptSubmit |
| `impact-radius-hook.py` | `r__posttool__impact-radius.py` | REFLEX, PostToolUse |
| `session-isolation-hook.py` | `g__session__session-isolation.py` | GATE, SessionStart |
| `source-attribution-check.py` | `d__stop__source-attribution.py` | DETECTOR, Stop |
| `claim-verify-stop.py` | `g__stop__claim-verify.py` | GATE, Stop |
| `brain_doctor.py` | `run__brain-doctor.py` (keeps `/brain-doctor` alias) | RUNNER |
| `ai_sync.py` | `run__ai-sync.py` (thunks `ai-push`/`ai-sync` unchanged) | RUNNER |
| `generate_neural_map.py` | `lib__neural-map.py` (import alias kept) | LIBRARY |
| `trace-hook.py` (multi-event) | `obs__multi__trace.py`, declared per-event in the manifest | OBSERVABILITY |

User-facing command names (`ai-push`, `ai-sync`, `brain-doctor`, `octo-dim`, `query_connectome`, `impact-radius`) keep stable thin aliases forever; the rename governs the FILE, the alias governs muscle memory.

---

## 6. WHAT STAYS MODEL-BEHAVIOR (irreducible) - and how each is STILL registered + asserted

Each is a Registry row with `strength: PRESENCE`, an explicit `source.anchor`, and a Proof of `ANCHOR_PRESENT` + (where one exists) a companion Detector. None is bare prose. The Coverage Ledger prints them as PRESENCE so 100% coverage is never misread as 100% force. Reflexes are honestly capped at FIRES (inject ≠ obeyed), per the panel's unanimous fires-vs-obeyed note.

| rule | strength | how wired + asserted |
|---|---|---|
| no-hallucination / never-invent-data | PRESENCE | ANCHOR_PRESENT + companion `d__stop__source-attribution.py` (Provenance footer present). EFFECTIVE unreachable; never claimed. |
| connector-not-human / Stance / act-as-role | PRESENCE | ANCHOR_PRESENT + Provenance-footer detector. Gating identity = false-positive machine; presence-asserted only. |
| tone / machine-register (residue) | PRESENCE | mechanical 6 (em-dash, filler, triads…) are GATE `g__stop__cadence.py` + DETECTOR; the "sounds human" judgment is PRESENCE backed by that detector id. |
| minimum-viable-change / do-it-right-not-fast | PRESENCE | ANCHOR_PRESENT (+ optional diff-size warn detector). No hook can prove "minimal/root-cause"; the row guarantees it appears in the Ledger and cannot silently vanish. |
| PromptDefense baseline (role-lock, treat-fetched-untrusted, refuse-injection) | PRESENCE | ANCHOR_PRESENT; secret-echo subset additionally GATE `g__pretool-bash__secrets-grep.py`. The refusal itself is inference-time, presence-asserted. |
| Best-Tool-First / when-unsure | PRESENCE | ANCHOR_PRESENT, backed by the delegate reflex existing; tool choice stays model-side. |

The point of Rule #1 is not to mechanize judgment. It is to forbid the row from having an empty `mechanism` list. A PRESENCE row whose anchor drifts (operator rewords the header) fails ANCHOR_PRESENT and is caught - which is why anchors are explicit ids in CLAUDE.md, not heading-text heuristics (closes the declarative + ontology brittleness note).

---

## 7. MIGRATION PLAN - ~13% → 100%, ordered, shippable

**PHASE 0 - CHEAP 20% / BUYS 80% (ship day one, no renames, no class generation):**
Author `registry/rules.yaml` + `rules.schema.json` for the ~30 ALREADY-scripted rules using EXISTING names. Add D0 (bootstrap self-check), D1 (schema), D2 (no-orphan-prose, per-anchor), D3.FILE_EXISTS + IN_HOOKS_JSON. Wire the sentinel into `.githooks/pre-push`. This alone makes Rule #1 real for the wired majority, kills the phantom-script class corpus-wide, and turns coverage into a printed number.

First 5 concrete commits:
1. `feat(registry): add rules.schema.json + registry/rules.yaml seeded from the 23 hook-wired scripts (existing names)`
2. `feat(doctor): D0 bootstrap self-check (core.hooksPath, pre-push sentinel, rules.yaml loads) fail-closed first`
3. `feat(doctor): D1 schema-validate rules.yaml reusing validate-skill-manifest engine; D3 FILE_EXISTS + IN_HOOKS_JSON per rule`
4. `feat(doctor): D2 bidirectional no-orphan-prose via explicit CLAUDE.md anchor ids; print Coverage Ledger`
5. `feat(hooks): add OCTORATO-WIRE-GATE sentinel + brain_doctor invocation to .githooks/pre-push; R-META-001/002 rows`

**PHASE 1 - complete corpus (shipped):** every CLAUDE.md anchor is backfilled (35/35) with PRESENCE rows for model-behavior, and the corpus was pruned of echoes (83 raw entries counted down to 43 real rules). D2 proves zero un-backed prose. Corpus-coverage holds at an honest 100% and is FAIL-armed: 6 skill-canon rows (registry PRESENCE/DETECTOR) plus a memory-directive class row (backed by the brain-memory-recall hook plus the MEMORY.md index) close the last gap, so any uncovered rule flips the ledger from PASS to FAIL and blocks the push.

**PHASE 2 - drift + polymorphic OO:** generate hooks.json + settings.json from the manifest (sha-stamped); add the Mechanism hierarchy + RuleLoader/MechanismFactory; D3 runs Gate/Reflex/Detector/Presence liveness; D5 drift gate. Wiring now propagates across machines. Flip PRESENCE warn→fail-closed once each has anchor + companion.

**PHASE 3 - convention + grandfather (revised; shipped):** the mass rename was reassessed against the real blast radius and dropped. The rename map revealed that core infra (brain_doctor, ai_sync, check-generic, lineage-doctor, install-runners, memory_sync, gate-check) is referenced by stable command name everywhere and must NOT be renamed, and that several hooks are multi-event (trace-hook) or double as CLIs (cadence-lint). Renaming 18+ scripts across the brain is high-risk, cosmetic churn against the very gate just built. Instead Phase 3 ships `registry/naming-policy.yaml` (the canonical scheme + a grandfather list of the 18 existing hook scripts) and a `registry-naming` doctor check: a NEW Claude Code hook script MUST follow `<prefix>__<event>__<slug>.py` and its prefix must agree with its declared kind (name-reparse assert); existing scripts are grandfathered and exempt. Future consistency, zero churn, zero risk. The physical rename of grandfathered scripts can still happen later, one codemod at a time, if ever desired.

**PHASE 4 - liveness + honest ceiling (shipped):** standardize `trace-hook` → `.brain/trace.jsonl`; D6 STALE detection (WARN). Add EFFECTIVE probes for the ~3 cheap deterministic gates (cadence, secrets, qa-merge) only. Publish the Ledger to brain-digest. Stop here; do NOT over-wire model-behavior into fake gates.

---

## 8. SELF-BOOTSTRAP + TOP RISKS

**Who wires Rule #1 and the doctor (the chicken-egg, closed by a fixed point):**
Rule #1's mechanism IS brain_doctor (Registry `R-META-001`). brain_doctor is invoked by `.githooks/pre-push` (Registry `R-META-002`). The irreducible axiom is a tiny, eyeball-auditable 3-line stanza in pre-push marked `# OCTORATO-WIRE-GATE` that (a) checks brain_doctor exists+executable, (b) runs it, (c) exits non-zero on failure. Mutual mirror: pre-push runs the doctor; the doctor's D0 greps pre-push for the sentinel. Neither alone is trusted; together closed. If either is deleted, the next `ai-pull` (which ends with brain_doctor) on any machine reports CORRUPT. The keystone cannot quietly un-wire itself.

**Real reachable percentage (honest):** 100% COVERAGE is reachable and is the correct healthy target - every rule carries a registered, live-asserted mechanism. Behavioral ENFORCEMENT is NOT 100% and the Ledger says so per rule: GATE+DETECTOR rules are mechanically real; REFLEX rules are capped at FIRES (injected, obedience unproven); PRESENCE rules are covered, not forced; EFFECTIVE-proven is only the ~3 cheap gates. A Ledger reading "Coverage 100% / Effective ~20%" is the CORRECT state, documented in the header so stakeholders never misread it.

**Top risks + mitigations:**
1. **Manifest becomes the new prose** (weak proofs). → every Gate/Reflex/Detector MUST ship `--selftest`; FILE_EXISTS-alone is schema-rejected for non-PRESENCE strengths.
2. **PRESENCE as escape hatch** (downgrade a hard rule to green it). → SECURITY/GENERIC/ARCHITECTURE schema-forbidden from PRESENCE; downgrades need an operator-signed, expiry-dated `waiver` (agent-proof env, the qa-merge precedent - the agent cannot self-waive).
3. **MECE erosion** (contributors invent categories / straddle). → 9-enum schema gate + explicit precedence tie-breaker; a new category is a schema PR the operator reviews. The ~6 straddling rules are mapped in §2.
4. **Fires-vs-obeyed false security** (a reflex marked "wired" the model ignores). → liveness tiers force honesty; a Reflex can NEVER be EFFECTIVE; the Ledger prints "injected, obedience unproven".
5. **Rename blast radius** (Phase 3, 71 scripts, the sed-depth bug). → codemod generated from the manifest (graph before grep via impact-radius), one-release aliases for documented CLI names, gated on D4==0; the doctor IS the acceptance test.
6. **Anchor brittleness** (heading reword breaks ANCHOR_PRESENT). → explicit anchor-id comments per rule in CLAUDE.md, exact-match not heuristic; a PreToolUse reflex flags a CLAUDE.md edit that adds an anchor without a matching rules.yaml row (completeness by reflex, not discipline).
7. **Unguarded fresh-clone push** (core.hooksPath unset before ai-pull). → install-runners sets it idempotently; server-side master PR-protection is the backstop.

---

**Decision record:** approved and shipped. Phase 0 landed in v4.0.0 (registry, doctor D0-D3, pre-push gate, phantom-script kill); the create-to-register loop landed in v4.2.0; the fail-closed meta-gate + gateable classification landed in v5.3.0 (#180); the waivers that armed it landed in v5.4.0; the v5.5.0 wave hardened the teeth: waiver `expires` is enforced (expired = unwaived = FAIL), release-drift is checked in both directions, anchor ambiguity is detected instead of first-match-wins, the corpus-coverage denominator counts skills canon plus memory directives, and the pre-push gate's own inputs are fail-closed (missing registry, doctor, or Python blocks the push, never a silent skip). The final wave closed corpus-coverage to an honest 100% and armed its teeth: skills canon is carried by 6 registry PRESENCE/DETECTOR rows, memory directives by a class row wired to the brain-memory-recall hook plus the MEMORY.md index, the denominator was pruned of echoes (83 raw entries down to 43 real rules), and the ledger flips from WARN to FAIL on any uncovered rule so a new un-wired rule blocks the push; enforcement strength prints per row (REFLEX/PRESENCE) so coverage is never misread as force.

💡 Unlock-suggestion: none - every artifact above is buildable on the operator's machine with existing tools (validate-skill-manifest engine, impact-radius, merge-hooks, .githooks/pre-push all verified present).

☠ Prune-suggestion: on Phase 3 completion, `check-hooks-drift.py` and `check-stats-drift.py` become dead cells (their manual drift role is subsumed by D5); flag for prune then, not now.
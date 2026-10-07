# Hook Orchestration: Reactive Control Architecture with Adaptive Recall

**Status:** Canonical architecture spec, living document.
**Scope:** Octorato brain (`~/.claude/`). Does NOT touch any arm or company layer.

---

## 1. Purpose

The brain's hooks were originally ad-hoc advisory rules: prose suggestions sprinkled across `CLAUDE.md` and skill files, enforced only by the agent's willingness to comply. This document formalizes them as a coherent, multi-layer reactive control architecture: a set of enforced reflexes instead of voluntary suggestions. The governing principle is that the agent is a **CONNECTOR** to real, cited sources. Its default behavior is therefore to CONNECT (load the right skill, activate the right agent, route to the appropriate model tier), and SELF (answering from the agent's own parametric knowledge) is reserved only for explicit opinion requests or cases where every seek path returns empty. SELF is the exception, not the mode.

---

## 2. The Four-Layer Stack

The architecture is stratified into four layers, each with a distinct theoretical foundation. Control flows downward (routing → flow → priority → atoms); feedback flows upward (ECA results → BT status → statechart transitions → bandit reward).

```
┌─────────────────────────────────────────────────────────┐
│  L4  Routing      Contextual Bandit / LinUCB            │
│                   model-tier selection (Haiku/Sonnet/Opus/Fable)│
├─────────────────────────────────────────────────────────┤
│  L3  Flow         Statechart (4D phase machine)         │
│                   + Blackboard (ledger + connectome)    │
├─────────────────────────────────────────────────────────┤
│  L2  Priority     Behavior Trees                        │
│                   hook composition & arbitration        │
├─────────────────────────────────────────────────────────┤
│  L1  Atoms        ECA rules + Rete matching             │
│                   one hook = one ECA triple             │
└─────────────────────────────────────────────────────────┘
```

### L4 (Routing): Contextual Bandit / LinUCB

**Foundation:** Contextual Bandit formalism (Langford & Zhang 2007) with the LinUCB algorithm (Li et al. 2010). At the start of each turn, a context vector `x_t` is constructed from observable prompt features (token count, detected task type, cost-so-far in the session, prior model tiers used). The bandit selects a model arm `a ∈ {Haiku, Sonnet, Opus, Fable}` (judgment work is pinned to Fable by policy, outside the bandit's choice set) to maximize the expected reward:

```
reward = quality(a, x_t) · w_q  −  cost(a) · w_c
```

where `w_q` and `w_c` are operator-tunable weights. LinUCB maintains an upper confidence bound over the linear reward estimate, trading off exploration of uncertain arms against exploitation of the best-known arm. An alternative formulation is a **Mixture-of-Experts (MoE) gating** function (Jacobs, Jordan, Nowlan & Hinton 1991): a learned soft-router that weights expert sub-models by context. The bandit framing is preferred here because it is online, reward-observable, and does not require a held-out labeled dataset.

L4 sits above all other layers. Its decision is a meta-decision: which cognitive resource to allocate before any hook fires.

### L3 (Flow): Statechart + Blackboard

**Foundation (statechart):** Harel Statecharts (Harel 1987) provide the formal model for the **4D phase machine**: `Describe → Delegate → Diligent → Disclose`. Each phase is a state with an entry action, a set of internal transitions, and an exit condition. History nodes preserve which sub-state was active when an interruption (e.g., a blocking gate) forces re-entry, so the machine resumes rather than restarts.

```
[Describe] ──────────► [Delegate] ──────────► [Diligent] ──────────► [Disclose]
     ↑  (history H)         ↑  (history H)         ↑  (history H)
     └── gate blocked ──────┘                       │
                                                     └── BT.Failure → stays
```

**Foundation (coordination substrate):** The Blackboard architecture (Hayes-Roth 1985) provides the shared working memory that all hooks read from and write to. In the brain, the blackboard has two persistent surfaces:

- **Per-turn ledger**: the structured record of the current turn's events, tool calls, phase state, and accumulated facts. Lives in memory during the turn; a summary may be written to `~/.claude/connectome/` on Stop.
- **Connectome** (`neural_map.json`, `lineage.yaml`): the cross-turn graph of skills, agents, and concepts. Knowledge sources write to it (skill promotion, ai-push); recall hooks read from it.

The statechart governs *what phase is active*; the blackboard governs *what is known*.

### L2 (Priority): Behavior Trees

**Foundation:** Behavior Trees (Colledanchise & Ögren 2018, arXiv:1709.00084), which have been proven to generalize Brooks' (1986) subsumption architecture as a special case. Behavior Trees use typed return status (`Success`, `Failure`, `Running`) and two core composite nodes:

- **Sequence** (`→`): executes children left-to-right; aborts and returns `Failure` on the first child failure. Used for the 4D phase chain and for composing blocking gates (any gate failing = abort the action).
- **Fallback** (`?`): executes children left-to-right; returns `Success` on the first child success. Used for priority arbitration when multiple hooks register for the same event: the highest-priority hook fires; lower-priority hooks are fallbacks.

Each hook is assigned an explicit integer priority. On a shared event:

```
Fallback(priority-sorted injectors) under a Sequence(gates)
```

Gates are composed as a Sequence: all must succeed before injectors fire. Injectors are composed as a Fallback: the highest-priority succeeding injector wins (or all run if they are declared parallel).

A 4D phase advances **only when its Behavior Tree returns `Success`**. This is the machine-verifiable definition of "phase complete", replacing the former prose rule.

### L1 (Atoms): ECA Rules + Rete

**Foundation:** Event-Condition-Action (ECA) rules, originating in active database research (Dayal et al. 1988 HiPAC project; Widom & Finkelstein 1990). Each hook is one ECA triple:

```
hook = (event, condition, action, coupling_mode)
```

| Field | Domain |
|---|---|
| `event` | `UserPromptSubmit` \| `PreToolUse` \| `PostToolUse` \| `Stop` |
| `condition` | predicate over blackboard state, prompt features, or tool call payload |
| `action` | `inject` \| `block` \| `write_ledger` \| `recall` |
| `coupling_mode` | `immediate` (synchronous, same transaction) \| `deferred` (async, next tick) |

Condition matching across all registered ECA rules is performed efficiently using the **Rete algorithm** (Forgy 1982), which compiles patterns into a discrimination network, evaluating only the rules whose conditions are touched by a state change rather than re-scanning all rules on every event.

The connectome-heartbeat hook, the impact-radius-hook, the gate-check, and the fail-open recall hooks are all ECA atoms at L1, orchestrated by L2 Behavior Trees.

---

## 3. Substrate (Cross-Cutting, Not a Layer)

Two theoretical frameworks underlie the entire stack as substrate. They are not a fifth layer but the medium through which the layers operate.

### Spreading Activation: Connectome Recall

**Foundation:** Spreading Activation networks (Collins & Loftus 1975; Anderson ACT-R 1983). The 2025 SYNAPSE architecture (arXiv:2601.02744) demonstrates activation-decay traversal for LLM augmentation. The connectome recall that fires on every `UserPromptSubmit` (the "heartbeat") is semantically a spreading activation query: given a seed concept (the task description), activation propagates outward through the `neural_map.json` graph, decaying by a factor `α` per hop and boosted by recency, and the top-k nodes above the activation floor are returned as relevant skills and agents.

The **current implementation** is a static approximation: TF-IDF vectorization + cosine similarity, computed at `ai-push` time and stored as a pre-built index. This is equivalent to a one-hop activation query on a flat similarity graph, correct in direction and incomplete in coverage: multi-hop paths are invisible. Recency is not. `scripts/update_neural_activity.py` decays the stored co-activation matrix and `scripts/query_connectome.py` applies an exponential time decay (roughly a 69-day half-life) to the Hebbian boosters, so a recency term is already live.

The **specified upgrade** (the multi-hop traversal, not yet implemented) is the full activation-decay form, of which only the `recency_boost` term exists today:

```
A(v, t+1) = Σ_{u→v} w(u,v) · A(u, t) · α^depth(u,v) · recency_boost(u)
```

This makes the heartbeat's 1-2 hop recall theoretically grounded rather than heuristic.

### Marr–Albus Cerebellar Control Loop: 4D Feedforward/Feedback

**Foundation:** The Marr–Albus model of cerebellar learning (Marr 1969; Albus 1971). In the cerebellum, mossy-fiber inputs encode context and drive a feedforward prediction; climbing-fiber inputs carry the teaching error signal; the adaptive loop converges when the prediction matches the outcome.

The 4D architecture maps onto this exactly:

| Cerebellar component | 4D analog |
|---|---|
| Mossy-fiber context | Gate Manifest (pre-write enumeration of exact target file-set) |
| Feedforward prediction | The Manifest's predicted Touched set |
| Climbing-fiber teaching signal | Provenance Footer (`Touched` field) |
| Error signal | `Touched ∖ Manifest ∪ Manifest ∖ Touched` (skips + excess) |
| Adaptive loop | The `WHILE (open work / remnants): 4D()` loop |
| Convergence criterion | `Touched ≡ Manifest` (set equality, no skip, no excess) |

The WHILE loop exits when the error signal is zero, the "cerebellum" reaches precision without tremor. Feedforward alone is blind (open-loop); feedback alone is tremor (correct-after-miss, "Parkinson" mode); feedforward + binary feedback + involuntary firing of the impact-radius hook is the full cerebellar model.

---

## 4. Analytic Companions

These frameworks are **verification and normative tools**, not implementation targets. They provide formal guarantees over the architecture.

### Petri Nets: Liveness, Boundedness, Deadlock

**Foundation:** Murata (1989), "Petri Nets: Properties, Analysis, and Applications." The per-turn ledger is a marked Petri net: places are phase-states and resource slots; transitions are hook firings; tokens are control flow. Standard reachability analysis over this net provides:

- **Liveness:** every phase is eventually reachable (no hook permanently blocks progress).
- **Boundedness:** the ledger never grows unboundedly (no runaway token accumulation).
- **Deadlock freedom:** no configuration exists where all transitions are permanently disabled.

These are offline proofs over the static hook topology, run when hooks are added or restructured, not a runtime mechanism.

### Active Inference / Free Energy Principle: Normative Objective

**Foundation:** Friston (2006, 2019). Active Inference frames an agent's behavior as the minimization of variational free energy (equivalently, the minimization of expected surprise over sensory observations). Under this framing, every hook firing is an action that reduces the agent's prediction error about the world: the connectome recall reduces uncertainty about which skill is relevant; the gate-check reduces uncertainty about whether a write is safe; the Provenance footer reduces uncertainty about whether the intent was realized. The WHILE loop continues until surprise is minimized: the session's free energy converges to zero.

This is the **normative interpretation** of what the brain is doing. It does not change the implementation but provides the theoretical ground for why fail-closed gates, mandatory recalls, and the WHILE loop are not arbitrary rules but consequences of a principled objective.

---

## 5. Refactoring Rules Derived from the Theory

These are the **engineering invariants** the theory demands. Any hook addition, removal, or restructuring that violates these invariants is a regression, not a refactor.

1. **Every hook is an explicit ECA triple** with typed fields: `event`, `condition`, `action`, `coupling_mode`. Hooks without explicit types are architectural debt; they must be typed before deployment.

2. **Context-injection hooks FAIL-OPEN.** A failed recall (connectome unreachable, TF-IDF index stale, file missing) must never block a turn. The agent continues without the injected context and notes the miss in the ledger. Rationale: an injection failure is recoverable; a blocked turn is not.

3. **Gate/block hooks FAIL-CLOSED.** A gate that errors (file write check crashes, gate-check script missing) defaults to **block**. Rationale: the cost of a false block is a delayed write; the cost of a false pass is an unsafe or incoherent write to the brain or an arm.

4. **On the same event, hooks compose as a Behavior Tree with explicit priority** (specified, NOT implemented). The runtime fact it is specified against: hooks registered on one event run in PARALLEL, and a `PreToolUse` call is denied when ANY of them denies. Array order in `hooks.json` is not priority and no gate may assume it; the two v8 isolation gates and the dimension gate deny independently, and either deny wins. Blocking gates form a Sequence (any gate failure aborts the action). Injectors form parallel children under a Fallback root. The specification asks for an integer priority field in the hook definition, so that ordering stops being implicit.

5. **A 4D phase advances only when its Behavior Tree returns `Success`.** This is the machine-verifiable exit condition for each phase. "Looks done" is not a Behavior Tree status.

6. **Model-tier routing (L4) is a meta-decision above the hook layer.** The bandit reads prompt context and cost-so-far and selects the tier before the first ECA rule is evaluated. No ECA rule at L1 may change the model tier mid-turn; tier changes require a new turn boundary.

---

## 6. Implementation Status

| Component | Status | Notes |
|---|---|---|
| L1: ECA atoms | **Enforced** | connectome-heartbeat, impact-radius-hook and the fail-open recall hooks are all deployed and fire on their declared events. `gate-check` is not among them: it is a CLI at `scripts/gate-check`, invoked by the model, and it appears in no `hooks.json` event. |
| L2: Priority (Behavior Trees) | **Partial** | There is no explicit integer priority field anywhere. Ordering on a shared event is the array order in `hooks.json`, which is consistent with the BT model but implicit. |
| L3: Statechart (4D phase machine) | **Partial** | The phase sequence is enforced by prose + hooks; the formal Harel statechart with history nodes and machine-verifiable exit conditions is specified here but not yet compiled into an executable state machine. |
| L3: Blackboard (ledger + connectome) | **Enforced** | The per-turn ledger and connectome are the operative substrate; all recall hooks read from them. |
| SELF→CONNECT default | **Enforced** | Documented in `CLAUDE.md`; heartbeat fires on every prompt. |
| Fail-open / fail-closed discipline | **Enforced** | Injection hooks are fail-open; gate hooks are fail-closed; documented in `CLAUDE.md` and skills. |
| L4: Contextual Bandit router | **Specified, NOT implemented** | Multi-day ML effort. Requires reward logging infrastructure, online update loop, and feature extraction pipeline. Do not claim as done. |
| Multi-hop decayed traversal | **Specified, NOT implemented** | Recency decay IS implemented (`update_neural_activity.py`, `query_connectome.py`, ~69-day half-life). What is missing is replacing the static TF-IDF index with a live multi-hop graph traversal with decay parameter `α`. Estimated effort: 1-2 days of implementation + evaluation. Do not claim as done. |
| Petri net liveness proofs | **Specified, NOT implemented** | Offline verification tooling not yet built. |
| Rule registry + gate-liveness (v4 to v6, 2026-06 to 2026-09) | **Enforced** | `registry/rules.yaml` types every rule; `brain_doctor` asserts wiring per rule and runs each fail-closed gate's `--selftest` fixture pair. See `wired-or-corrupt.md` section 9. |
| Receipts + outward-send gate (v7, 2026-09) | **Enforced** | Hook-written receipt ledger plus `g__pretool-mcp__outward-send.py` at PreToolUse; a send without a seek receipt or a gate receipt is denied. See `v7-nothing-ships-unverified.md`. |

---

## 7. Further Reading

1. Langford, J. & Zhang, T. (2007). "The Epoch-Greedy Algorithm for Multi-armed Bandits with Side Information." *NeurIPS 2007*.
2. Li, L., Chu, W., Langford, J. & Schapire, R.E. (2010). "A Contextual-Bandit Approach to Personalized News Article Recommendation." *WWW 2010*.
3. Jacobs, R.A., Jordan, M.I., Nowlan, S.J. & Hinton, G.E. (1991). "Adaptive Mixtures of Local Experts." *Neural Computation 3*(1), 79–87.
4. Harel, D. (1987). "Statecharts: A Visual Formalism for Complex Systems." *Science of Computer Programming 8*(3), 231–274.
5. Hayes-Roth, B. (1985). "A Blackboard Architecture for Control." *Artificial Intelligence 26*(3), 251–321.
6. Colledanchise, M. & Ögren, P. (2018). "Behavior Trees in Robotics and AI: An Introduction." arXiv:1709.00084. CRC Press.
7. Brooks, R.A. (1986). "A Robust Layered Control System for a Mobile Robot." *IEEE Journal of Robotics and Automation 2*(1), 14–23.
8. Dayal, U., Blaustein, B., Buchmann, A., Chakravarthy, U., Hsu, M., Levin, R., McCarthy, D., Rosenthal, A., Sarin, S., Silberschatz, A., Tanaka, K. & Zimmermann, M. (1988). "The HiPAC Project: Combining Active Databases and Timing Constraints." *ACM SIGMOD Record 17*(1), 51–70.
9. Widom, J. & Finkelstein, S.J. (1990). "Set-Oriented Production Rules in Relational Database Systems." *ACM SIGMOD 1990*, 259–270.
10. Forgy, C.L. (1982). "Rete: A Fast Algorithm for the Many Pattern / Many Object Pattern Match Problem." *Artificial Intelligence 19*(1), 17–37.
11. Collins, A.M. & Loftus, E.F. (1975). "A Spreading-Activation Theory of Semantic Processing." *Psychological Review 82*(6), 407–428.
12. Anderson, J.R. (1983). "A Spreading Activation Theory of Memory." *Journal of Verbal Learning and Verbal Behavior 22*(3), 261–295.
13. SYNAPSE (2025). "Spreading Activation for LLM Augmentation." arXiv:2601.02744.
14. Marr, D. (1969). "A Theory of Cerebellar Cortex." *Journal of Physiology 202*(2), 437–470.
15. Albus, J.S. (1971). "A Theory of Cerebellar Function." *Mathematical Biosciences 10*(1–2), 25–61.
16. Murata, T. (1989). "Petri Nets: Properties, Analysis, and Applications." *Proceedings of the IEEE 77*(4), 541–580.
17. Friston, K. (2006). "A Free Energy Principle for the Brain." *Journal of Physiology-Paris 100*(1–3), 70–87.
18. Friston, K. (2019). "A Free Energy Principle for a Particular Physics." arXiv:1906.10184.

<!-- moved-from-claude-md v10-T13 -->
## 8. Constitution detail (moved from CLAUDE.md)

These paragraphs were the constitution's own text until v10 (T13), moved here so `CLAUDE.md` keeps only what every session needs. They are kept as written, with em-dashes normalised; `CLAUDE.md` now carries a short paragraph pointing here.

### The 4D WHILE and its root goal

**The 4D runs in a WHILE, not once**, `while (open work / remnants / Touched ≠ intent): 4D()`. Exit only when the Provenance footer's self-read reconciles (no skip, no excess), never on "looks done". The footer is proprioception: comparing what you *touched* against what you *meant* is what closes the gap between intent and effect, and that gap, not malice, is the recurrent failure. **The WHILE needs a PERSISTED root**, because `intent` in context is not one: every obstacle (a denied permission, a disabled region, a missing binary) rewrites it, so after a chain of them the loop keeps running against the last sub-goal while the session's real goal has gone unnamed for turns, and a legitimately-evidenced sub-goal close reads as victory. **The ganglion is `g__stop__goal-anchor.py`** (Registry `FLOW.root-goal-anchor`): it pins the root goal to disk per session, re-anchors only on a deterministic marker (`objetivo:` / `goal:` / a pivot phrase), and blocks once when a closure claim lands with the root unmentioned for 4+ turns. Hard ceiling of 2 interruptions per anchor; `goal-anchor-ok` on a line exempts the turn.

### The cerebellum

**The cerebellum (precision without tremor).** The reach hits exactly, no skip, no excess, only when three things hold together: (1) **feedforward**, the 4D Gate Manifest enumerates the EXACT target file-set *before* acting (a sharp predicted target, not a vague intent); (2) **binary feedback**, the Provenance `Touched` is reconciled as set-equality against that Manifest + `impact-radius.py`, not a "I think I got it"; (3) **involuntary firing**, the `impact-radius-hook` (PostToolUse `Write|Edit`) surfaces a concept's other references the moment you edit it, so the scan fires without you choosing to. Feedback alone is tremor (correct-after-miss = the "Parkinson" mode); feedforward + binary + involuntary feedback is the cerebellum, take exactly what you want, at speed, without dysmetria.

### Graph before grep

**ULTRA RULE, Graph before grep ("and the graph?").** A grep is a table scan: it depends on the input string ("it always changes"), so coverage is stochastic and partial; it is repo-text-only (blind to off-repo + derived surfaces); and it costs ~100x the tokens of a seek (measured: ~1737 vs ~16 for one concept). The graph **is**, a persistent index you traverse, not rebuild per query. So before grep'ing the brain to find where a concept lives, **SEEK** it: `python3 ~/.claude/scripts/impact-radius.py --file <path>` (or `"<concept>"`) traverses `connectome/lineage.yaml` (+ the gitignored `company/connectome/lineage.yaml` private layer) and returns every impacted surface deterministically, with a machine **receipt**. **Arms carry their own sealed graph** (`<ARM>/.claude/connectome/lineage.yaml`, seeded from `templates/arm/connectome/`): run the same script from inside an arm and the seek auto-detects that layer (`layer=arm` receipts), one graph per seek, never merged across arms. Quote that receipt verbatim in the Provenance `Graph:` field. A grep is a labeled FALLBACK only for an *unlit neuron* (no edge yet), and the honest fallback files a candidate so the graph grows; it is a PASS, not a failure. The real failure: grep'ing brain surfaces and then WRITING files **without a seek**, the graph is the octopus's blood; without it you are blind and pixelate. The WHILE exits in one beat only on `SEEK-COMPLETE`. **Three graphs, one rule:** *recall* (which skill/agent knows this?) seeks the **connectome** (`query_connectome.py query`); *surfaces* (where does this concept live / what derives from it?) seek **lineage** (`impact-radius.py`); *past* (have I already lived this, already written this lesson down?) seeks the **memory index** (`query_connectome.py memory "<what I am trying to recall>"`, built by `scripts/generate_memory_map.py` into the gitignored `memory_map.json`). The third one closed a real hole: life-memories were the one corpus with no graph, so "do I already know this?" fell back to a scan over 200+ files, and a memory phrased in another language than the prompt was simply invisible. All three replace a grep. grep survives in exactly three places, all legitimate (not brain-memory recall): `git log --grep` (git's own index), exact-string 3D verification on a file you already know, and scanning **external** user content the connectome does not index (documents, codebases, arms).

### Prune dead cells

**ULTRA RULE, Prune dead cells (graph-driven, Disclose-time).** The same graph that routes blood also shows where tissue has died. A **dead cell** is a node the graph no longer connects: a connectome orphan (`python3 ~/.claude/scripts/query_connectome.py dead` → degree-0 isolated / degree-1 dying leaf) or a dangling lineage edge (`python3 ~/.claude/scripts/lineage-doctor.py` → a surface pointing at a file that's gone). If you already have the graph, you don't hunt for dead weight by hand and you don't bulk-`rm` on a hunch, **you ask the graph**. So: whenever a turn touches the brain (writes a skill/agent, edits the connectome, or runs a graph seek) and the scan surfaces a dead cell **related to that work**, append a one-line `☠ Prune-suggestion:` at the END of the response naming the node + its file. **Suggest, never auto-delete**, a degree-0 node may be a brand-new *unlit* neuron (give it an edge), not dead tissue (remove it), and only the operator tells the two apart. The cut is **fail-closed**, same stance as merges: the agent proposes, the operator approves. Biology, not vanity: a brain gets sharper by pruning, not by accreting (see `harmonization-over-accretion`).

### Suggest the unlock

**ULTRA RULE, Suggest the unlock (Disclose-time).** When a turn hits a capability limit, a missing tool, an OAuth scope too narrow, a permission rule, an unconnected MCP, and ships a workaround or a partial result, the Disclose MUST end with a one-line `💡 Unlock-suggestion:` naming the gap and the EXACT unlock. And the agent RUNS that unlock itself whenever it is executable on the operator's machine, only the irreducible human step (a consent click, a password, a permission grant for the exact rules) goes to the operator. Asking the operator to type a command the agent could run is friction, not safety. A disclosed limitation without its unlock is half a Disclose: the agent moves on, the gap repeats forever, and the operator has to hunt it. Mirror of ☠ Prune-suggestion, the agent proposes, the operator decides; one line, never a lecture.

### The Q1 heartbeat

The heartbeat (`scripts/connectome-heartbeat.py`) makes Q1 involuntary, like the octopus's pulse circulating blood through its whole body and returning. It surfaces a *lean*; the model still owns Q2/Q3 and the final verdict. (v7: reflex by design, see the Enforcement Scripts note.)

### Human Cadence: mechanical enforcement

Read-aloud test: if a sentence sounds like a LinkedIn thought-leader wrote it, rewrite it. The Provenance footer is exempt (machine receipt, not prose). Mechanical enforcement, two reflexes: `scripts/cadence-lint.py` flags rules 1/2/3/5/6/9 as a PostToolUse reflex on prose writes and as a CLI (`--file`/stdin, exit 1) for arm pipelines and CI; `scripts/cadence-stop-hook.py` (Stop) lints every CHAT reply before delivery and blocks once for a rewrite.

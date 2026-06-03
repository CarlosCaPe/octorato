# Hook Orchestration — Reactive Control Architecture with Adaptive Recall

**Status:** Canonical architecture spec — living document.
**Scope:** Octorato brain (`~/.claude/`). Does NOT touch any arm or company layer.

---

## 1. Purpose

The brain's hooks were originally ad-hoc advisory rules — prose suggestions sprinkled across `CLAUDE.md` and skill files, enforced only by the agent's willingness to comply. This document formalizes them as a coherent, multi-layer reactive control architecture: a set of enforced reflexes instead of voluntary suggestions. The governing principle is that the agent is a **CONNECTOR** to real, cited sources. Its default behavior is therefore to CONNECT — load the right skill, activate the right agent, route to the appropriate model tier — and SELF (answering from the agent's own parametric knowledge) is reserved only for explicit opinion requests or cases where every seek path returns empty. SELF is the exception, not the mode.

---

## 2. The Four-Layer Stack

The architecture is stratified into four layers, each with a distinct theoretical foundation. Control flows downward (routing → flow → priority → atoms); feedback flows upward (ECA results → BT status → statechart transitions → bandit reward).

```
┌─────────────────────────────────────────────────────────┐
│  L4  Routing      Contextual Bandit / LinUCB            │
│                   model-tier selection (Haiku/Sonnet/Opus)│
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

### L4 — Routing: Contextual Bandit / LinUCB

**Foundation:** Contextual Bandit formalism (Langford & Zhang 2007) with the LinUCB algorithm (Li et al. 2010). At the start of each turn, a context vector `x_t` is constructed from observable prompt features (token count, detected task type, cost-so-far in the session, prior model tiers used). The bandit selects a model arm `a ∈ {Haiku, Sonnet, Opus}` to maximize the expected reward:

```
reward = quality(a, x_t) · w_q  −  cost(a) · w_c
```

where `w_q` and `w_c` are operator-tunable weights. LinUCB maintains an upper confidence bound over the linear reward estimate, trading off exploration of uncertain arms against exploitation of the best-known arm. An alternative formulation is a **Mixture-of-Experts (MoE) gating** function (Jacobs, Jordan, Nowlan & Hinton 1991): a learned soft-router that weights expert sub-models by context. The bandit framing is preferred here because it is online, reward-observable, and does not require a held-out labeled dataset.

L4 sits above all other layers. Its decision is a meta-decision: which cognitive resource to allocate before any hook fires.

### L3 — Flow: Statechart + Blackboard

**Foundation (statechart):** Harel Statecharts (Harel 1987) provide the formal model for the **4D phase machine**: `Describe → Delegate → Diligent → Disclose`. Each phase is a state with an entry action, a set of internal transitions, and an exit condition. History nodes preserve which sub-state was active when an interruption (e.g., a blocking gate) forces re-entry, so the machine resumes rather than restarts.

```
[Describe] ──────────► [Delegate] ──────────► [Diligent] ──────────► [Disclose]
     ↑  (history H)         ↑  (history H)         ↑  (history H)
     └── gate blocked ──────┘                       │
                                                     └── BT.Failure → stays
```

**Foundation (coordination substrate):** The Blackboard architecture (Hayes-Roth 1985) provides the shared working memory that all hooks read from and write to. In the brain, the blackboard has two persistent surfaces:

- **Per-turn ledger** — the structured record of the current turn's events, tool calls, phase state, and accumulated facts. Lives in memory during the turn; a summary may be written to `~/.claude/connectome/` on Stop.
- **Connectome** (`neural_map.json`, `lineage.yaml`) — the cross-turn graph of skills, agents, and concepts. Knowledge sources write to it (skill promotion, ai-push); recall hooks read from it.

The statechart governs *what phase is active*; the blackboard governs *what is known*.

### L2 — Priority: Behavior Trees

**Foundation:** Behavior Trees (Colledanchise & Ögren 2018, arXiv:1709.00084), which have been proven to generalize Brooks' (1986) subsumption architecture as a special case. Behavior Trees use typed return status — `Success`, `Failure`, `Running` — and two core composite nodes:

- **Sequence** (`→`): executes children left-to-right; aborts and returns `Failure` on the first child failure. Used for the 4D phase chain and for composing blocking gates (any gate failing = abort the action).
- **Fallback** (`?`): executes children left-to-right; returns `Success` on the first child success. Used for priority arbitration when multiple hooks register for the same event — the highest-priority hook fires; lower-priority hooks are fallbacks.

Each hook is assigned an explicit integer priority. On a shared event:

```
Fallback(priority-sorted injectors) under a Sequence(gates)
```

Gates are composed as a Sequence: all must succeed before injectors fire. Injectors are composed as a Fallback: the highest-priority succeeding injector wins (or all run if they are declared parallel).

A 4D phase advances **only when its Behavior Tree returns `Success`** — this is the machine-verifiable definition of "phase complete", replacing the former prose rule.

### L1 — Atoms: ECA Rules + Rete

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

Two theoretical frameworks underlie the entire stack as substrate — they are not a fifth layer but the medium through which the layers operate.

### Spreading Activation — Connectome Recall

**Foundation:** Spreading Activation networks (Collins & Loftus 1975; Anderson ACT-R 1983). The 2025 SYNAPSE architecture (arXiv:2601.02744) demonstrates activation-decay traversal for LLM augmentation. The connectome recall that fires on every `UserPromptSubmit` (the "heartbeat") is semantically a spreading activation query: given a seed concept (the task description), activation propagates outward through the `neural_map.json` graph, decaying by a factor `α` per hop and boosted by recency, and the top-k nodes above the activation floor are returned as relevant skills and agents.

The **current implementation** is a static approximation: TF-IDF vectorization + cosine similarity, computed at `ai-push` time and stored as a pre-built index. This is equivalent to a one-hop, non-decaying activation query on a flat similarity graph — correct in direction, incomplete in coverage (multi-hop paths and recency are invisible).

The **specified upgrade** (not yet implemented) is an activation-decay traversal:

```
A(v, t+1) = Σ_{u→v} w(u,v) · A(u, t) · α^depth(u,v) · recency_boost(u)
```

This makes the heartbeat's 1-2 hop recall theoretically grounded rather than heuristic.

### Marr–Albus Cerebellar Control Loop — 4D Feedforward/Feedback

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

The WHILE loop exits when the error signal is zero — the "cerebellum" reaches precision without tremor. Feedforward alone is blind (open-loop); feedback alone is tremor (correct-after-miss, "Parkinson" mode); feedforward + binary feedback + involuntary firing of the impact-radius hook is the full cerebellar model.

---

## 4. Analytic Companions

These frameworks are **verification and normative tools**, not implementation targets. They provide formal guarantees over the architecture.

### Petri Nets — Liveness, Boundedness, Deadlock

**Foundation:** Murata (1989), "Petri Nets: Properties, Analysis, and Applications." The per-turn ledger is a marked Petri net: places are phase-states and resource slots; transitions are hook firings; tokens are control flow. Standard reachability analysis over this net provides:

- **Liveness:** every phase is eventually reachable (no hook permanently blocks progress).
- **Boundedness:** the ledger never grows unboundedly (no runaway token accumulation).
- **Deadlock freedom:** no configuration exists where all transitions are permanently disabled.

These are offline proofs over the static hook topology, run when hooks are added or restructured — not a runtime mechanism.

### Active Inference / Free Energy Principle — Normative Objective

**Foundation:** Friston (2006, 2019). Active Inference frames an agent's behavior as the minimization of variational free energy (equivalently, the minimization of expected surprise over sensory observations). Under this framing, every hook firing is an action that reduces the agent's prediction error about the world: the connectome recall reduces uncertainty about which skill is relevant; the gate-check reduces uncertainty about whether a write is safe; the Provenance footer reduces uncertainty about whether the intent was realized. The WHILE loop continues until surprise is minimized — the session's free energy converges to zero.

This is the **normative interpretation** of what the brain is doing. It does not change the implementation but provides the theoretical ground for why fail-closed gates, mandatory recalls, and the WHILE loop are not arbitrary rules but consequences of a principled objective.

---

## 5. Refactoring Rules Derived from the Theory

These are the **engineering invariants** the theory demands. Any hook addition, removal, or restructuring that violates these invariants is a regression, not a refactor.

1. **Every hook is an explicit ECA triple** with typed fields: `event`, `condition`, `action`, `coupling_mode`. Hooks without explicit types are architectural debt; they must be typed before deployment.

2. **Context-injection hooks FAIL-OPEN.** A failed recall (connectome unreachable, TF-IDF index stale, file missing) must never block a turn. The agent continues without the injected context and notes the miss in the ledger. Rationale: an injection failure is recoverable; a blocked turn is not.

3. **Gate/block hooks FAIL-CLOSED.** A gate that errors (file write check crashes, gate-check script missing) defaults to **block**. Rationale: the cost of a false block is a delayed write; the cost of a false pass is an unsafe or incoherent write to the brain or an arm.

4. **On the same event, hooks compose as a Behavior Tree with explicit integer priority.** Blocking gates form a Sequence (any gate failure aborts the action). Injectors form parallel children under a Fallback root. Priority is an integer field in the hook definition — implicit ordering by declaration order is forbidden.

5. **A 4D phase advances only when its Behavior Tree returns `Success`.** This is the machine-verifiable exit condition for each phase. "Looks done" is not a Behavior Tree status.

6. **Model-tier routing (L4) is a meta-decision above the hook layer.** The bandit reads prompt context and cost-so-far and selects the tier before the first ECA rule is evaluated. No ECA rule at L1 may change the model tier mid-turn; tier changes require a new turn boundary.

---

## 6. Implementation Status

| Component | Status | Notes |
|---|---|---|
| L1 — ECA atoms | **Enforced** | connectome-heartbeat, impact-radius-hook, gate-check, fail-open recall hooks are all deployed and fire on their declared events. |
| L2 — Priority (Behavior Trees) | **Enforced** | Explicit integer priority and Sequence/Fallback composition are documented in `CLAUDE.md`; hook ordering is consistent with the BT model. |
| L3 — Statechart (4D phase machine) | **Partial** | The phase sequence is enforced by prose + hooks; the formal Harel statechart with history nodes and machine-verifiable exit conditions is specified here but not yet compiled into an executable state machine. |
| L3 — Blackboard (ledger + connectome) | **Enforced** | The per-turn ledger and connectome are the operative substrate; all recall hooks read from them. |
| SELF→CONNECT default | **Enforced** | Documented in `CLAUDE.md`; heartbeat fires on every prompt. |
| Fail-open / fail-closed discipline | **Enforced** | Injection hooks are fail-open; gate hooks are fail-closed; documented in `CLAUDE.md` and skills. |
| L4 — Contextual Bandit router | **Specified, NOT implemented** | Multi-day ML effort. Requires reward logging infrastructure, online update loop, and feature extraction pipeline. Do not claim as done. |
| Activation-decay connectome upgrade | **Specified, NOT implemented** | Requires replacing the static TF-IDF index with a live graph traversal with decay parameter `α`. Estimated effort: 1-2 days of implementation + evaluation. Do not claim as done. |
| Petri net liveness proofs | **Specified, NOT implemented** | Offline verification tooling not yet built. |

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

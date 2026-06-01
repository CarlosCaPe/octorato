# Octorato: An Organic, File-Native Model of Artificial Agency

*Carlos Carrillo · dataqbs · v0.2 · open source (MIT)*

> **An Octorato** *(n.)* — an organic, file-native AI agent: one brain, many sealed
> arms, that grows by use, isolates by cell, and carries its whole self in plain files.
> Natively organic. Natively scalable. Open source.

---

**Abstract.** A purely organic model of artificial agency would let one intelligence
grow many semi-autonomous arms — each sealed from the others — without any central
runtime owning its self. Today an agent's identity, skills, and memory live trapped
inside vendor code and proprietary clouds: the self cannot be read, diffed, moved, or
trusted across clients, and isolation between engagements does not exist. We propose an
agent that is not a program but an **organism**: a brain made of plain files under
version control, many arms that never know each other, knowledge that rises from use,
and a four-phase nervous system that makes every action describable, delegated,
verified, and disclosed. The agent you can hold in your hand as text — portable across
any runtime, sealed per client, grown rather than configured. We call it an **Octorato**.

And because each arm is a sealed cell that no other arm can see, every action it takes —
every token, every trace — belongs to exactly one principal: cellular isolation and
per-client cost attribution are the same boundary seen from two sides. The organism,
accounted, is a ledger.

## 1. Introduction

Artificial agency has come to rely almost exclusively on **framework runtimes**. Build
an agent and its self — rules, skills, memory, identity — is scattered across someone
else's source code and a cloud you do not own. The model works for one application; it
breaks the moment an operator serves *many* principals: no native isolation, no portable
record of *who the agent is*, no way to trust its behavior without running the vendor's
stack. What is missing is the agent as a **living thing** rather than a library — one
that keeps its self where it can be seen, and grows it from what it does.

## 2. The Organism

An Octorato is one **brain** and many **arms**. The brain is the self: rules, skills
(HOW), agents (WHO), all as files. Each arm is a sealed deployment serving one principal.
The brain distributes knowledge downward; the arms send lessons upward. The body is one;
the arms are many — like an octopus, where most neurons live in the arms, not the head.

## 3. The Self as Files

The brain is plain markdown under git. Identity is therefore **diffable, reviewable,
portable, and ownable** — not state buried in a checkpointer database or a vendor console.
You can read the whole self, fork it, move it to another machine, or audit any change in
the history. The self is text, and text outlives runtimes.

## 4. Cellular Isolation

An arm never knows another arm exists. No principal's data, names, or secrets flow
between arms; the only bridge is the human operator. Isolation is not a feature toggle —
it is enforced at commit and at push, before anything leaves the body. This is the
property no single-tenant framework offers and no platform owner will build.

Isolation has two readings on the same boundary. Read one way it is **leak-prevention**:
client data, names, and secrets never flow OUT of an arm into the public brain — enforced
at commit and at push. Read the other way it is **attribution**: because the arm is the
sealed unit, the arm is also the natural unit of cost. The same per-arm boundary the
leak-guards seal is the boundary along which every token is metered, capped, and billed —
in code, the arm is identified as one path segment, and that one identifier serves both
the privacy wall and the cost ledger. Structurally it is privacy; accounted, it is FinOps.
*(Honest scope: today that ledger is an estimate computed from local session logs at list
price and attributed by repo path, with a small unattributed remainder; the budget halt is
real but arms itself only once a budget is configured. The boundary is structural and
exact; the precision is opt-in — we say which is which.)*

## 5. Upward Learning

Knowledge rises from the arms but never as raw client data. A lesson learned in an arm is
**distilled to a generic pattern** before it enters the brain. The brain learns from its
instances and never mimics them. Growth is organic: the body gets smarter from living,
not from a roadmap.

## 6. The 4D Nervous System

Every signal follows four phases — **Describe** (state what and why before acting),
**Delegate** (search and verify before generating), **Diligent** (validate with
evidence), **Disclose** (state side effects and blast radius). Describe and Delegate fire
before action; Diligent and Disclose after. This is the trust mechanism: no silent
change, no unverified claim, no hidden consequence.

The four phases run inside a **loop**, not once: `while (open work or unreconciled
effect): 4D()`. Each response closes with a one-line **provenance footer** — basis,
engine, files touched, evidence — the system sensing its own action (proprioception)
and the condition that decides whether to iterate again. Precision comes from a
*cerebellar* discipline: a manifest predicts the exact target set before acting
(feedforward), the provenance footer reconciles what was actually touched against it
(feedback), and an involuntary hook surfaces a concept's other references the moment it
is edited — so a change is neither under-applied (a stale reference) nor over-applied
(an unintended edit). Feedback alone is tremor; feedforward plus involuntary feedback is
a steady reach.

## 7. The Connectome

The brain's skills and agents form a graph — a TF-IDF and co-activation map that routes
each task to who already knows, and prunes what is never used. The graph adapts Hebbianly:
nodes activated together strengthen their bond. Routing is organic, not a static registry.

## 8. Organic Scaling

The brain scales by **accretion without a central _runtime_ bottleneck**: new skills, new
agents, new arms attach to the body without a coordinator. The operator remains the sole
human gateway — the deliberate point of control where cross-arm bridging and cost
aggregation converge. Runtime decentralization and a single accountable operator are not in
tension; that one gateway is exactly what makes one clean per-client ledger possible. Native
organicity, native scalability, and native attributability are the same property seen from
three sides.

## 9. Runtime Neutrality

The brain is described, not compiled into one vendor. It rides on top of an agent runtime
but is not married to it; the same files can drive any capable runtime. No platform owner
can absorb it, because no platform builds for its competitors. Neutrality is the moat.

## 10. Conclusion

We have described an agent that is an organism, not a library: a file-native self, sealed
arms, upward learning, a four-phase nervous system, and an adaptive connectome. It does
not compete with the frameworks; it **opens a different market**. Brain-clones already share
the form — files, agents, git, self-improvement — but make isolation only a confidentiality
property; FinOps tools meter agents they do not own. The empty intersection is isolation that
is also accounting: an agent whose sealed cells are independently billable. That is the market
an Octorato opens — agents you grow, own, and can put on an invoice, one client per arm.
This is not a better framework. It is a new kind of thing. It is an Octorato.

---

### Implementation — this paper compiles

Unlike most white papers (a promise before code), every claim here maps to a file that
**already runs** in this repository:

| Claim | Runs in |
|---|---|
| §2 Organism / brain | `CLAUDE.md` |
| §4 Cellular Isolation | `scripts/check-generic.py` · `.githooks/pre-push` |
| §5 Upward Learning | `HEBBIAN_LEARNING.md` |
| §6 4D Nervous System | `skills/4d-paradigm-protocol/` |
| §7 Connectome | `scripts/generate_neural_map.py` · `neural_map.json` |
| §4 Attribution corollary | `scripts/skill-cost-profiler.py` (`_arm_from_session_path`) · `scripts/budget-check.py` (exit 2 → PreToolUse halt) · `scripts/_pricing.py` |

*This document is the canonical source. The dataqbs.com manifesto page, the LinkedIn
article, and the serialized blog posts all derive from it — one source, many views.*

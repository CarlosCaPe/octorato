---
name: peripheral-parallel-dispatch
description: Decision rule for WHEN to fan work out to N parallel sub-agents/arms vs solve it centrally, and HOW the center reconciles divergent results without becoming the bottleneck. Use before launching multiple agents or a Workflow, or when one context can't hold the whole job.
metadata:
  type: pattern-reference
  origin: octopus↔OS symbolism analysis — 2026-06-01 session (8-arms-parallel vs central-brain match)
---

# Peripheral Parallel Dispatch

## The biology this encodes

The octopus runs **eight arms on different tasks at the same time** — one prying a shell, one anchoring, one tasting the water. The central brain does **not** micromanage them. It sets *intent* and *reconciles* what comes back; ~2/3 of the neurons live in the arms, deciding the *how* locally. That is exactly how an OS scheduler multiplexes apparatus it never operates itself: the kernel coordinates, the processes do the work. The center stays uncongested by **delegating the doing and keeping only the reconciling**.

The failure mode this prevents is a **central bottleneck**: a brain that fans out but then re-does, re-reads, or re-decides every arm's work in the center — losing all the parallelism it paid for.

## When this fires

Before any of:
- launching multiple `Agent` calls or a `Workflow`,
- a job too big for one context (migration, audit, broad sweep),
- "should I just do this myself or split it?"

## Decision rule — fan out vs solve centrally

**Fan out** when ALL hold:
1. **Decomposable** — the work splits into independent units with little cross-talk.
2. **Width > depth-of-context** — covering it serially would blow the context window or wall-clock.
3. **The center's job is reconciliation, not redoing** — you can verify/merge results without re-deriving them.

**Solve centrally** when: the task is one tight reasoning chain, units depend heavily on each other's intermediate state, or the reconciliation cost ≥ the doing cost (then splitting is pure overhead).

## How the center reconciles without becoming the bottleneck

The arm decides the *how*; the center owns only intent-in and reconciliation-out:

| Center DOES (cheap) | Center must NOT do (recreates the bottleneck) |
|---|---|
| Set a sharp predicted target per arm (feedforward) | Re-read every file an arm already read |
| Check returned results as **set-equality** vs the manifest | Re-derive an arm's conclusion from scratch |
| Dedup / merge across arms (cross-item view) | Serialize arms that could run concurrently |
| Adversarially **verify** a claim, not reproduce it | Micromanage each arm's steps |

- Prefer **structured returns** (schemas) so the center reconciles data, not prose.
- Prefer **`pipeline()` over a barrier** — let each arm flow stage-to-stage; only use `parallel()` when you genuinely need *all* results at once (dedup, early-exit-on-zero, cross-comparison).
- The **Provenance footer** is the reconciliation receipt: `Touched` reconciled against the manifest is the center "feeling" all eight arms at once (proprioception), not re-touching them.

## Sweeping: axes, mutual blindness, and the stop condition

The rule above says *when* to fan out. This says how to fan out a **search**, where the arms are looking for something whose size nobody knows yet. Four constraints, and the brain paid for three of them in production.

**1. Searchers must be blind to each other.** An octopus arm tasting the water does not wait to see what the arm prying the shell found. N searchers that can see each other's partial results converge on the first one's framing, and you get one search wearing N costumes. Independence is not a nicety here, it is the entire reason you paid for parallelism.

**2. One axis leaves structural holes, so vary the axis, not the count.** Running the same query shape N times finds the same things N times. The holes an axis leaves are a property of the axis, so more repetitions never reach them. Sweep by container, by content, by entity, and by time. The receipts, three domains, same failure:

| Receipt | Single axis used | What it produced |
|---|---|---|
| Email swept with a filter | one folder scope | items in spam and trash never seen |
| Chat read by one identifier | one of two live IDs | a confident **false** "not there" |
| Results piped through `head -N` | one truncated page | edits made from a partial list |

**3. Stop by saturation, not by a counter.** When the population is enumerable (a queue, a file list) you stop when the queue drains. When it is **not** enumerable (threads, references, impacted surfaces), a fixed `while count < N` stops in the middle and calls it done. Stop instead when **K consecutive rounds return nothing new**, deduping against everything seen, not against what survived judging. Dedup against survivors and rejected items reappear forever.

**4. Close with a completeness pass.** The cut is invisible from inside the sweep: an axis you never ran leaves no trace in the results. So the last step asks what is missing, which modality did not run, which claim went unverified, which source went unread. What it returns is the next round, not a footnote.

**And never cap in silence.** If the sweep was bounded (top-N, no retry, sampling, a `head`), the report says so. A truncated sweep reported as total reads as full coverage and is worse than no sweep, because it closes the question. This one has teeth: the Stop gate `claim-verify-stop.py` blocks a reply that asserts total coverage when the turn shows a truncation artifact and the reply never owns the cut. Declaring the cut always passes.

## Tell / anti-pattern

> Fanned out 6 agents, then the main loop re-read all 6 files and rewrote the conclusion itself.

That's an octopus that grew eight arms and then did everything with the head. You paid for parallelism and threw it away. If the center's post-fan-out work looks like the arms' work repeated, you violated this rule.

## See also
- [[4d-paradigm-protocol]] — Delegate (the "who does it" half); this skill is the "fan out to many + reconcile" extension
- [[harmonization-over-accretion]] — restraint on the *what*; this is structure for the *how-many*
- [[runtime-adaptation-over-source-edit]] — sibling octopus↔OS pattern (adapt at the edge, keep the core lean)
- [[orchestrated-planning]] — planning counterpart for multi-agent work

# Octorato Roadmap

> **North star:** a portable OS that runs *any* AI agent under enforced isolation, budgets, and capabilities — so a fleet of agents is as safe to operate as a fleet of Linux processes.

Most "agent frameworks" are libraries you import. Octorato wants to be the **kernel they run on**.

## Where we are today (honest)

Octorato is an **early-stage, research-driven** attempt at an OS-grade runtime for AI agents. What's **real and shipping** right now:

- A persistent **brain** (`~/.claude/`): versioned rules + 160+ agent personas + a growing skill library.
- A **connectome** (TF-IDF + cosine graph over every skill/agent) used for agent selection and gap detection.
- The **4D paradigm** (Describe → Delegate → Diligent → Disclose) with pre-write gates.
- **FinOps with teeth**: per-arm cost rollup *and* a budget cap that fires a **hard `PreToolUse` halt** — most "agent OS" projects have *zero* runtime enforcement; this one stops work when the budget is blown.
- **Arm isolation** (one sealed repo per client) — today enforced by audit (`check-generic.py`), see M2 for the plan to enforce it earlier.

Today Octorato is a strong **governance layer over a host harness**. It is **not yet** a runtime with its own kernel. The roadmap below is the path from "governance layer" to "OS" — sequenced, not scheduled.

## The one decision that gates half of this

Several milestones (concurrency, fault tolerance, init/daemon, *enforced* ABI) all collapse into a single question:

> **Does Octorato adopt/build its own host runtime, or stay a governance layer that compiles to many harnesses (Claude Code, GPT, local models)?**

This is **[RFC #0002](https://github.com/CarlosCaPe/octorato/discussions)** — debated in the open. Everything marked *ready to build* below is valuable under **either** answer, so that's where we start.

## Milestones

v8 (the kernel) shipped in September 2026 and is specified in [docs/architecture/v8-kernel.md](docs/architecture/v8-kernel.md): PROCESS, ISOLATION, JOURNAL and PACKAGE as a contract enforced by hooks, scripts and git, no daemon. It covers M1, the non-money half of M2, the replay half of M3 and the package half of M5; M4 stays future.

v9 (done is a verdict) shipped in October 2026 and is specified in [docs/architecture/v9-done-is-a-verdict.md](docs/architecture/v9-done-is-a-verdict.md). It adds no milestone to the table below; it hardens the governance layer the table rests on. On a large task the agent that wrote the code no longer decides that the work is finished: an independent pass judges every acceptance criterion against the code and tests, and in this repository a spec reaches `converged` in a push only with that pass's receipt. What it cannot enforce is listed in the same document, with the measurement for each.

v10 (low friction, easy entry) is the October 2026 release, <!--canon:v10.release.version-->v10.0.0<!--/canon-->, specified in [docs/specs/202610061605-v10-low-friction-easy-entry/](docs/specs/202610061605-v10-low-friction-easy-entry/feature.md). Like v9 it adds no milestone; it makes the existing checks cheaper to live with and easier to start. Its acceptance criteria are judged by the converge pass in that spec directory, not here. One part of the release criterion is read after the cut: over the first 7 days of friction data after release, the send check's false-positive rate on its labelled sample must stay under <!--canon:v10.release.send_ask_fp_target-->15%<!--/canon-->. `octo friction` prints that rate per check (the "FP rate of labelled denies" column), so the live figure lives there and not in this file.

| Shipped | PR | What you get |
|---|---|---|
| One-command install | #379 | `quickstart.py` wires the Claude Code hooks, sets `core.hooksPath`, runs `brain_doctor --fast` and writes a first spec. A fresh-clone CI job fails the run past <!--canon:v10.quickstart.ci_budget-->5 minutes<!--/canon-->. |
| Friction ledger and replay | #380, #397, #401 | Every refusal is counted from the transcript, `octo friction` reports it per check, and a private replay corpus of <!--canon:v10.replay.cases-->1,841<!--/canon--> real cases blocks a change that drops a refusal that was right. Each Stop is counted once across session files, and `replay` prints how many cases ran stateful or isolated. |
| Send check reads the ask | #382, #389 | "send it" counts in English or Spanish; a plain read of the support script is not a send. |
| Fewer false Stop blocks | #385 | goal-anchor, wa-guardia, delegation-audit, claim-verify and secrets-grep tuned, each with a replay or reconstruction result. |
| Faster budget check | #383, #408 | The check answers from a spend cache: <!--canon:v10.budget.spawn_after-->85 to 254 ms<!--/canon--> median per call with a warm cache, down from <!--canon:v10.budget.spawn_before-->7.2 s<!--/canon--> per spawn. A cache up to <!--canon:v10.budget.stale_window-->15 minutes<!--/canon--> old is fresh; one from this month up to <!--canon:v10.budget.stale_max-->24 hours<!--/canon--> old answers at once and refreshes in the background. Before #408 that stale cache was recomputed on the spot: a ledger read on 2026-10-07 counted <!--canon:v10.budget.live_timeouts-->9 (12%)<!--/canon--> of <!--canon:v10.budget.live_calls-->73<!--/canon--> live calls at the <!--canon:v10.budget.hook_timeout-->10 s<!--/canon--> hook timeout, each one a recompute of <!--canon:v10.budget.recompute_time-->about 24 s<!--/canon--> that could not finish in time. |
| A visible brain | #378 | `octo dash` writes one offline HTML page; a status line shows the gate receipt, live processes and the active spec. |
| Shorter constitution | #392, #395, #400 | `CLAUDE.md` went from <!--canon:v10.constitution.tokens_before-->25,506<!--/canon--> to <!--canon:v10.constitution.tokens_after-->11,551<!--/canon--> tokens by the health check's own estimator (a per-piece bound that stays above the tokenizer's count), English only, and `brain_doctor` fails it above <!--canon:v10.constitution.ceiling-->12,000<!--/canon-->. |
| Re-review after a base update | #391, #395, #401 | `/requa <pr>` checks that a pull request changed only by merging master and records a QA receipt for the new head; it reads the patch with git's text filters off, so a configured textconv cannot hide a binary swap. `ai-pull` runs the fast doctor and re-proves the gates only when they changed (one sandbox run of the full doctor took <!--canon:v10.doctor.full-->344 s<!--/canon-->). |
| Goal-anchor read receipts | #398 | The goal-anchor check writes one receipt line per Stop (where it stopped reading, a digest of the reply it judged, its decision; no text), so the friction ledger and the replay cut each Stop where the gate did. |
| A SELF verdict demands the live source | #406 | `delegate-check` prints, on every SELF verdict, a line that calls the answer about 99% likely stale or hallucinated and asks for the live source checked before answering; its selftest fails when the line is removed. |
| Fewer goal-anchor blocks | #411 | A closed root is retired; a steer, an ack or an obstacle report never anchors; a goal-shaped prompt (5 or more content words with a task verb) anchors after a close or as the first root; a mention counts by whole words. Like for like, the gate before v10 against this one on the same <!--canon:v10.goal_anchor.stops-->2,974<!--/canon--> Stops of <!--canon:v10.goal_anchor.sessions-->35<!--/canon--> recorded sessions: <!--canon:v10.goal_anchor.raw-->220 to 38<!--/canon--> blocks (<!--canon:v10.goal_anchor.measured-->17.3%<!--/canon-->), <!--canon:v10.goal_anchor.per_case-->51 to 7 (13.7%)<!--/canon--> per case, against a target of at most <!--canon:v10.goal_anchor.target-->25%<!--/canon-->. The replay reproduces <!--canon:v10.goal_anchor.receipt_fidelity-->99.3%<!--/canon--> of the <!--canon:v10.goal_anchor.receipt_stops-->146<!--/canon--> Stops the check recorded a read receipt for; `octo friction` carries the live count forward. Residual: a goal of 3 or 4 words anchors only through the topic streak, and the task-verb list is the filter. |
| Goal-anchor fidelity rated on receipts | #414 | The replay rates the goal-anchor check on the Stops it wrote a read receipt for: <!--canon:v10.goal_anchor.receipt_fidelity-->99.3%<!--/canon--> of <!--canon:v10.goal_anchor.receipt_stops-->146<!--/canon--> reproduced (floor 100 Stops and 90%), history before the receipts reported but no longer deciding the mark, and the gate's <!--canon:v10.goal_anchor.fixture_tp-->12 of 12<!--/canon--> fixture violation legs standing in as labelled true positives while the corpus holds none (AC-10 amended, AC-25 added). |

The table has not been re-graded since v8 shipped: the cells v8 covers (M1, parts of M2, M3 and M5) still show the status they had before it. v10's friction ledger and replay harness add to M3 without changing its grade.

| Milestone | Theme | Maturity | Gaps |
|-----------|-------|----------|------|
| **M1 — The Kernel Boundary** | Define what the OS *is* — the contract everything plugs into | `status: design` | Kernel/syscall ABI · model/harness portability · capability + identity |
| **M2 — Isolation & Resource Control** | Make the boundary actually *enforce* limits (not just $) | `status: design` (partly in progress) | Kernel-enforced arm isolation · non-$ quotas (time/rate/compute) · uniform tool-driver model |
| **M3 — Observability First** | See what your agents did and why | `status: in progress` | Replayable decision journal + trace schema + tracing |
| **M4 — Concurrency & Messaging** | Run many agents at once, safely, with recovery | `status: future` | Scheduler/process model · IPC/message bus · fault tolerance/checkpoint |
| **M5 — Distribution** | Package, install, and boot agents like services | `status: future` | Signed/semver package manager + registry · init/service manager |

M3 is pulled forward on purpose: it's low-dependency, immediately useful, and the best on-ramp for new contributors.

## How to contribute

- New here? Read **[Start Here — Contributing](https://github.com/CarlosCaPe/octorato/issues)** and filter issues by [`good first issue`](https://github.com/CarlosCaPe/octorato/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
- Want to shape the architecture? Weigh in on the RFCs in **[Discussions → Ideas](https://github.com/CarlosCaPe/octorato/discussions)**.
- We ship enforcement, not promises — and we're explicit about what isn't built yet. Dates are never promised on M4/M5: **sequenced, not scheduled.**

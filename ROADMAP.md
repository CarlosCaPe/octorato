# Octorato Roadmap

> **North star:** a portable OS that runs *any* AI agent under enforced isolation, budgets, and capabilities — so a fleet of agents is as safe to operate as a fleet of Linux processes.

Most "agent frameworks" are libraries you import. Octorato wants to be the **kernel they run on**.

## Where we are today (honest)

Octorato is an **early-stage, research-driven** attempt at an OS-grade runtime for AI agents. What's **real and shipping** right now:

- A persistent **brain** (`~/.claude/`): versioned rules + 160+ agent personas + a growing skill library.
- A **connectome** (TF-IDF + cosine graph over every skill/agent) used for agent selection and gap detection.
- The **4D paradigm** (Describe → Delegate → Diligent → Disclose) with pre-write gates.
- **FinOps with teeth**: per-arm cost rollup *and* a budget cap that fires a **hard `PreToolUse` halt** — most "agent OS" projects have *zero* runtime enforcement; this one stops work when the budget is blown.
- **Arm isolation** (one sealed repo per client), enforced at write time since v8: one writer per tree and per file lane, and a write into another arm is denied naming the process that holds it (`g__pretool-write__tree-owner.py`, `g__pretool-bash__tree-owner.py`); `check-generic.py` still audits what gets committed.
- **The v8 kernel** (shipped 2026-09-17, [docs/architecture/v8-kernel.md](docs/architecture/v8-kernel.md)): every run has a process record with a pid, parent, worktree, quota and exit status; an append-only, hash-chained journal per process that replays and verifies (`octo replay --verify`); per-process quotas enforced at the tool boundary; and signed semver skill packages with a tracked lockfile, verified by the doctor and at push time.

Today Octorato is a **kernel contract enforced over a host harness**: PROCESS, ISOLATION, JOURNAL and PACKAGE are hooks, scripts and git, not prose. It is **not yet** a runtime of its own: it cannot kill, suspend or signal a running agent, and it does not schedule (both stay in M4). The roadmap below is the path from that contract to an OS: sequenced, not scheduled.

## The one decision that gates half of this

Several milestones (concurrency, fault tolerance, init/daemon, *enforced* ABI) all collapse into a single question:

> **Does Octorato adopt/build its own host runtime, or stay a governance layer that compiles to many harnesses (Claude Code, GPT, local models)?**

This is **[RFC #0002](https://github.com/CarlosCaPe/octorato/discussions)** — debated in the open. Everything marked *ready to build* below is valuable under **either** answer, so that's where we start.

## Milestones

**v8.0.0 "The Kernel" shipped on 2026-09-17** ([release](https://github.com/CarlosCaPe/octorato/releases/tag/v8.0.0), design in [docs/architecture/v8-kernel.md](docs/architecture/v8-kernel.md)): PROCESS, ISOLATION, JOURNAL and PACKAGE as a contract enforced by hooks, scripts and git, no daemon. It closed M1, the non-money half of M2, the replay half of M3 and the package half of M5. M4 stays future.

| Milestone | Theme | Maturity | Gaps |
|-----------|-------|----------|------|
| **M1 — The Kernel Boundary** | Define what the OS *is* — the contract everything plugs into | `status: shipped` (v8.0.0) | Contract is live as four primitives; model/harness portability continues per binding row ([multi-runtime](docs/architecture/multi-runtime.md)) |
| **M2 — Isolation & Resource Control** | Make the boundary actually *enforce* limits (not just $) | `status: in progress` (isolation + quotas shipped in v8) | Uniform tool-driver model · compute quotas beyond tool calls and minutes |
| **M3 — Observability First** | See what your agents did and why | `status: in progress` (replayable journal shipped in v8) | Trace schema + tracing across processes |
| **M4 — Concurrency & Messaging** | Run many agents at once, safely, with recovery | `status: future` | Scheduler/process model · IPC/message bus · fault tolerance/checkpoint |
| **M5 — Distribution** | Package, install, and boot agents like services | `status: in progress` (signed semver packages + lockfile shipped in v8) | Hosted package index · dependency resolution · init/service manager |

M3 is pulled forward on purpose: it's low-dependency, immediately useful, and the best on-ramp for new contributors.

## How to contribute

- New here? Read **[Start Here — Contributing](https://github.com/CarlosCaPe/octorato/issues)** and filter issues by [`good first issue`](https://github.com/CarlosCaPe/octorato/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
- Want to shape the architecture? Weigh in on the RFCs in **[Discussions → Ideas](https://github.com/CarlosCaPe/octorato/discussions)**.
- We ship enforcement, not promises — and we're explicit about what isn't built yet. Dates are never promised on M4/M5: **sequenced, not scheduled.**

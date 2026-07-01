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

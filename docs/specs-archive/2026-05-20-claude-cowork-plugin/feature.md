---
title: Claude Cowork integration — architectural shape
status: design-shipped / enforcement-deferred
date: 2026-05-20
slug: claude-cowork-plugin
archived-on: 2026-05-20
---

# Claude Cowork — how it fits the Octopus

## TL;DR

**Claude Cowork integrates as a quarantined pseudo-arm called `cowork-shared`, not as a per-client brazo.** The shape is decided. The enforcement code is deferred until Anthropic publishes Cowork's session-event API surface (no public webhook / hook / JSONL stream exists at time of this spec).

## Why this needs a spec at all

The octopus model has one sacred invariant: **arms never see each other** (CLAUDE.md → "Arm Isolation (MANDATORY)"). Every other rule cascades from that. Per-client cost attribution, the FinOps pipeline, and the legal posture toward client data all depend on the boundary being airtight.

Cowork breaks the assumptions the brain has about session topology:

| Octopus assumption | Cowork reality | Risk |
|---|---|---|
| 1 human per session | Multiple humans in a shared session | Whose budget burns? |
| Session anchored at a local cwd → maps to one arm | Session runs in Anthropic's hosted environment, no cwd | Cost can't be attributed by path |
| Tool calls happen on the operator's filesystem | Tool calls happen in a shared sandbox | Two collaborators with different client contexts could mix data |

If we let Cowork mount client arm directories the way Claude Code does, we get a clean way to violate arm isolation in production. That's the failure mode this spec exists to prevent.

## The shape

Cowork is a **distribution channel for the brain itself**, not a new way to do client work.

Concretely:

1. **Cowork sessions are a synthetic pseudo-arm** named `cowork-shared`. Anything happening inside a Cowork session is tagged with that arm, never with a real client.
2. **Cowork sessions never mount a client arm directory.** A `PreToolUse` guardrail refuses `Read` / `Write` / `Edit` on any path under `~/Documents/github/<arm>/` when the session is marked Cowork. The guardrail is permissive only inside `~/.claude/` (the brain itself) and `~/Documents/github/octorato/` (the public framework).
3. **Cost attribution.** Cowork billed cost shows up in the Admin API `usage_report` (already ingested by `scripts/anthropic-analytics-pull.py`). `brain-digest.py` groups any rows where the source indicates a Cowork session into the `cowork-shared` arm line. No client gets billed for Cowork.
4. **Use case.** Operators collaborating with peers (or with paying clients of the *brain product*, not arm clients) to write skills, review agents, sketch frameworks. Anything that should be public-ish or framework-level. Not client deliverables.

## Why this honors the octopus, not breaks it

A normal arm is a sealed client repo. `cowork-shared` is a sealed *brain-only* session — it sits at the same logical level as an arm but its contents are framework, not client. Arm isolation is preserved because the guardrail makes "mount client A in a Cowork session" mechanically impossible. The pulpo gains a ninth tentacle that only ever touches its own head, never reaches into the other eight.

## What is shipped today

- This spec (the design)
- The naming convention (`cowork-shared`)
- The contract that `anthropic-analytics-pull.py` is the authoritative source of Cowork cost (already true — Admin API rows surface Cowork usage regardless of whether we explicitly parse them)
- README + LinkedIn launch drafts updated to reflect: design done, enforcement waiting on vendor

## What is deferred

- `scripts/cowork-quarantine-hook.py` — the PreToolUse guardrail. Cannot be wired without knowing Anthropic's Cowork session-event format (env var? webhook? JSONL? unknown).
- `skills/claude-cowork-plugin/SKILL.md` — operator setup guide. Written once we have a concrete surface to integrate against.
- `brain-digest.py` explicit `cowork-shared` line. Currently Cowork rows land in the Admin reconciliation block; an explicit per-arm line is a small follow-up once we confirm how the Admin API tags them.

## Why "first paying client" was always the wrong gate

The original roadmap entry said "*gated on first-paying-client validation of the integration shape*". That framing was a deflection. The integration shape is an **architectural** question — does Cowork get to mount arm directories? — not a **commercial** one. Waiting for a paying client to answer it was a way to avoid making the call. This spec makes the call.

The real gate is and always was: **Anthropic publishes the Cowork session-event surface**. When they do, the deferred work above ships in a single PR.

## Out of scope

- Cowork-specific pricing (lives in `_pricing.py` once Anthropic publishes Cowork's billing tier — until then the Admin API delivers actuals so list-price math isn't needed).
- Multi-tenant Cowork (different operator orgs sharing one Cowork session). Not a real use case for the brain.
- Cowork plug-ins / extensions on the Anthropic side. We are not building inside Cowork; we are building the boundary around it.

## Legal / copyright

- Spec is part of the public octorato brain → AGPL/MIT per file rules apply. This file is MIT.
- References to "Claude Cowork" are nominative use of Anthropic's product name — no endorsement implied. Anthropic ToS for Cowork governs operator's use of the product; this spec governs only how *our brain* behaves around it.
- No client data, vendor incidents, or non-public Anthropic information appears in this doc.

## Pointers

- Roadmap line: `~/.claude/README.md` → "FinOps roadmap"
- Cost ingest: `~/.claude/scripts/anthropic-analytics-pull.py`
- Digest renderer: `~/.claude/scripts/brain-digest.py` → `section_anthropic_reconciliation()`
- Arm isolation rule: `~/.claude/CLAUDE.md` → "Core Principles → 1. Arm Isolation"

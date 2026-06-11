# Memory Model — two-tier, ship the engine not the data

Octorato's memory is split by **scope**, and scope decides **location**. The public
framework ships the *mechanism*; your memories are *data* and stay private — the
SQLite rule (the engine is open source, your `.db` is yours).

Decided by a 4-specialist panel (Software Architect · Security Engineer · Backend
Architect · Product) — unanimous on the design below. But the real authority isn't
the panel; it's the animal.

## Foundation — the octopus has nine brains

An octopus has ~500M neurons and **one central brain + eight arm brains** — and
**~2/3 of those neurons live in the arms**, not the center. Each arm senses,
processes, and acts semi-autonomously; the central brain sets intent and
coordinates, it does not micromanage each arm.

So the two-tier memory model is **not a design choice — it's the neuroanatomy**:

- **1 central brain → brain memory** (`octorato-memory`): identity + generic
  cross-arm lessons. "Who you are."
- **8 arm brains → per-arm memory**: each arm remembers its own client, sealed and
  semi-autonomous. "What this project taught you."
- **2/3 of neurons in the arms** → most operational knowledge is *arm-local*; the
  central brain (and the public framework that ships it) stays lean and generic.
- **the center doesn't micromanage** → arm isolation: the brain never reaches into
  an arm's local memory.

Corollary that kills the tempting shortcut: putting brain memory *inside an arm* is
trying to cram the central brain into one tentacle. Anatomically impossible — the
arm already has its own brain, the center has its own. A standalone brain-owned
memory repo is the only morphologically correct shape.

## How memory rises: the immune system

The octopus says *where* memory lives. It doesn't say *how* an arm's lesson becomes a generic brain memory, and biologically it can't (octopus arms don't consolidate learning upward). That mechanism has a different right model: the **immune system**.

- **Clonal selection** = a local encounter triggers learning. An arm hits a specific problem; solving it is the antigen encounter.
- **Memory cells** = the lesson becomes durable and body-wide. A generic skill or lesson is promoted to the central brain, available to every future arm, the way memory B and T cells make the whole body faster next time.
- **Store the pattern, not the antigen.** Immune memory keeps the generalized receptor, never a copy of the pathogen. That is the distil-upward rule exactly: the *generic* lesson rises; the arm's *specific* data stays sealed and never travels. The seal and the upward path are the same invariant seen from two angles.

Octopus = the spatial layer (1 + N sealed brains). Immune system = the learning layer (local to durable generic, pattern up, specifics sealed).

## The two tiers

| Tier | What it holds | Where it lives | Syncs to |
|---|---|---|---|
| **Brain memory** | "who you are" — operator identity, preferences, **generic cross-arm lessons** | the brain's gitignored `projects/<id>/memory/` as its **own nested `.git`** | a **private, standalone, brain-owned** repo (e.g. `octorato-memory`) |
| **Arm memory** | "what this project taught you" — one client's schema quirks, deploy gotchas, stakeholders | inside **that arm's own repo** (`<arm>/.claude/memory/`), sealed | the arm's own remote |

Routing rule (so the split is enforceable, not aspirational):
**Would this lesson help a *different* client?** Yes → distill to generic → brain memory. No → arm memory. Unsure → arm memory (default-deny). This is Upward Learning applied to memory.

## Why not the obvious shortcuts

- **Memory inside an arm** — inverts the morphology: the brain would *depend on a
  client repo* to remember itself, and generic cross-arm lessons would physically
  sit in one client's tree (isolation breach). A sync channel into one arm also
  leaks *future* lessons distilled from *other* arms into it — you'd be validating
  a snapshot, not the channel.
- **Memory as a submodule/branch of the public repo** — a submodule URL is a public
  string and one wrong-branch push publishes operator PII to forever-history. The
  whole "brain stays generic" rule forbids any private byte sharing the public `.git`.
- **Local-only, never synced** — not wrong, just the *floor*: zero multi-machine
  continuity. It's the correct zero-config default, not the target.

## What is public vs private

| Public (ships in `octorato`) | Private (never in the public repo) |
|---|---|
| `scripts/memory_sync.py` (the engine) | the actual memory `*.md` (behind the nested `.git`) |
| this doc + `templates/memory/MEMORY.template.md` | the private remote URL (in gitignored `company/config/memory.json`) |
| the format + `MEMORY.md` index convention + recall hook | operator identity, preferences, lessons |

The public repo knows the **slot**, never the **occupant** — the remote URL is read
from gitignored `company/config/memory.json`, never hardcoded (same precedent as
`arms-paths.json` and the derived git remote).

## Adopter onboarding (activate, don't implement)

1. **Clone → memory works local-only.** Recall hook live, writes land in the
   gitignored memory dir. Zero config, zero new repo, zero leak risk.
2. **Opt in to cross-machine sync:** create a **private** repo, write its URL into
   `company/config/memory.json` (`brain_memory.remote` + `path`), then run
   `python3 scripts/memory_sync.py push`. The script `git init`s the nested repo on
   first run and pushes. No config → it soft-fails back to local-only.

```bash
python3 scripts/memory_sync.py status   # show config + nested-repo state
python3 scripts/memory_sync.py push     # pull --rebase, commit, push
python3 scripts/memory_sync.py pull     # refresh on a new machine
```

One-line mental model: **brain memory is who you are; arm memory is what this
project taught you — and the framework ships the machinery empty, so your data
never rides anyone's public history.**

# Octorato Wiki

> **The open-source AI Agent Operating System.** One human operator. A shared brain of specialist agents. Many clients, projects, and machines — never mixing their data or their bills.

Welcome to the official wiki for [**Octorato**](https://github.com/CarlosCaPe/octorato). If you have five minutes, this page tells you what Octorato is, why it exists, and where to go next. If you have thirty seconds, read the box above and jump to [Start here](#start-here).

---

## What Octorato is

Octorato is a **brain** — a file-based "self" that lives in `~/.claude/` and survives across sessions, machines, and clients. It is the persistent operating system a single operator uses to direct a team of AI specialists with nothing but natural language: build software, ship it, and bill the client honestly when it does.

The name encodes the two ideas the architecture is built on:

- **Octopus** — an octopus keeps roughly two-thirds of its neurons in its *arms*, not its central brain. Each arm acts with local intelligence while the central brain sets intent. Octorato copies that shape: a generic central brain coordinates many semi-autonomous **arms** (one sealed workspace per client). The brain distributes knowledge downward; arms send lessons upward; **arms never see each other.** Rotate the 8 arms sideways and you get ∞ — the engineering claim is *unbounded* sealed tenancy with no ceiling.
- **Tesseract** — the **4D Paradigm** (Describe → Delegate → Diligent → Disclose) is named for the 4-dimensional analog of a cube. The four phases are not sequential steps but *dimensions* active in every action. It is the control plane, not a checklist.

The practical problem this solves is the one a solo consultant or small agency actually faces: **one consciousness, many client workspaces, no cross-contamination — and a defensible answer to "what did this client's work cost?"** Octorato tags every trace event with the client who incurred it, rolls it up to USD per arm, and can halt an agent when a budget cap is burned. The biology is the metaphor; per-client FinOps and air-gapped isolation are the product.

> Full naming rationale: [`skills/octorato-symbolism/SKILL.md`](https://github.com/CarlosCaPe/octorato/blob/master/skills/octorato-symbolism/SKILL.md). See also [[Glossary]] and [[Architecture]].

---

## The north star

**Keep the brain current with a market that moves faster than any one person can read — and grow it from its own logs and the operator's hand-written skills.**

The AI race is brutal. A stale brain is dead weight: models, tools, and pricing primitives shift weekly, and a knowledge base frozen at last quarter quietly stops being an asset and starts being a liability. Octorato treats currency as a first-class, automated mandate, growing along two axes:

1. **Outward (market intake).** A daily scheduled loop scans GitHub Trending, Hacker News, and Product Hunt, runs each candidate through a deterministic brain-fit classifier plus an LLM quality gate, dedupes against the existing connectome, and **auto-promotes** the survivors into real skills — crediting the source and publishing what it learned to a public audit ledger. The point is *harmonization, not accretion*: the brain is a connected graph, not a junk drawer of skills. See [[Self-Growth]].
2. **Inward (self-reflection).** Trace logs feed a cost-and-quality digest; failed tasks subtract from connectome edge weights; hand-written skills born from arm patterns are anonymized and distributed to every arm. The brain learns from what it did and from what the operator deliberately taught it.

No daily human gatekeeping is required — the operator audits the ledger on their own cadence rather than approving every item. That is the only way a one-person brain keeps pace with the industry.

---

## Live stats

| Dimension | Count | What it is |
|---|---:|---|
| **Skills** (synapses) | **189** | Reusable techniques — loaded on demand, born from arms, decay when stale |
| **Agent personas** (neurons) | **162** | Specialist processors with persona, expertise, and voice |
| **Divisions** | **13** | Engineering, Design, Marketing, Sales, Product, Project Mgmt, Testing, Support, Specialized, Spatial Computing, Game Dev, Academic, Paid Media (+ 2 reference dirs) |
| **Enforcement scripts** | **8** | Delegate-check, gate-check, budget-check, connectome query, and the rest of the guardrails |
| **Multi-machine sync** | — | `ai-push` / `ai-pull` keep the brain identical across every workstation |
| **Neural connectome** | — | TF-IDF + cosine-similarity graph over every skill and agent; rebuilt on every push |
| **FinOps pipeline** | — | Per-arm token attribution → USD rollup → cost-spike watchdog → budget caps that halt agents |

> Counts grow as the brain learns. The numbers above are a snapshot; query the connectome live with `python3 ~/.claude/scripts/query_connectome.py stats`.

---

## Start here

New to Octorato? Read these pages in roughly this order. Veterans can jump straight to the reference pages at the bottom.

### Understand the model
- **[[Architecture]]** — the CLASS / OBJECT / ARM inheritance model: the generic brain, your private company instance, and your sealed client arms.
- **[[The-4D-Paradigm]]** — the nervous-system protocol every action follows, including the Change Gate and the 3 Mandatory Questions.
- **[[Glossary]]** — every term in one place: arm, connectome, synapse, god node, Hebbian boost, Impact Radius.

### Get running
- **[[Getting-Started]]** — clone the brain, create your private company brain, stand up your first arm, sync across machines.
- **[[Arms-and-Sync]]** — how client arms stay isolated, how knowledge flows up and down (never sideways), and how `ai-push` / `ai-pull` work.

### Work with the building blocks
- **[[Agents]]** — the 162 personas across 13 divisions: who they are and what they do.
- **[[Agents-System]]** — how agents are selected, activated, and combined with skills and arm context.
- **[[Skills]]** — the 189 reusable techniques and how they cluster into synaptic families.
- **[[Skills-System]]** — how a skill fires: similarity search, rule match, load-into-context, then reinforce or decay.

### Run it like a business
- **[[Self-Growth]]** — the daily discovery loop, the brain-fit classifier, and how the brain keeps itself current.
- **[[FinOps]]** — per-client cost attribution, USD rollups, cost-spike alerts, and budget caps that actually stop agents.
- **[[Security]]** — the "brain stays generic" rule, the two-layer commit/push enforcement, and how secrets and client data never leak.

---

## Quick Start

```bash
# 1. Clone the brain into ~/.claude (it IS the octorato repo)
git clone https://github.com/CarlosCaPe/octorato.git ~/.claude

# 2. Enable the push-time generic-content guardrail
git -C ~/.claude config core.hooksPath .githooks

# 3. Create your private company brain (gitignored — never published)
cp -r ~/.claude/templates/company/ ~/.claude/company/
mv ~/.claude/company/COMPANY.md.template ~/.claude/company/COMPANY.md

# 4. Stand up your first sealed client arm
mkdir -p ~/projects/my-client/.claude
cp ~/.claude/templates/arm/CLAUDE.md.template ~/projects/my-client/.claude/CLAUDE.md

# 5. Sync across every workstation
ai-pull
```

Full walkthrough with annotated `{{PLACEHOLDERS}}`: **[[Getting-Started]]**.

---

## Repository

**[github.com/CarlosCaPe/octorato](https://github.com/CarlosCaPe/octorato)** — public, open-source. The brain is published in the open, so it stays strictly generic: no client names, no credentials, no internal data ever enter git history. That discipline is enforced, not aspirational — see [[Security]].

> Octorato is also the open-source AI Agent OS productized at [dataqbs.com](https://dataqbs.com). Repo identity and product identity are the same thing.

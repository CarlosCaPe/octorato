# Octorato — the AI Agent OS that grows itself

> **Organ:** central brain — receives intent from the human, distributes generic knowledge to every arm, and routes you to the organ that handles each concern.

> **Octorato** = *octopus* + *tesseract* — an eight-armed brain in a 4D
> activation space (Agent × Skill × Arm × 4D-phase). Open-source AI-agent
> operating system for a single operator directing a shared brain of specialist
> agents across clients, projects, and machines — without ever mixing their data
> or their bills.

**Live:** <!--canon:skills.count-->230+<!--/canon--> skills · <!--canon:agents.count-->160+<!--/canon--> agent personas across
13 divisions · hook-enforced gates · multi-machine sync · a neural
connectome that learns over time · a FinOps pipeline that tags every trace event
with the client who incurred it.

Repo: https://github.com/CarlosCaPe/octorato

---

## Why this exists

The AI race is brutal and the tooling landscape changes daily. A brain that
isn't current is dead weight. So Octorato **keeps itself current**:

- **Reads the market every day** — a scheduled loop scans GitHub Trending,
  Hacker News, and Product Hunt, filters against what the brain already knows,
  and auto-promotes genuinely-new capabilities into real skills. See
  **[[Self-Growth]]**.
- **Learns from its own work** — session logs + the operator's manual skills
  feed pattern extraction (`skill-creator`), so repeated solutions become
  reusable skills.
- **Publishes what it learns** — every brain change flows to a public `/news`
  changelog and a daily blog, with Facebook syndication. This keeps the operator
  informed *and* drives fresh-content rotation/SEO across all their sites.

The result is a brain that compounds: external market signal + internal
experience → more skills → more leverage.

## Start here

Each page is an organ. This brain routes you to whichever one you need.

1. **[[Architecture]]** — the anatomy atlas: CLASS / OBJECT / ARM, the activation stack, and why an octopus.
2. **[[The-4D-Paradigm]]** — the nervous signal: every action follows Describe → Delegate → Diligent → Disclose.
3. **[[Skills]]** — the synapse catalog: <!--canon:skills.count-->230+<!--/canon--> learned techniques (the *HOW*).
4. **[[Agents]]** — the neuron roster: <!--canon:agents.count-->160+<!--/canon--> specialist personas (the *WHO*).
5. **[[Self-Growth]]** — neurogenesis and pruning: the daily auto-curation loop.
6. **[[Security]]** — the immune system: why the brain stays generic, and how that's enforced.

## Quick start (run the brain yourself)

```bash
# 1. Clone the brain into ~/.claude
git clone https://github.com/CarlosCaPe/octorato ~/.claude

# 2. Enable the push-time secret guard
cd ~/.claude && git config core.hooksPath .githooks

# 3. Create your private company brain (gitignored, never public)
#    and your first client "arm" — see Architecture.
```

---

*This wiki is generated from the live brain. Every skill and agent below is
extracted from `~/.claude/skills/*/SKILL.md` and `agents/REGISTRY.md` — it is
always in sync with what the brain can actually do.*

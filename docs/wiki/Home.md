# Octorato, the AI Agent OS that grows itself

> **Organ:** central brain. It receives what you decide, hands the shared rules to every arm, and routes you to the page that answers your question.

**In one sentence:** Octorato is a folder of plain-text files that gives your AI coding assistant a lasting memory, house rules, and a receipt for everything it does.

**In plain words:**

- It is a folder (`~/.claude`) of rules, how-to guides and role cards. The assistant reads it every time it starts.
- It keeps each client or project in its own sealed folder, so work never leaks from one to another.
- It records every run and can cap how many steps and minutes a run may take (the v8 kernel; caps are opt-in).
- It is not a chatbot and there are no people in it. An "agent" here is a text file describing a role, the way a job description does.
- It is free (MIT) and runs on Claude Code and Cursor today.

**Live:** <!--canon:skills.count-->230+<!--/canon--> skills · <!--canon:agents.count-->160+<!--/canon--> agent personas across
13 divisions · hook-enforced gates · multi-machine sync · an index (the
connectome) that learns which guide fits which task · a cost pipeline that tags
every run with the client who incurred it · a generated capability manifest
([`docs/CAPABILITIES.md`](../CAPABILITIES.md)) that the pre-push gate keeps
fresh so no capability can be silently dropped.

Repo: https://github.com/CarlosCaPe/octorato · Plain-words front page: the repo [README](https://github.com/CarlosCaPe/octorato#readme)

---

## Why this exists

The AI tooling landscape changes daily. A brain that isn't current is dead
weight. So Octorato **keeps itself current**:

- **Reads the market every day.** A scheduled loop scans GitHub Trending,
  Hacker News, and Product Hunt, filters against what the brain already knows,
  and promotes genuinely new capabilities into real skills. See
  **[[Self-Growth]]**.
- **Learns from its own work.** Session logs and the operator's manual skills
  feed pattern extraction (`skill-creator`), so repeated solutions become
  reusable skills.
- **Publishes what it learns.** Every brain change flows to a public `/news`
  changelog and a daily blog. The operator stays informed and the sites get
  fresh content.

The result is a brain that compounds: outside signal plus inside experience,
more skills, more reach.

## Start here

Each page is an organ. This brain routes you to whichever one you need.

1. **[[Architecture]]**: the anatomy atlas. CLASS / OBJECT / ARM, the activation stack, the v8 kernel, and why an octopus.
2. **[[The-4D-Paradigm]]**: the nervous signal. Every action follows Describe → Delegate → Diligent → Disclose.
3. **[[Skills]]**: the synapse catalog, <!--canon:skills.count-->230+<!--/canon--> learned techniques (the *HOW*).
4. **[[Agents]]**: the neuron roster, <!--canon:agents.count-->160+<!--/canon--> specialist personas (the *WHO*).
5. **[[Self-Growth]]**: neurogenesis and pruning, the daily auto-curation loop.
6. **[[Security]]**: the immune system, why the brain stays generic, and how that's enforced.

## Quick start (run the brain yourself)

```bash
# 1. Clone the brain into ~/.claude
git clone https://github.com/CarlosCaPe/octorato ~/.claude

# 2. Enable the push-time secret guard
cd ~/.claude && git config core.hooksPath .githooks

# 3. Create your private company brain (gitignored, never public)
#    and your first client "arm". See Architecture.
```

---

*This wiki is generated from the live brain. Every skill and agent below is
extracted from `~/.claude/skills/*/SKILL.md` and `agents/REGISTRY.md`, so it is
always in sync with what the brain can actually do.*

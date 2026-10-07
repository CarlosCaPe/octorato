<p align="center">
  <img src="https://www.dataqbs.com/banner-octorato.webp?v=3" alt="Octorato, the open-source AI Agent OS" width="100%">
</p>

# Octorato

**A folder of plain-text files that gives your AI coding assistant a lasting memory, house rules, and a receipt for everything it does.**

Free and open source (MIT). Runs on Claude Code and Cursor today. No code to write to start using it.

[![License: MIT](https://img.shields.io/github/license/CarlosCaPe/octorato)](LICENSE)
[![Stars](https://img.shields.io/github/stars/CarlosCaPe/octorato?style=social)](https://github.com/CarlosCaPe/octorato/stargazers)
[![Issues](https://img.shields.io/github/issues/CarlosCaPe/octorato)](https://github.com/CarlosCaPe/octorato/issues)
[![Good first issues](https://img.shields.io/github/issues/CarlosCaPe/octorato/good%20first%20issue?label=good%20first%20issues&color=7057ff)](https://github.com/CarlosCaPe/octorato/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
[![Version](https://img.shields.io/github/v/release/CarlosCaPe/octorato?label=version&color=blueviolet)](https://github.com/CarlosCaPe/octorato/releases)

> 🌍 This README is in English. Running an AI assistant? Ask it to read this page in your language.

## In plain words

- **What it is.** A folder (`~/.claude`) of rules, how-to guides and role descriptions, all plain text. Your AI assistant reads it every time it starts. Today it holds <!--canon:skills.count-->240+<!--/canon--> skills (how-to guides) and <!--canon:agents.count-->160+<!--/canon--> agent personas (role cards).
- **What it fixes.** Out of the box an AI assistant forgets you between sessions and mixes one project with another. With this folder it keeps who you are, how you work, and what it must never do.
- **Who it is for.** Anyone who uses an AI assistant on more than one project or client: freelancers, small agencies, engineers, analysts, students. If you can edit a text file, you can use it.
- **What it is not.** It is not a chatbot, and there are no people inside it. The "agents" are text files that describe a role (a code reviewer, a data engineer, a writer), the way a job description does. The assistant reads the card and works in that role. Octorato itself is a tool, not a person, and it never pretends to be one.
- **What it costs.** Nothing. It is a public git repository you can read, copy and change.

## Before and after

| Without Octorato | With Octorato |
|---|---|
| The assistant starts every session blank. | It starts with your rules, your projects and what it learned last time. |
| Work for client A can leak into client B. | Each client lives in its own sealed folder. Working on one, the assistant cannot see the other. |
| You don't know what the assistant did, or what it cost. | Every run is recorded (on Claude Code; on Cursor, the main session only), and you can cap how many steps and minutes one run may take. Caps are opt-in: with none set, nothing is capped. |
| A rule is a line in a document the assistant may skip. | Every rule is tied to an automatic check. A rule without a check does not count. |

## Try it in 5 minutes

```bash
# 1. Clone the brain
git clone https://github.com/CarlosCaPe/octorato.git ~/.claude

# 2. One command does the rest
python3 ~/.claude/scripts/quickstart.py
```

The second command wires the automatic checks into Claude Code (and into Cursor, when Cursor is installed), turns on the guard that stops a secret from being pushed, runs a quick health check, and writes your first spec. Then open `claude` (or a Cursor Agent session) anywhere and ask it something real.

Your first spec teaches the four ideas you need on day one:

| Idea | What it is |
|---|---|
| Spec | What must be true, one checkable sentence per requirement (`feature.md`). |
| Plan | How you will get there, in steps (`plan.md`). |
| Tasks | The plan's numbered lines. Each one names the requirements it serves. |
| Verdict | A second assistant that did not write the code decides when it is done. |

Everything else (private notes, sealed client folders, syncing several machines) can wait. It is in the [Getting Started](https://github.com/CarlosCaPe/octorato/wiki/Getting-Started) page, under "Going further".

<p align="center"><img src="assets/demo.gif" alt="Terminal demo: brain_doctor checks that every rule is wired to a live mechanism, then the pre-push gate refuses a commit carrying a fake AWS key" width="100%"></p>

<p align="center"><sub><b>Real footage.</b> The health check confirms every rule has a working check behind it, then the push guard refuses a fake AWS key before it can leave the machine.</sub></p>

What changes right away: every answer ends with a receipt (what it used, what it touched, how it checked), and the assistant picks the how-to guide or role that fits the task instead of guessing. Full walkthrough in the [Getting Started](https://github.com/CarlosCaPe/octorato/wiki/Getting-Started) page.

## How it works, in one picture

```
 You (decide)
   │
   ▼
 Brain  ~/.claude/          rules · how-to guides · role cards · memory    shared, public, generic
   │
   ├── Arm: client A/       its own folder, its own facts, sealed          private
   ├── Arm: project B/      sealed
   └── Arm: course C/       sealed
   ▲
 AI assistant (Claude Code, Cursor) reads the brain and works inside one arm at a time
```

Every action follows four steps, and they are checked by hooks, not by good intentions:

1. **Describe.** Say what it will do and why, before doing it.
2. **Delegate.** Look up who already knows (a guide, a role, a data source) before inventing.
3. **Diligent.** Prove it worked: build, test, or show the output.
4. **Disclose.** Say what else was touched, and sign the answer with a receipt.

## The words we use

| Word | Plain meaning |
|---|---|
| Brain | The shared folder of rules and guides, `~/.claude`. Public and generic: no client data in it, ever. |
| Arm | One client, project or topic in its own sealed folder. An arm never knows another arm exists. |
| Skill | A how-to guide the assistant loads when a task needs it. |
| Agent | A role card: a text file describing a job. Not a person. |
| Hook | An automatic check that runs before or after the assistant acts. It can refuse the action. |
| Kernel | New in v8. The part that gives every run an identity, a journal and a cap on steps and minutes. |
| Connectome | An index that finds the right skill or agent for a task. |
| Provenance footer | The receipt at the end of every answer: basis, engine, files touched, how it was verified. |
| 4D | The four steps above. |

**About cost, plainly.** Per-client cost is an estimate from local session logs at list price, attributed by folder. The budget halt is real code, but it arms itself only once you write a `budgets.yaml`. The mechanism is real; the precision is opt-in, and the docs say which is which.

## What's new in v10, "Low Friction, Easy Entry" (in progress, October 2026)

Version 10 keeps every check from v7 to v9 and makes them cheaper to live with. Install is one command after the clone: it wires the checks, turns on the push guard and writes your first spec, in about <!--canon:v10.quickstart.measured-->21 s<!--/canon--> on a clean clone. The checks now count their own refusals, so `octo friction` shows which one said no, how often and how slowly, and a replay of <!--canon:v10.replay.cases-->1,654<!--/canon--> real past cases proves a change did not drop a refusal that was right. The send check reads "send it" in English or Spanish, the budget check per helper fell from <!--canon:v10.budget.spawn_before-->7.2 s<!--/canon--> to <!--canon:v10.budget.spawn_after-->73 to 254 ms<!--/canon-->, and `octo dash` puts specs, reviews and live runs on one page. v10 is not released yet (the latest tag is <!--canon:v10.latest_tag-->v9.13.1<!--/canon-->). The open criterion is AC-10, the goal-anchor check, which still blocks <!--canon:v10.goal_anchor.measured-->42%<!--/canon--> of its old count against a <!--canon:v10.goal_anchor.target-->25%<!--/canon--> target, and the budget check is still slow when its cache is cold (live p95 <!--canon:v10.budget.live_p95-->about 10 s<!--/canon-->). How friction is measured: [docs/architecture/v10-friction.md](docs/architecture/v10-friction.md). What shipped and what is left: the [Roadmap](ROADMAP.md).

## What's new in v9, "Done Is a Verdict" (October 2026)

Until v8, the assistant that wrote the code was also the one that said "done". Version 9 takes that call away from it on large tasks. The requirements are written in a fixed sentence pattern a script can check, a second assistant that did not write the code judges each requirement against the code and the tests, and its verdict is recorded as a receipt. A push of this repository that marks the work as finished is refused without a fresh receipt. The check runs on your machine before a push and is not installed in your other projects; where it can be skipped is listed, with measurements, in [docs/architecture/v9-done-is-a-verdict.md](docs/architecture/v9-done-is-a-verdict.md). Plain summary in the [CHANGELOG](CHANGELOG.md).

## What's new in v8, "The Kernel" (September 2026)

Until v7, Octorato could tell you what the assistant *should* do. Version 8 adds the part that watches each run: every process (a session, or a helper it spawns) gets a record, an append-only journal you can replay line by line, and a cap on how many calls or minutes it may take. Two runs can no longer write over each other's files, and a skill installed with `octo pkg` is checked (manifest, tree hash, signature) before it lands. On Cursor the kernel records the main session only; the gap is stated in the risks section of [docs/architecture/v8-kernel.md](docs/architecture/v8-kernel.md). Plain summary in the [CHANGELOG](CHANGELOG.md); the full contract in [docs/architecture/v8-kernel.md](docs/architecture/v8-kernel.md).

## Built with Octorato

This is not a demo. A few of the products this brain built and keeps running (more in the [showcase](SHOWCASE.md)):

| Product | Live |
|---|---|
| Trilingual site + chatbot that answers from real documents | **[dataqbs.com](https://dataqbs.com)** |
| Multi-Reach: write once, publish to 6 social channels | **[/multi-reach](https://dataqbs.com/multi-reach)** |
| White-label real-estate catalog with daily auto-publish | **[/realestate](https://dataqbs.com/realestate)** |
| Open Garage: commission-free marketplace over WhatsApp | **[/open-garage](https://dataqbs.com/open-garage)** |
| A persona bot that answers as its operator | **[/carloscarrillo](https://dataqbs.com/carloscarrillo)** |
| Daily AI-news blog and curated news page | **[/blog](https://dataqbs.com/blog)** · **[/news](https://www.dataqbs.com/news)** |

## Go deeper

Pick the depth you want. Each level stands on its own.

| Time | Read |
|---|---|
| 2 minutes | [FAQ](FAQ.md): the questions people actually ask, answered plainly. |
| 10 minutes | [Wiki](https://github.com/CarlosCaPe/octorato/wiki): one page per part, starting with [Architecture](https://github.com/CarlosCaPe/octorato/wiki/Architecture). |
| 30 minutes | [The long tour](docs/ANATOMY.md): every part of the brain, the biology behind the names, and why it is shaped this way. |
| Reference | [White paper](WHITEPAPER.md) · [Launch article](https://www.linkedin.com/pulse/introducing-octorato-open-source-finops-brain-ai-agents-dataqbs-trbjc) · [Live page](https://www.dataqbs.com/octorato) · [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md) · [Architecture notes](docs/architecture/) · [Capability manifest](docs/CAPABILITIES.md) |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add a skill or an agent, and how to report an issue. Every contribution must be anonymized: no client data, no personal information. Newcomers are welcome and every contributor is credited. Start with a [good first issue](https://github.com/CarlosCaPe/octorato/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

## License

[MIT](LICENSE)

---

*Created by [dataqbs](https://dataqbs.com), where the productized AI Agent OS runs on this brain.*

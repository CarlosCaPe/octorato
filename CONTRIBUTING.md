# Contributing to the Octopus Brain Framework

Thank you for considering a contribution. This guide explains how to add agents, skills, and improvements.

## Golden Rule: No Personal Data

Every contribution must be **fully anonymized**. No client names, no personal identifiers, no company-specific workflows. The framework is the CLASS — contributions enrich the generic toolbox, not any single company's instance.

Before submitting a PR, verify:
```bash
git diff --cached | grep -i "your-name\|your-company\|client-name"
# Must return empty
```

## Adding a New Agent

1. **Choose a division** from the 13 existing ones (see `agents/REGISTRY.md`)
2. **Create the agent file**: `agents/<division>/<division>-<agent-name>.md`
3. **Follow the format** of existing agents in the same division
4. **Update REGISTRY.md**: Add triggers, cross-reference skills, and division entry
5. **Regenerate the connectome**: `python3 scripts/generate_neural_map.py`

### Agent File Structure

```markdown
# <Agent Name>

## Role
One-sentence description of what this agent does.

## Expertise
- Domain area 1
- Domain area 2

## Triggers
Keywords or task patterns that activate this agent.

## Cross-Reference Skills
Skills this agent commonly loads.

## Workflow
Step-by-step approach this agent follows.

## Deliverables
What this agent produces.
```

## Adding a New Skill

1. **Create the directory**: `skills/<skill-name>/`
2. **Create SKILL.md** using `templates/skill/SKILL.md.template` as a starting point
3. **Include**: Purpose, Triggers, Workflow, Best Practices, Lessons Learned
4. **Regenerate the connectome**: `python3 scripts/generate_neural_map.py`

### Skill Naming Convention

- Use lowercase kebab-case: `explain-analyze-validation`, `dry-run-gate-pattern`
- Be specific: `querymaster-postgresql` not `database-skill`
- Include the technique: `index-creation-concurrently` not `index-stuff`

## Branching Model — PRs Target `test`, Not `master`

The brain uses a **staged-promotion** workflow. Two branches matter:

- **`test`** — the integration / contribution branch. **All pull requests target `test`** — community contributions, day-to-day work, and bot-authored skills alike. Iterate, review, and critique freely here.
- **`master`** — the curated, public canonical. **Promotion-only.** Nobody opens a PR against `master` directly; it advances solely through the weekly `test → master` promotion (see below). It is a protected branch (status checks + linear history).

Why: fewer, deliberate, reviewed updates to the public canonical, and a safe place for community contribution where ideas can be iterated before they become canon.

> **Content exception:** the daily `dataqbs.com` blog/news/metrics feed ships to its **own repo's** `master` daily for SEO freshness. The `test → master` staging applies to the **brain** (skills, agents, rules, docs) — not that content feed.

## Submitting a PR

1. Fork the repository
2. Branch off **`test`** (not `master`): `git checkout test && git pull && git checkout -b feat/add-agent-xyz`
3. Make your changes
4. Run the security scan:
   ```bash
   git diff --cached | grep -iE "password|secret|token|key|@.*\.com"
   # Must return empty
   ```
5. Regenerate the connectome if you added/modified agents or skills
6. **Open the PR against `test`** with a clear description of what you're adding and why

## How Changes Reach `master`

`master` is never written to directly. Once a week the operator runs the `/promote-test` ritual: review the accumulated diff on `test`, then promote `test → master` as one deliberate, reviewed update. Your merged PR ships to the public canonical at that next weekly promotion — not the moment it lands on `test`.

```
contributors ─┐
operator work ─┼──PRs──▶  test  ──weekly /promote-test (reviewed)──▶  master  (protected, public canonical)
bot skills    ─┘
```

### Commit Message Format

```
type(scope): description

Types: feat, fix, docs, chore, refactor
Scopes: agent, skill, script, connectome, template
```

## Reporting Issues

Open an issue on GitHub with:
- What you expected
- What happened
- Steps to reproduce
- Your environment (OS, Claude Code version)

## Code of Conduct

- Be respectful and constructive
- No personal data in any contribution
- Focus on generic, reusable patterns
- Credit sources when adapting from documentation or tutorials

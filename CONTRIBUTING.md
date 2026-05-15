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

## Submitting a PR

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/add-agent-xyz`
3. Make your changes
4. Run the security scan:
   ```bash
   git diff --cached | grep -iE "password|secret|token|key|@.*\.com"
   # Must return empty
   ```
5. Regenerate the connectome if you added/modified agents or skills
6. Submit the PR with a clear description of what you're adding and why

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

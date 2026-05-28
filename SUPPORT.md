# Getting Help with Octorato

Octorato is the open-source AI-agent operating system that powers a real
operator's brain. It is built and maintained by a single operator with
contributions from the community — your patience is appreciated; your
question is welcome.

## Where to ask

Pick the channel that matches the shape of what you need:

| You want to… | Go here |
|---|---|
| **Ask a question, share an idea, or propose an RFC** | [GitHub Discussions](https://github.com/CarlosCaPe/octorato/discussions) |
| **Report a bug or request a feature** | [GitHub Issues](https://github.com/CarlosCaPe/octorato/issues/new/choose) |
| **Suggest a new skill or agent** | [Issue → Skill or Agent Request](https://github.com/CarlosCaPe/octorato/issues/new?template=skill_or_agent_request.md) |
| **Improve the docs / wiki** | [Issue → Documentation](https://github.com/CarlosCaPe/octorato/issues/new?template=documentation.md) or open a PR directly |
| **Find your first contribution** | [Good first issues](https://github.com/CarlosCaPe/octorato/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) |
| **Report a security vulnerability** | **Do not open a public issue.** Email **carlos.carrillo@dataqbs.com** with subject `SECURITY: octorato` — see [SECURITY.md](SECURITY.md) |

## Before you open an issue

A few minutes of due diligence saves everyone time:

1. **Search the repo** — [open issues](https://github.com/CarlosCaPe/octorato/issues) and [closed issues](https://github.com/CarlosCaPe/octorato/issues?q=is%3Aissue+is%3Aclosed). Your question may already be answered.
2. **Check the wiki** — [Architecture](https://github.com/CarlosCaPe/octorato/wiki/Architecture), [Self-Growth](https://github.com/CarlosCaPe/octorato/wiki/Self-Growth), [Skills System](https://github.com/CarlosCaPe/octorato/wiki/Skills-System), [FinOps](https://github.com/CarlosCaPe/octorato/wiki/FinOps).
3. **Read the relevant `SKILL.md`** — every skill in `skills/` documents its own usage and front-matter.
4. **Try `brain_doctor`** — `python3 ~/.claude/scripts/brain_doctor.py` runs 17 read-only health checks if something feels off after install or sync.

## Response expectations

- **Issues and Discussions:** best effort, typically within a week. Maintained by one person with arms in production — no SLA.
- **Security reports:** acknowledged within 72 hours per [SECURITY.md](SECURITY.md).
- **Pull requests:** reviewed by the Claude Code Action automatically on open, then by the operator. The Octorato brain stays generic — see [CONTRIBUTING.md](CONTRIBUTING.md) §"Golden Rule: No Personal Data" before opening a PR.

## Code of Conduct

Participation in any of the above channels is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). The short version: technical critique is welcome; personal critique is not.

## Commercial / paid support

There is no paid support tier. If you want to fund the project, [open an issue tagged `sponsor-interest`](https://github.com/CarlosCaPe/octorato/issues/new) and we can discuss whether GitHub Sponsors makes sense for your use case. The brain itself stays free and open-source either way.

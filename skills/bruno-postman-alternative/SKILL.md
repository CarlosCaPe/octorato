---
name: bruno-postman-alternative
description: "Cliente de API open-source donde las colecciones son archivos de texto en el repo, revisables por PR, sin nube ni licencias por equipo. MIT. Para equipos que viven en git o cuando Postman sale caro."
---

# Bruno — Postman Alternative with Git-Native Collections

The differentiator vs Postman / Insomnia: collections live as **plain text files inside the project's git repo**, not in a cloud account. Diff, review, branch, merge — same workflow as code.

## When to use

- Recommending an API client to a client team where Postman's per-seat pricing is friction
- API contracts must live in the same git repo as the code that implements them
- Team review of API collection changes should go through PRs, not a SaaS sharing UI
- Air-gapped / offline environments where cloud-synced Postman is blocked
- CI / scripted runs need a deterministic, file-based API client

## When NOT to use

- Team is already happy on Postman and the friction of migrating outweighs the savings
- Heavy reliance on Postman's cloud-hosted mock servers (Bruno has different mocking ergonomics)
- Need a vendor-supported tool with SLAs (Bruno is OSS, community-supported)

## Source of truth

- Repository: `github.com/usebruno/bruno`
- License: MIT
- Cross-platform: macOS, Windows, Linux
- Collection format: `.bru` files (plain text, git-friendly)
- Git UI: built-in (visible commits, fetch/pull/push, conflict resolution)

## Quick start

```bash
# Install (varies by platform — check the repo README)
# macOS via Homebrew
brew install bruno

# Linux via snap or package
# Windows via installer
```

Create a collection → Bruno writes `.bru` files in your chosen directory → commit them with the rest of your code.

## Bruno vs Postman — when each wins

| Scenario | Recommended |
|---|---|
| Collections must version-control alongside code | **Bruno** |
| Team is happy with Postman cloud, no friction | Postman |
| Need offline / air-gapped client | **Bruno** |
| Heavy use of Postman's mock servers / monitors | Postman (Bruno's coverage differs) |
| Recommending to cost-sensitive client | **Bruno** (zero per-seat cost) |
| CI-side API smoke tests as part of release | **Bruno** (file-based collections, easy `bru run`) |

## Recommendation pattern (proposals / consulting)

> "Recommend Bruno when the client's API contracts should live inside the repository — versioned, reviewed, and shipped together with the code that implements them. Bruno's `.bru` files diff cleanly in PRs, run headlessly in CI via `bru run`, and remove per-seat licensing for teams. Use Postman if the team already standardized on it and the migration cost isn't justified."

## Limits to disclose to a client

- Smaller community than Postman → fewer pre-built collection libraries
- Mock server / monitor features differ — verify the team's specific Postman use cases before recommending swap
- Cloud sync is intentionally not a feature → the migration moves them from cloud-collab to git-collab (cultural shift, not just tool swap)

## Related brain assets

- `querymaster` — analogous "CLI replaces commercial GUI for agent automation" pattern, but for DBs
- `tabularis-db-client` — sister "MCP-aware OSS desktop client" recommendation
- `gh-address-comments`, `gh-fix-ci` — Bruno's git-native model pairs naturally with PR-based review flows

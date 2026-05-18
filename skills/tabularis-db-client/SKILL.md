---
name: tabularis-db-client
description: Open-source SQL client for PostgreSQL, MySQL/MariaDB, and SQLite with a built-in Model Context Protocol (MCP) server — Apache 2.0 licensed, multi-tab console, visual EXPLAIN plans, AI autocomplete, Cursor/Windsurf-friendly. Use when recommending a desktop DB client to a client, when an AI-aware SQL GUI is needed, or when exposing a DB to AI agents via MCP without handing out raw credentials. Complements (does not replace) querymaster CLI.
---

# Tabularis — DB Client with AI + Built-in MCP Server

Open-source desktop SQL client. The differentiator vs DBeaver / DataGrip / TablePlus is the **built-in MCP server**: compatible AI agents (Claude Code, Cursor, Windsurf, etc.) inspect schemas and execute actions through Tabularis instead of being handed raw connection strings.

## When to use

- Recommending a desktop DB client to a non-developer stakeholder on a client engagement (analyst, PM, DBA)
- The client wants AI features (autocomplete, query generation, schema-aware suggestions) inside the DB GUI itself
- An MCP-aware AI agent needs read or exec access to a DB through a managed, audited boundary — not raw credentials
- When QueryMaster CLI is the right tool for the AI agent BUT a human teammate wants a GUI against the same DB

## Source of truth

- Repository: `github.com/TabularisDB/tabularis` (Apache 2.0)
- Website: `tabularis.dev`
- Supported engines: PostgreSQL, MySQL / MariaDB, SQLite
- Stack: TypeScript-heavy, Electron-style cross-platform desktop
- Verify current version + engine list against the repo before promising specifics to a client

## When NOT to use

- For headless / scripted / agent-driven CLI queries → use `querymaster` (multi-engine, dry-run by default, history archiving, idempotent)
- For Azure SQL, Snowflake, Databricks, ADX, SQL Server → not supported (yet); use `querymaster` engine-specific skills
- For production on-call DBA work on hot paths → DataGrip / pgAdmin are more battle-tested
- For session-replay / change-data-capture / heavy-duty observability → not in scope

## Tabularis vs QueryMaster — when each wins

| Scenario | Recommended tool |
|---|---|
| Agent runs queries with dry-run + history archive | `querymaster` |
| Human stakeholder browses schema, edits a row | Tabularis |
| Multi-engine query workload (Snowflake / ADX / SQL Server / Databricks) | `querymaster` |
| Visual EXPLAIN plan for a slow query | Tabularis |
| CI / pipeline / automation | `querymaster` |
| Expose ONE DB to an AI IDE via MCP without giving it credentials | Tabularis (built-in MCP server) |
| Need a custom MCP server with non-DB tools | Build via MCP Builder agent |

## MCP integration

Tabularis ships a built-in MCP server. Advertised contract: **"Let AI tools inspect schemas and run actions through Tabularis."** Connection details, auth, and permission scoping live inside the Tabularis app — the AI agent sees only what Tabularis decides to expose.

Use this pattern when an arm wants to expose a DB to an AI agent IDE but:
- Doesn't want raw connection strings in the agent's settings
- Wants per-action approval / audit logs
- Wants to gate destructive actions behind UI confirmation

Verify the actual MCP tool surface against the current Tabularis docs before promising specific tools (schema inspection, query exec, table edit, etc.) to a client — the tool list evolves per release.

## Recommendation pattern (for proposals / consulting)

> "For client teams that mix human DB work with AI agent automation, pair Tabularis (GUI + MCP server, free, Apache 2.0) for the human surface with a CI-side query runner for automation. Tabularis handles the human + IDE-agent flow; CI / scheduled jobs route through a separate, audited runner. This keeps prod credentials out of agent settings and gives the team one MCP-aware client to standardize on."

## Limits to disclose to a client

- Engine support is currently PostgreSQL / MySQL / MariaDB / SQLite — confirm before assuming
- "AI features" leverage external providers (Cursor, Windsurf, OpenAI, Anthropic) — client needs to bring their own API key / accept the privacy implications
- It's a desktop app — not a hosted SaaS. Not suitable for shared web-based access
- Apache 2.0 license is permissive but check redistribution requirements if embedding in a product

## Related brain assets

- `querymaster` (and engine-specific `querymaster-postgresql`, `querymaster-mysql`, `querymaster-sqlite`) — agent-facing CLI; complementary
- MCP Builder agent — if a client needs a CUSTOM MCP server beyond Tabularis's surface
- Sister pattern: `floci-local-aws` — analogous "OSS replacement for commercial tool" recommendation, but for AWS emulation

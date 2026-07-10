# Skill: MCP Stack Setup for Octopus Arms

## Purpose
Install and configure the full MCP stack for any Octopus arm, respecting Arm Isolation rules:
- **Cloud MCPs** → `user` scope (OAuth per Claude account, shared brain, never per-client)
- **Database MCPs** → `arm` scope (`.mcp.json` inside client repo, per-client credentials)

## Triggers
- "setup MCP for [CLIENT]"
- "agregar MCP al arm"
- "configurar herramientas MCP"
- "install MCP stack"
- "setup MCPs"
- New arm onboarding

---

## MCP Catalog

| Tool | MCP Server | Type | URL / Command | Auth |
|------|-----------|------|---------------|------|
| Teams | Microsoft 365 | Remote (directory) | `https://microsoft365.mcp.claude.com/mcp` | OAuth |
| Outlook | Microsoft 365 | Remote (directory) | `https://microsoft365.mcp.claude.com/mcp` | OAuth |
| SharePoint | Microsoft 365 | Remote (directory) | `https://microsoft365.mcp.claude.com/mcp` | OAuth |
| Outlook Calendar | Microsoft 365 | Remote (directory) | `https://microsoft365.mcp.claude.com/mcp` | OAuth |
| Gmail | Gmail | Remote (directory) | `https://gmailmcp.googleapis.com/mcp/v1` | OAuth |
| Google Calendar | Google Calendar | Remote (directory) | `https://calendarmcp.googleapis.com/mcp/v1` | OAuth |
| Jira + Confluence | Atlassian Rovo | Remote (directory) | `https://mcp.atlassian.com/v1/mcp` | OAuth |
| Slack | Slack | Remote (directory) | `https://mcp.slack.com/mcp` | OAuth |
| GitHub | github-mcp-server | Remote HTTP | `https://api.githubcopilot.com/mcp` | PAT header |
| PostgreSQL | @bytebase/dbhub | stdio (local) | `npx -y @bytebase/dbhub` | DSN string |
| SQL Server / Azure SQL | microsoft_sql_server_mcp | stdio (local) | `uvx microsoft_sql_server_mcp` | env vars |
| Snowflake | Snowflake-Labs/mcp | stdio (local) | `uvx --from git+https://github.com/Snowflake-Labs/mcp mcp-server-snowflake` | env vars o OAuth nativo |

---

## Workflow

### Step 1 — Cloud MCPs (run ONCE at brain level, not per arm)

Connect via `claude.ai/settings/connectors`:

| Service | Action |
|---------|--------|
| Microsoft 365 (Teams/Outlook/SharePoint/Calendar) | Connect at claude.ai/settings/connectors |
| Atlassian Rovo (Jira/Confluence) | Connect at claude.ai/settings/connectors |
| Slack | Connect at claude.ai/settings/connectors |
| Gmail / Google Calendar | Connect at claude.ai/settings/connectors |
| GitHub | See Step 1b |

#### Step 1b — GitHub (PAT-based, user scope)

```bash
claude mcp add --transport http \
  --scope user \
  github https://api.githubcopilot.com/mcp \
  --header "Authorization: Bearer ${GITHUB_PAT}"
```

Add to `~/.env` or environment:

```bash
GITHUB_PAT=ghp_your_token_here
```

---

### Step 2 — Database MCPs (.mcp.json per arm)

Create or update `~/Documents/github/[CLIENT_NAME]/.mcp.json`.
**Only include the DB servers this client actually uses — delete unused blocks.**

```json
{
  "mcpServers": {
    "postgres-[CLIENT_NAME]": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@bytebase/dbhub", "--dsn", "${[CLIENT_NAME]_PG_DSN}"]
    },
    "sqlserver-[CLIENT_NAME]": {
      "type": "stdio",
      "command": "uvx",
      "args": ["microsoft_sql_server_mcp"],
      "env": {
        "MSSQL_SERVER": "${[CLIENT_NAME]_MSSQL_SERVER}",
        "MSSQL_DATABASE": "${[CLIENT_NAME]_MSSQL_DATABASE}",
        "MSSQL_USER": "${[CLIENT_NAME]_MSSQL_USER}",
        "MSSQL_PASSWORD": "${[CLIENT_NAME]_MSSQL_PASSWORD}"
      }
    },
    "snowflake-[CLIENT_NAME]": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/Snowflake-Labs/mcp",
        "mcp-server-snowflake",
        "--account", "${[CLIENT_NAME]_SF_ACCOUNT}",
        "--username", "${[CLIENT_NAME]_SF_USER}",
        "--role", "${[CLIENT_NAME]_SF_ROLE}",
        "--warehouse", "${[CLIENT_NAME]_SF_WAREHOUSE}",
        "--database", "${[CLIENT_NAME]_SF_DATABASE}"
      ],
      "env": {
        "SNOWFLAKE_PASSWORD": "${[CLIENT_NAME]_SF_PASSWORD}"
      }
    }
  }
}
```

---

### Step 3 — Client .env (add to `~/Documents/github/[CLIENT_NAME]/.env`, NEVER commit)

```bash
# PostgreSQL
[CLIENT_NAME]_PG_DSN=postgresql://user:pass@host:5432/dbname

# SQL Server / Azure SQL
[CLIENT_NAME]_MSSQL_SERVER=server.database.windows.net
[CLIENT_NAME]_MSSQL_DATABASE=mydb
[CLIENT_NAME]_MSSQL_USER=myuser
[CLIENT_NAME]_MSSQL_PASSWORD=secret

# Snowflake
[CLIENT_NAME]_SF_ACCOUNT=myorg-myaccount
[CLIENT_NAME]_SF_USER=myuser
[CLIENT_NAME]_SF_PASSWORD=secret
[CLIENT_NAME]_SF_ROLE=MYROLE
[CLIENT_NAME]_SF_WAREHOUSE=COMPUTE_WH
[CLIENT_NAME]_SF_DATABASE=MYDB

# GitHub (brain-level, documented here for reference only)
GITHUB_PAT=ghp_token
```

---

### Step 4 — Verify Arm Isolation

Run from within the arm directory:

```bash
# Claude Code:
claude mcp list
# Cursor: Settings → MCP, or GetMcpTools in-session (no claude CLI required)

# Should show ONLY database MCPs scoped to this arm.
# Cloud MCPs (Teams, Slack, Jira) appear via user-scope — that is CORRECT.
```

Verify `.gitignore` includes:

```
.env
.env.*
.mcp.json   # optional: if credentials are hardcoded (prefer env vars instead)
```

---

## Arm Isolation Rules

| MCP Category | Scope | Isolation Mechanism |
|---|---|---|
| Cloud MCPs (Teams, Gmail, Slack, Jira, GitHub) | `user` (brain) | OAuth is per-user; each service enforces access at API level — no client data crosses arms |
| Database MCPs (Postgres, SQL Server, Snowflake) | `arm` (`.mcp.json`) | Prefixed env vars per client (e.g., `CLIENT_A_PG_DSN`, `CLIENT_B_MSSQL_SERVER`) prevent cross-contamination even when two arms are open simultaneously |

**Rule: The brain NEVER sees database credentials. Only the arm's local `.env` does.**

---

## Usage Pattern (per arm)

1. Duplicate this skill reference
2. Replace `[CLIENT_NAME]` with the client code (e.g., `CLIENT_A`, `CLIENT_B`, `CLIENT_C`, `CLIENT_D`)
3. Delete `.mcp.json` blocks for DBs this client does NOT use
4. Populate `.env` with actual credentials for this client
5. Verify MCP on the active runtime (Claude Code: `claude mcp list`; Cursor: Settings → MCP / GetMcpTools)

## Arms Reference (example shape)

The actual list lives in your private `company/COMPANY.md`. Generic example:

| Arm | DB MCPs needed |
|-----|---------------|
| portfolio-arm | postgres |
| client-arm-a | postgres, snowflake |
| client-arm-b | postgres, sqlserver |
| analytics-arm | postgres |
| client-arm-c | postgres |
| client-arm-d | postgres |
| client-arm-e | sqlserver (Azure SQL) |

## Lessons Learned

- **2024-04**: `.mcp.json` should use env var references (`${VAR}`) not hardcoded values — enables arm isolation without `.gitignore` dependency on the file itself
- **2024-04**: Cloud MCP OAuth tokens are scoped to the Claude account, not to the workspace directory — they safely appear in all arms without leaking client data
- **2024-04**: Prefix all DB env vars with the client code (`CLIENT_E_MSSQL_SERVER` not `MSSQL_SERVER`) to prevent collisions when two arms share the same shell session

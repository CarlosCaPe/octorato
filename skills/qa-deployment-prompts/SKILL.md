---
name: qa-deployment-prompts
description: "QA Deployment Prompts"
metadata:
  short-description: "QA Deployment Prompts"
  original-index: 13
---

# QA Deployment Prompts

## What

A self-contained markdown document that provides everything an operator (or AI
agent) needs to deploy a ticket to an environment they can reach, when the
original developer cannot (e.g., due to VNET restrictions).

## Why

When DEV is reachable but QA is behind a VNET, the developer can't deploy
directly. Instead of writing a Slack message with scattered instructions, a
QA Deployment Prompt packages **all context** into a single copy-paste document
that another operator can execute without any additional questions.

## How

### Required sections

```markdown
# DA-XXX -- QA Deployment Prompt

## Context for the AI agent
- What the ticket does (plain English)
- What the script modifies (tables, procedures, indexes)
- Current status table (DEV: deployed, QA: pending)

## What you need to do

### Step 1: Verify the workspace
Test-Path fixes/tickets/DA-XXX/01_script.sql

### Step 2: Verify credentials
.env must have DB_HOST_QA, DB_PORT_QA, DB_USER_QA, DB_PASSWORD_QA

### Step 3: Test connectivity
TcpClient connect test to QA server

### Step 4: Dry-run (FIRST)
node scripts/run_sql_file.js --env qa --db MyDB_QA --file ... --logPrefix DA-XXX

### Step 5: Execute (only after dry-run succeeds)
node scripts/run_sql_file.js --env qa --db MyDB_QA --file ... --execute 1 --logPrefix DA-XXX

### Step 6: Update ticket files
Update CLOSURE_NOTE.md and README.md

### Step 7: Git commit

## Important notes
- Idempotent, dry-run by default, auth method, etc.
```

### Key principle

The prompt must be **self-contained**. The operator should not need to:
- Read other documents
- Ask the developer questions
- Understand the ticket history
- Know the database schema

Everything they need is in the prompt.

## When to Use

- Any deployment blocked by network restrictions (VNET, VPN, firewall)
- When handing off deployment to another team member
- When the deployment will happen at a different time (shift handoff)

## Where We Used It

- **DA-102**: Full QA deployment prompt with 7-step instructions,
  connectivity test, and post-deployment update checklist

## Gotchas

- Include the **exact** commands -- don't say "run the script," paste the
  full command line
- Include a connectivity test step -- if the operator can't reach the server,
  they should know immediately, not after 30 seconds of timeout
- Mention the auth method (`psqladmin` + password vs. Azure AD)
- Include the expected output (e.g., "8/8 post-check") so the operator
  knows what success looks like

---

*Category: Process | Origin: DA-102*

---
name: agent-proof-approval-gate
description: Build a fail-closed PreToolUse gate for merge/deploy/destructive actions that the AI agent provably cannot self-bypass. Use when you need human-only override for a consequential action the agent orchestrates.
metadata:
  type: lesson-learned
  status: draft
  captured: 2026-06-02
  origin: session-learn-extractor (manual /learn)
---

# Agent-Proof Approval Gate

## Problem

A PreToolUse hook that blocks a destructive action (merge, deploy, delete) needs a human-only override. Naively you might check for an env var or a flag — but the agent can set those itself with an inline prefix (`APPROVE=1 gh pr merge 96`) or by writing a file. The gate must be unforgeable by the entity it constrains.

## Key Insight — Inline Env Never Reaches the Hook

A PreToolUse hook runs in the **harness process**, not in the shell that executes the agent's command. When the agent writes `VAR=1 cmd`, that assignment is scoped to the child shell that runs `cmd`; the hook fires before `cmd` even starts, in a separate environment. Therefore:

> **An env var set in the agent's command prefix is invisible to the hook.**

Only a human who runs `export OCTO_MERGE_APPROVE=96` in the real terminal session can set the hook's env. The agent cannot reach it.

## Design

### Primary channel — scoped env var (agent-proof)

```bash
# Human grants approval for a specific PR
export OCTO_MERGE_APPROVE=96      # must match the exact PR number being merged
```

The hook validates:
1. `OCTO_MERGE_APPROVE` is set.
2. Its value **equals** the PR number extracted from the command being intercepted (not `startswith`, not `in` — exact equality).
3. Optionally, a TTL: compare against the file-mtime of a stamp written when the var was set.

```python
import os, re, sys

def check_approval(pr_number: str) -> bool:
    approved = os.environ.get("OCTO_MERGE_APPROVE", "").strip()
    return approved == pr_number          # "96" != "95", "96x", " 96"

# In the hook body:
if not check_approval(detected_pr):
    print(f"[gate] BLOCKED — set OCTO_MERGE_APPROVE={detected_pr} to authorize.")
    sys.exit(1)   # non-zero exit blocks the tool call
```

### Secondary channel — TTL'd approval file (loud, agent-forgeable — acceptable)

A human can also run an explicit command that writes a stamp:

```bash
octo-dim approve-merge 96    # writes ~/.claude/tmp/approved-merge-96.<epoch>
```

The hook checks for a fresh stamp (e.g. < 5 min old). This channel is technically agent-forgeable (the agent could call `octo-dim approve-merge` too), but the canon rule blocks self-approval: the gate script rejects approvals issued by the agent itself. The env channel is the real boundary; the file channel is convenience.

## Scoping Rule — Never Blanket, Always Specific

The approved value must encode the **exact action**:

| Bad (blanket) | Good (scoped) |
|---|---|
| `OCTO_MERGE_APPROVE=yes` | `OCTO_MERGE_APPROVE=96` |
| `APPROVE_ALL=1` | `OCTO_DEPLOY_APPROVE=prod-2026-06-02` |

A stale `OCTO_MERGE_APPROVE=95` cannot authorize PR 96. This prevents approval replay.

## Residual Risk

Shell indirection can evade **string-based** command detection (the part that extracts the PR number from the command):

```bash
bash -c "gh pr merge 96"          # hard to parse correctly
eval "gh pr merge 96"             # same
```

The env channel is immune to this because it doesn't depend on parsing the command — it only checks the env. If the action is truly critical, combine:
- Env channel for authorization (unforgeable).
- Command parsing for action identification (parse best-effort; fail-closed on ambiguity).

See [[command-boundary-hook-matching]] for the parsing half.

## When to Use

- Merging PRs that auto-deploy to production.
- Running destructive DB migrations.
- Any action where "the agent is doing the work but only the human should pull the trigger."

## Production writes (MANDATORY): no prod write without a per-destination operator approval

A remote production write is the same shape as a merge and gets the same treatment. `aws ssm send-command` carrying a host write, `wrangler deploy` / `secret put` / `kv key put|delete` / `pages deploy`, and the destructive AWS control-plane calls (`ec2 terminate-instances|stop-instances`, `iam put-role-policy|attach-role-policy|delete-*`, `secretsmanager put-secret-value|delete-secret`) are denied fail-closed unless the operator has approved **that specific destination** inside a short window. Orchestrator instructions passed to a builder sub-agent are not an authorization: they live in the agent's own context, so nothing outside the agent can check or record them, and three agents deploying on that basis in one session is exactly what produced the security alerts this rule exists for.

The destination is the instance id, the Worker name, or an agreed token. Approving the Worker never approves the instance, and a morning approval is dead by the afternoon (600 s window: an approval covers one operation, not a day).

Read-only stays untouched by design, and that is a hard requirement rather than a nicety: `describe-*`, `get-*`, `list-*`, an SSM payload that only runs `cat` / `journalctl` / `systemctl is-active|show`, and status `curl`s all pass silently. A gate that cries on a `describe-instances` gets switched off, and then it protects nothing.

Mechanism: `scripts/g__pretool-bash__prod-write.py` (Registry `SEC.prod-write-gate`), approvals via `OCTO_PROD_APPROVE=<destination>` (env, agent-proof) or `octo-dim.py approve-prod <destination>`, which refuses to run when it detects an agent shell.

## Reference Implementation

`~/.claude/scripts/qa-merge-gate.py` — full gate with env channel, file channel, PR-number extraction, and TTL logic.

`~/.claude/scripts/g__pretool-bash__prod-write.py` is the production-write sibling: per-destination scoping, payload inspection for SSM and ssh, a read-first allowlist that keeps false positives at zero, and a crash path that denies once a prod channel is identified.

## See also

- [[command-boundary-hook-matching]] — parsing the command string safely to extract the action identity
- [[pre-merge-qa-gate]] — QA approval workflow that feeds into this gate
- [[dry-run-gate-pattern]] — sibling pattern for destructive ops (preview before execute)

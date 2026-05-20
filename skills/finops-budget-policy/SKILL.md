---
name: finops-budget-policy
description: "Per-arm monthly USD budget caps with three escalation levels (alert / warn / hard_stop). Config lives in ~/.claude/budgets.yaml (gitignored). A PreToolUse hook calls scripts/budget-check.py before expensive tools (Agent, subagent dispatch, browser automation) and refuses to invoke when an arm's grace-adjusted cap is burned through."
metadata:
  short-description: "Open-source FinOps budget caps with real halt mechanism — the third leg of the per-client cost ledger"
---

# FinOps — Per-Arm Budget Caps

## What this skill is

The third building block of the FinOps pipeline:

  1. **Per-arm cost rollup + USD** (already shipped) — every trace event
     tags the client (`arm`), every session's tokens convert to USD.
  2. **Cost-spike watchdog** (already shipped) — z-score over 24h tokens
     per skill·arm against 30d baseline, alerts when a runaway spikes.
  3. **Budget caps** (this skill) — declarative monthly USD ceilings per
     arm with three escalation levels. A real halt mechanism, not just
     a dashboard warning.

Budget caps are the difference between *"we have telemetry"* and *"we
don't merge a PR that would burn the client's budget."* It's the
feature a CFO will recognize.

## When to use

- Whenever the operator runs Claude Code across multiple billable client
  engagements through the same API key.
- When onboarding a new arm: write a budget for it from day one. The
  default is "no cap configured = no enforcement"; opt-in is cheap.
- Before a long-running agent task (`agent-browser`, an SDD spec
  marathon, a multi-agent dispatch) — the hook fires automatically, but
  the operator should also know what the cap is going into the run.

## How it works

### 1. Configure budgets (private to the laptop)

Create `~/.claude/budgets.yaml`. This file is **gitignored** — it
encodes per-client pricing decisions and never enters the public brain
repo. Schema:

```yaml
budgets:
  - arm: client-x
    monthly_usd_cap: 200.00
    action_on_breach: hard_stop    # alert | warn | hard_stop
    grace_pct: 110                 # allow 10% overage before hard_stop fires

  - arm: client-y
    monthly_usd_cap: 500.00
    action_on_breach: warn          # surfaces in digest, never halts

  - arm: home                       # operator's tinkering bucket
    monthly_usd_cap: 50.00
    action_on_breach: alert         # log only, no UX impact

default:
  monthly_usd_cap: 100.00
  action_on_breach: warn
  grace_pct: 120
```

`action_on_breach` semantics:

| Action | When triggered | What happens |
|---|---|---|
| `alert` | spend ≥ cap | digest shows the breach next morning. No execution change. |
| `warn` | spend ≥ cap | next turn prepends a system warning to the operator. |
| `hard_stop` | spend ≥ cap × grace_pct/100 | PreToolUse hook refuses Agent / subagent / browser dispatch. Operator must edit budgets.yaml to override. |

### 2. Wire the PreToolUse hook (one-time, in settings.json)

The hook lives in `~/.claude/settings.json` under `hooks.PreToolUse`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Agent",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/scripts/budget-check.py --tool Agent"
          }
        ]
      }
    ]
  }
}
```

When the hook exits with code 2 (`HARD_STOP`), Claude Code refuses to
invoke the tool and surfaces the halt reason to the operator.

### 3. Daily visibility

`brain-digest.py` (the cron'd morning report) includes a
"Budget burn this month" section showing each configured arm's
month-to-date spend vs cap, with a marker (✓ / ⚠ / 🛑).

### 4. Override / unblock

When the hook halts and you legitimately want to proceed:

```bash
# Option A — raise the cap for the rest of the month
nvim ~/.claude/budgets.yaml   # bump monthly_usd_cap for that arm

# Option B — temporarily switch the breach action
# Edit the arm's `action_on_breach: hard_stop` → `warn`
# Remember to flip it back.
```

There is no `--force` flag on the budget checker itself by design —
the override path is config-driven so the change is durable and
auditable in `git diff` (well, in your private notes — `budgets.yaml`
is gitignored).

## Algorithm — how spend is measured

Spend = sum of `usd_estimate` for the arm's sessions from the 1st of
the current month to today. Calculated by running
`skill-cost-profiler.py --days <day-of-month> --json` and aggregating
`by_arm[].usd_estimate`. The same pricing dict
(`scripts/_pricing.py`) drives every layer of the FinOps pipeline —
single source of truth.

For arms with no observed spend yet, the cap still applies (in case a
new tool gets dispatched at the end of the month and would push them
over their cap on its first run).

## Anti-patterns

- **Setting hard_stop on the operator's own home bucket.** You'll lock
  yourself out of routine exploration. Use `warn` for `home`.
- **Forgetting to gitignore budgets.yaml.** It contains your pricing
  decisions and possibly client identifiers — must stay local.
- **Setting grace_pct: 100** (no grace). API call latency, cache races,
  and rounding mean a non-zero grace is operationally necessary.
- **Treating WARN as actionable for an agent.** WARN is for the
  operator's eyes; the agent should not parse it and self-throttle.
  Halts come from `hard_stop` exit code 2 alone.

## Lessons Learned

<!-- Append as the operator tunes per-arm caps and discovers what
breach actions actually work for them. -->

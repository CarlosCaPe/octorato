# FinOps — Cost Governance for an Agent OS

> **Organ:** metabolism — every token has a cost, every cost has an arm, and the organism stops burning when the cap is reached.

> Octorato is an open-source agent operating system that is **billed per token**, run by one operator across **multiple isolated client workspaces** ([[Architecture|arms]]). FinOps is the discipline that answers a single, unforgiving question: *when a token is spent, which client incurred it — and have they run out of budget?*

This page is the cost-governance reference. It documents the shipped pipeline end to end: how every action is traced and tagged with the arm that incurred it, how those traces roll up to per-client USD, how a statistical watchdog catches runaway spend, how a budget cap **halts an agent mid-run**, and how the brain's own list-price estimate is reconciled against Anthropic's actual invoice.

Everything described here is **local-first and SaaS-free**. The ledger lives on the operator's filesystem. No third-party FinOps platform ever sees a client's name or token counts.

---

## 1. Why FinOps matters here

A consultant running Claude Code across several engagements through one API key faces a problem that traditional cloud FinOps never had to solve at this granularity: **the unit of cost is a token, and tokens are fungible across clients.** Anthropic's invoice tells you the org spent *N* dollars. It does not tell you that Client A's refactor marathon was 70% of it and Client B barely touched the agent.

Without attribution you cannot do three things every consultant must do:

1. **Bill honestly.** "I spent roughly this much on you this month" is not a number you can defend. A per-arm USD rollup, derived from the actual token usage of sessions run inside that client's repository, is.
2. **Cap spend per client.** A budget is meaningless if it is org-wide. Client A's generous allowance should not let an agent quietly torch Client B's tight one.
3. **Detect runaways before the invoice arrives.** A cost spike caught at 24h is recoverable. One discovered on next month's bill is a write-off.

The architectural answer is the same one the [[Architecture|octopus model]] gives for isolation: **every trace event carries the arm that incurred it.** Attribution is not bolted on after the fact — it is captured at the moment the action happens, from the working directory the agent was standing in. That is the foundation the entire pipeline is built on. See [[Architecture]] for how arm isolation works and why the `arm` tag is trustworthy.

---

## 2. The pipeline at a glance

```
                        ┌─────────────────────────────────────────────┐
   8 hook points  ───▶  │  trace-hook.py        (capture, per event)   │
   (per skill /         │  → ~/.claude/traces/YYYY-MM-DD.jsonl         │
    agent / 4D phase)   │    every record tagged with `arm`            │
                        └───────────────────┬─────────────────────────┘
                                            │
        native session JSONLs               │ trace records
   (~/.claude/projects/.../*.jsonl)         │
              │                             ▼
              ▼                  ┌───────────────────────────┐
   ┌──────────────────────┐     │  watchdog.py  (cost_spike) │
   │ skill-cost-profiler   │───▶ │  z-score, 30d baseline     │──▶ GitHub issue
   │  per-arm USD rollup   │     └───────────────────────────┘
   │  (_pricing.py)        │
   └──────────┬───────────┘     ┌───────────────────────────┐
              │                 │  budget-check.py           │
              ├────────────────▶│  budgets.yaml → exit 2     │──▶ PreToolUse HARD-STOP
              │                 └───────────────────────────┘
              ▼
   ┌──────────────────────┐     ┌───────────────────────────┐
   │   brain-digest.py     │◀────│ anthropic-analytics-pull   │
   │  morning report       │     │ Admin API → analytics/     │
   │  estimated vs billed  │     └───────────────────────────┘
   └──────────────────────┘
```

Five stages, each independently shippable, each reading the substrate the one before it produced:

| Stage | Component | Role |
|---|---|---|
| 1. Capture | `trace-hook.py` (8 hook points) | Emit a trace record per skill / agent / 4D phase, tagged with the arm |
| 2. Roll up | `skill-cost-profiler.py` + `_pricing.py` | Convert tokens → USD, aggregate per arm and per skill |
| 3. Detect | `watchdog.py` (`cost_spike`) | z-score current 24h vs 30d baseline; open an issue on a spike |
| 4. Cap | `budget-check.py` + `budgets.yaml` | Hard-stop a tool invocation when an arm burns its cap (exit 2) |
| 5. Reconcile | `anthropic-analytics-pull.py` + `brain-digest.py` | Estimated (list price) vs billed (Anthropic Admin API) |

The single thread running through all five is **the `arm` tag and the `_pricing.py` USD table** — one source of truth for "who" and one for "how much," shared by every layer so the digest, the watchdog, and the budget cap can never disagree.

---

## 3. Stage 1 — Trace capture (`trace-hook.py`, 8 hook points)

`scripts/trace-hook.py` is the observability capture surface. It reads a Claude Code hook event from stdin and appends one JSONL record to `~/.claude/traces/YYYY-MM-DD.jsonl`. It is **best-effort by contract**: any malformed input or internal error is silently swallowed (`return 0`) so the hook can never block the underlying tool call. A FinOps ledger that breaks the agent is worse than no ledger.

### The three record types

| `event` | Emitted when | Builder |
|---|---|---|
| `skill_fire` | `PostToolUse` on the `Skill` tool | `_build_skill_fire` |
| `agent_activate` | `PostToolUse` on the `Agent` tool | `_build_agent_activate` |
| `phase_boundary` | invoked with `--phase <name>` from a lifecycle hook | `_build_phase_boundary` |

Every record shares a strict schema (`schemas/trace-event.schema.json`, v1.0):

```json
{
  "schemaVersion": "1.0",
  "ts": "2026-05-24T15:04:01.234Z",
  "event": "skill_fire",
  "name": "querymaster-postgresql",
  "task_id": "<sha1(session_id) — 40 hex chars>",
  "arm": "client-x",
  "duration_ms": null,
  "tokens": {"input": 1234, "output": 567},
  "status": "ok",
  "error": null
}
```

### How the `arm` tag is derived — the heart of attribution

```python
ARM_PATH_RE = re.compile(r"/Documents/github/([^/]+)(/|$)")

def _arm_from_cwd() -> str | None:
    m = ARM_PATH_RE.search(os.getcwd())
    return m.group(1) if m else None
```

The arm is the directory segment immediately after `github/` in the agent's current working directory. Stand the agent inside a client's repository and **every** action it takes — every skill, every subagent, every 4D phase — is automatically stamped with that client. The operator does nothing; attribution is a consequence of *where the work happens*, which is exactly the [[Architecture|arm isolation]] invariant. No CWD match (e.g. the operator's bare home directory) yields `null`, bucketed downstream as `home` or `__unknown__`.

`task_id` is `SHA-1(session_id)` — exactly 40 hex chars, matching the schema. Autonomous turns with no session id get an ad-hoc UUID v4. This id is what later lets the profiler join a skill's token cost to its 3D-Diligent success count for ROI.

### The 8 hook points

The phases of the [[The-4D-Paradigm|4D Paradigm]] are themselves traced. `trace-hook.py --phase <name>` accepts the six valid phases — `describe`, `delegate`, `gate`, `execute`, `diligent`, `disclose` — plus the two tool-completion captures (`Skill`, `Agent`). Wired in `~/.claude/settings.json`:

| # | Lifecycle hook | Matcher | Invocation | Records |
|---|---|---|---|---|
| 1 | `UserPromptSubmit` | — | `trace-hook.py --phase describe` | `phase_boundary: describe` |
| 2 | `UserPromptSubmit` | — | `trace-hook.py --phase delegate` | `phase_boundary: delegate` |
| 3 | `PreToolUse` | `Write\|Edit` | `trace-hook.py --phase gate` | `phase_boundary: gate` |
| 4 | `PostToolUse` | `Write\|Edit` | `trace-hook.py --phase execute` | `phase_boundary: execute` |
| 5 | `PostToolUse` | `Write\|Edit` | `trace-hook.py --phase diligent` | `phase_boundary: diligent` |
| 6 | `Stop` | — | `trace-hook.py --phase disclose` | `phase_boundary: disclose` |
| 7 | `PostToolUse` | `Skill` | `trace-hook.py` (no flag) | `skill_fire` |
| 8 | `PostToolUse` | `Agent` | `trace-hook.py` (no flag) | `agent_activate` |

This maps the full Describe → Delegate → Gate → Execute → Diligent → Disclose nervous-system flow plus the two tool-fire signals onto a continuous trace. The `diligent` `phase_boundary` records (`status: ok`) are reused downstream as the ROI denominator: *tokens spent per successful diligence.*

**Storage contract.** One file per UTC day under `~/.claude/traces/`, append-only. POSIX `O_APPEND` makes sub-4096-byte appends atomic — no file locking needed. The directory is **gitignored**; traces carry arm names and absolute paths and must never reach the public brain repo. Full layout in `docs/architecture/trace-storage.md`.

---

## 4. Stage 2 — Per-arm USD rollup (`skill-cost-profiler.py` + `_pricing.py`)

`scripts/skill-cost-profiler.py` turns raw usage into money. It does **not** read the trace files for token counts — it reads the **native Claude Code session JSONLs** under `~/.claude/projects/<sanitized-cwd>/<session-uuid>.jsonl`, which carry the authoritative per-turn `usage` block (input, output, cache-creation, cache-read). The trace files supply the ROI denominator; the session logs supply the cost.

### Arm derivation from the session path

Claude Code stores each session under a directory whose name is the absolute CWD with `/` replaced by `-`. The profiler's `_arm_from_session_path` mirrors `trace-hook.py`'s CWD logic against that encoding:

- `-home-<user>-Documents-github-<arm>` → the segment after `github` is the arm
- a path containing `--claude` → the `.claude` brain bucket
- bare `-home-<user>` → `home`
- anything else → `__unknown__`

So the same client identity is recovered whether you look at a trace event or a session log — the two halves of the ledger agree by construction.

### Turn-level attribution

For each `assistant` turn the profiler:

1. extracts the rich `usage` (input + cache-creation + cache-read summed as "input-incl-cache", plus output);
2. adds it to the **per-arm** rollup (sessions, turns, input, output, cache-read, cache-write);
3. finds any `Skill` `tool_use` blocks in the turn. If the turn fired *M* skills, the turn's tokens split equally across them (remainder to the first). Turns with no skill land in the `__conversation__` bucket.

### USD conversion — `_pricing.py`, the one source of truth

`scripts/_pricing.py` is the **single USD authority** shared by the profiler, the watchdog's cost-spike check, the budget checker, and the digest. It holds Anthropic list price per 1M tokens per model, with four rates each:

| Rate | Meaning |
|---|---|
| `in` | input tokens |
| `out` | output tokens |
| `cache_w` | cache **creation** — 1.25× input (writing the cache costs more) |
| `cache_r` | cache **read** — ~10% of input (a cache hit is cheap; high cache-read volume is *good news*) |

Unknown model names fall back to a family heuristic (`opus` / `haiku` / else `sonnet`) so cost reporting never goes dark when Anthropic ships a new model before the dict is updated. `_normalize_model_name` strips `[1m]`-style suffixes and trailing 8-digit date stamps to find the canonical key.

> **Billing semantics note (from `_pricing.py`):** on a Claude Max/Pro subscription the USD figure is *"what this would cost at list price"* — value extracted, not money owed. Synthetic harness messages (`model='<synthetic>'`) are $0.

### Output

```bash
python3 ~/.claude/scripts/skill-cost-profiler.py --days 30          # markdown
python3 ~/.claude/scripts/skill-cost-profiler.py --days 30 --json   # machine-readable
```

The markdown report leads with the FinOps headline — **Cost by arm** — then the per-skill breakdown:

```
# Cost by arm (client) — last 30d
| Arm        | Sessions | Turns | Total tokens | USD (list price) |
|------------|---------:|------:|-------------:|-----------------:|
| `client-x` |       42 | 1,203 |   18,400,221 |          $XXX.XX |
| `home`     |       15 |   310 |    3,100,004 |           $XX.XX |
| **TOTAL**  |          |       |              |          $XXX.XX |
```

The `--json` form (`{"by_skill": [...], "by_arm": [...]}`) is the API contract consumed by `budget-check.py` and `watchdog.py`. Each `by_arm` row exposes `usd_estimate` — the field every downstream stage reads.

---

## 5. Stage 3 — Cost-spike watchdog (`watchdog.py`)

`scripts/watchdog.py` is the anomaly detector. It computes three classes — `cliff_drop` (a skill stopped firing), `quality_drop` (success rate fell >2σ), and the FinOps-relevant **`cost_spike`** — and, in `--execute` mode, opens a deduplicated GitHub issue.

### How `cost_spike` works

The check (`_detect_cost_spikes`) calls `skill-cost-profiler.py --json` **twice** — once for the last 24h, once for the 30-day baseline — and compares per `(bucket, name)` where bucket is `by_arm` or `by_skill`:

```python
expected_per_day = baseline_total_30d / 30
z = (observed_24h - expected_per_day) / sqrt(expected_per_day)   # Poisson z-score
```

An anomaly fires only when **both** hold:

- `z ≥ 2.0` (`SIGMA_THRESHOLD`) — today is statistically far above the daily baseline, **and**
- `observed_24h ≥ 100_000` tokens (`MIN_TOKENS_FOR_COST_SPIKE`) — the noise floor.

The floor is the design lesson: below ~100k tokens/day the stddev comparison is hypersensitive — a 2-turn task can sit 2σ above a near-zero baseline and trigger a meaningless alert. Brand-new arms/skills with `expected_per_day < 1` are skipped entirely (no baseline → no σ).

Because the spike check runs per-arm, a runaway is attributed to the client who caused it. The issue body carries the 24h token count, the projected daily baseline, the z-score, and the `~USD 24h` figure straight from `_pricing.py`.

```bash
python3 ~/.claude/scripts/watchdog.py              # dry-run: print the report
python3 ~/.claude/scripts/watchdog.py --execute    # open GitHub issues
```

Dedup + suppression state lives under `~/.claude/watchdog/` (gitignored): one issue per name per day, 14-day suppression after the operator dismisses an issue. Suggested cron: `0 14 * * * python3 ~/.claude/scripts/watchdog.py --execute`.

> The watchdog **alerts**. It does not stop anything. Stopping is Stage 4's job.

---

## 6. Stage 4 — Budget caps that halt the agent (`budget-check.py` + `budgets.yaml`)

This is the stage a CFO recognizes: the difference between *"we have telemetry"* and *"we will not run a tool that burns through this client's budget."*

### `budgets.yaml` — declarative, per-arm, private

The config lives at `~/.claude/budgets.yaml` and is **gitignored** — it encodes per-client pricing decisions and possibly client identifiers, so it never enters the public brain. (A `budgets.json` fallback is read when PyYAML is unavailable.)

```yaml
budgets:
  - arm: client-x
    monthly_usd_cap: 200.00
    action_on_breach: hard_stop    # alert | warn | hard_stop
    grace_pct: 110                 # allow 10% overage before hard_stop fires

  - arm: home                      # operator's tinkering bucket
    monthly_usd_cap: 50.00
    action_on_breach: alert        # log only, never blocks

default:                           # applies to any arm not listed
  monthly_usd_cap: 100.00
  action_on_breach: warn
  grace_pct: 120
```

| Action | Trigger | Effect |
|---|---|---|
| `alert` | spend ≥ cap | tomorrow's digest shows the breach. No execution change. |
| `warn` | spend ≥ cap | digest warning for the operator. Does **not** halt. |
| `hard_stop` | spend ≥ cap × grace_pct/100 | `PreToolUse` hook refuses the tool. Operator must edit `budgets.yaml` to proceed. |

### How spend is measured

`_month_to_date_usd_by_arm()` runs `skill-cost-profiler.py --days <day-of-month> --json` (e.g. on the 24th, `--days 24`) and reads each `by_arm[].usd_estimate`. Month-to-date, per arm, in the same USD that every other stage uses. Caps apply even to arms with zero observed spend yet — so a tool dispatched late in the month can't sneak over the line on its first run.

### The halt — exit code 2

`evaluate()` returns a structured verdict (`OK` / `WARN` / `HARD_STOP`). The exit code is the contract:

| Exit | Status | Caller obligation |
|---|---|---|
| `0` | `OK` or `WARN` | proceed (a `WARN` is for the operator's eyes only) |
| `1` | config error (malformed YAML) | proceed; misconfig must not block work |
| `2` | `HARD_STOP` | **caller MUST refuse the tool invocation** |

`HARD_STOP` fires only when an arm's spend reaches `cap × grace_pct/100` **and** that arm's `action_on_breach == hard_stop`. The `halt_reason` string spells out the arithmetic, e.g. *"arm 'client-x' burned $221.40 (grace $220.00 = cap $200.00 × 110%) — refusing tool."*

### Wiring the PreToolUse hook

In `~/.claude/settings.json`, gate the expensive tools (`Agent`, subagent dispatch, browser automation) on the checker:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Agent",
        "hooks": [
          { "type": "command",
            "command": "python3 ~/.claude/scripts/budget-check.py --tool Agent" }
        ]
      }
    ]
  }
}
```

When the hook exits `2`, Claude Code refuses to invoke the tool and surfaces the halt reason. By design there is **no `--force` flag** on the checker — the only way through is to edit `budgets.yaml` (raise the cap, or flip `hard_stop` → `warn`), making every override a durable, auditable config change rather than a transient keystroke. The checker is built to run on *every* invocation (target <200ms), so it stays out of the way until it matters. Full operator playbook: the [`finops-budget-policy`](https://github.com/CarlosCaPe/octorato/blob/master/skills/finops-budget-policy/SKILL.md) skill.

**Anti-patterns to avoid:** `hard_stop` on the `home` bucket (you'll lock yourself out of routine exploration — use `warn`); `grace_pct: 100` (no grace — latency, cache races, and rounding make a non-zero buffer operationally necessary); and having the agent parse a `WARN` and self-throttle (WARN is for humans; only exit-2 halts).

---

## 7. Stage 5 — Reconciliation: estimated vs billed (`anthropic-analytics-pull.py`)

Stages 1–4 run on the brain's **estimated** USD — list-price math over token counts. That is good enough to cap spend and catch spikes, but it is **not** what Anthropic actually charges (enterprise discounts, exact rate card, cache classification). Stage 5 pulls the vendor truth and reconciles.

`scripts/anthropic-analytics-pull.py` calls the Anthropic Admin API `GET /v1/organizations/usage_report` and writes the rows verbatim to `~/.claude/analytics/anthropic-<YYYY-MM-DD>.jsonl` (one row per line; the directory is **gitignored** — it holds vendor billing data).

```bash
python3 ~/.claude/scripts/anthropic-analytics-pull.py --dry-run   # show URL + env state
python3 ~/.claude/scripts/anthropic-analytics-pull.py --days 7    # write 7 days of rows
```

**Soft-fail by design.** It reads `ANTHROPIC_ADMIN_API_KEY` (an Admin-scope key, distinct from the per-user API key; `ANTHROPIC_ORG_ID` optional). If the key is unset it prints "not configured" and exits `0` — the rest of the FinOps pipeline keeps running on estimates. On Pro/Max-only accounts this stage is simply dormant.

### The reconciliation row

`brain-digest.py` (`section_anthropic_reconciliation`) reads the latest `analytics/anthropic-*.jsonl`, totals the billed USD, and renders against the estimate:

```
**Anthropic billed (vendor truth)** vs **Estimated (Octorato)** — 24h
- Estimated (list-price math): $XX.XX
- Billed (Anthropic Admin API): $XX.XX
- Delta: +X.X%   ⚠ drift > 20%
- Source: analytics/anthropic-2026-05-24.jsonl (N rows)
```

A delta over 20% is flagged — it almost always means a **stale `_pricing.py`** (Anthropic changed rates) or a cache-read classification mismatch. The Admin pull is an *after-the-fact* truth-table, **not** a brake pedal: a runaway burning thousands in an hour shows up on tomorrow's pull, not in time to stop it. Stopping is Stage 4's job; this stage tells you whether your estimates were honest. Full setup: the [`anthropic-enterprise-analytics`](https://github.com/CarlosCaPe/octorato/blob/master/skills/anthropic-enterprise-analytics/SKILL.md) skill. Suggested cron (30 min after the digest, so it lands on the *next* morning's report): `30 15 * * * python3 ~/.claude/scripts/anthropic-analytics-pull.py`.

---

## 8. The daily digest — where it all surfaces

`scripts/brain-digest.py` is the cron'd morning report that assembles every FinOps surface into one place:

- **Cost by arm** (from the profiler) — the billable rollup.
- **Budget burn this month** (from `budget-check.py`) — each configured arm's MTD spend vs cap with ✓ / ⚠ / 🛑 markers; a 🛑 means a hard-stop is active on at least one arm.
- **Cost spikes** (from the watchdog) — any 24h anomaly.
- **Estimated vs billed** (from the analytics pull) — the reconciliation row.

One report, every morning, answering: *what did each client cost, is anyone near their cap, did anything spike, and were my estimates right?*

---

## 9. Design invariants

| Invariant | Why |
|---|---|
| **Trace capture never blocks the agent** | `trace-hook.py` swallows all errors and returns 0. A broken ledger must never break the work. |
| **`_pricing.py` is the only USD authority** | Profiler, watchdog, budget cap, and digest all import it — they can never disagree on cost. |
| **The `arm` tag comes from the CWD** | Attribution is a free consequence of [[Architecture|arm isolation]], not a manual annotation the operator can forget. |
| **Estimate runs without the vendor API** | Budget caps and spikes work on Pro/Max with no Admin key. Reconciliation is purely additive. |
| **Override is config, not a flag** | No `--force` on `budget-check.py`. The only way past a hard-stop is an auditable `budgets.yaml` edit. |
| **Cost-bearing files are gitignored** | `traces/`, `analytics/`, `budgets.yaml`, `watchdog/` all stay local. The public brain never learns a client name or token count. |

---

## 10. Generic by construction

Octorato's brain is open-source; its git history is public forever. **None of the FinOps machinery leaks a client.** Arm names live only in gitignored runtime files (`traces/`, `analytics/`, `budgets.yaml`); the committed scripts contain only the *mechanism* — regexes, z-score math, a list-price table, exit codes. The same self-publicity rule that governs [[Self-Growth|skill creation]] governs the ledger: distill the technique into the public brain, keep the client's numbers on the laptop.

---

## See also

- [[Architecture]] — the octopus model, arm isolation, and why the `arm` tag is trustworthy
- [[The-4D-Paradigm]] — the six-phase lifecycle the trace hooks capture
- [[Self-Growth]] — the daily LLM-gated loop whose near-zero cost this envelope makes viable
- [`finops-budget-policy`](https://github.com/CarlosCaPe/octorato/blob/master/skills/finops-budget-policy/SKILL.md) — operator playbook for budget caps
- [`anthropic-enterprise-analytics`](https://github.com/CarlosCaPe/octorato/blob/master/skills/anthropic-enterprise-analytics/SKILL.md) — operator playbook for vendor reconciliation

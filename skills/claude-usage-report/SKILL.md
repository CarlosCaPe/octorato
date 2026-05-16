---
name: claude-usage-report
description: Aggregate Claude Code usage (tokens, sessions, API-equivalent cost) by day, week, month, model, and project from local JSONL session logs. Use when the user asks about their Claude Code usage, consumption, costs, "cuánto he usado", "uso diario/semanal/mensual", or wants to audit which projects/models are eating the most tokens.
---

# Claude Usage Report

## Purpose

Claude Code stores every assistant message — including token usage and model
identity — in JSONL files under `~/.claude/projects/`. This skill parses those
logs and produces a usage breakdown so the operator can:

- See daily / weekly / monthly activity at a glance.
- Identify which projects and models are driving cost.
- Spot anomalies (sudden spike, idle weeks, model drift).
- Quantify the "value extracted" from a Claude Max/Pro subscription vs paying
  per-token at API list price.

## Triggers

Activate when the user asks any of:

- "¿cómo va mi uso de Claude?" / "how is my Claude usage?"
- "uso semanal" / "uso mensual" / "uso diario"
- "cuánto he gastado en Claude" / "Claude usage stats"
- "qué proyecto consume más tokens"
- "qué modelo uso más"
- Any audit-style question about Claude Code consumption.

## Workflow

### 1. Run the aggregator

```bash
python3 ~/.claude/skills/claude-usage-report/scripts/usage_report.py
```

Optional flags:

- `--days 30` — show last 30 days of detail (default 14)
- `--json` — emit machine-readable output (useful for piping into other tools)
- `--projects-dir PATH` — override the default `~/.claude/projects/` location

### 2. Output sections (in order)

1. **Header** — files scanned, lines, messages with usage data
2. **ÚLTIMOS N DÍAS** — day-by-day breakdown (sessions, msgs, tokens, $)
3. **POR SEMANA** — last 8 ISO weeks
4. **POR MES** — every month with activity
5. **POR MODELO** — sorted by cost, shows which model dominates spend
6. **POR PROYECTO** — top 10 projects by cost (uses cwd-derived names)
7. **TOTAL ACUMULADO** — grand totals + cost note

### 3. Interpret with the user

Use the output to answer their actual question. Common follow-ups worth
volunteering:

- If Opus dominates >80% of cost: "Sonnet handles ~80% of typical work at 1/5
  the price — worth considering for non-critical tasks."
- If cache reads are large vs input tokens: "Prompt caching is saving you ~X.
  Keeping sessions warm matters."
- If a single day is an extreme outlier: name it and check it's expected.
- If sessions count is high but msgs/session low: many short interruptions —
  consolidating may help cache hit rate.

## Pricing source

The script embeds Anthropic public list prices (USD per 1M tokens) for the
Claude 4.x family. Pricing categories: `in`, `out`, `cache_w` (cache write),
`cache_r` (cache read).

When Anthropic updates prices or releases new models, edit the `PRICING` dict
at the top of `scripts/usage_report.py`. Unknown models fall back to family
heuristics (opus / sonnet / haiku) so the report still produces a number.

## Best practices

- **Don't conflate cost with payment.** With a Claude Max/Pro subscription the
  dollar figure is "what this would cost at API list price" — i.e. value
  extracted, not money owed. Always state this when reporting.
- **Cache read is the cheapest token type** (~5% of input price) — high cache
  read volume is good news, not bad.
- **Synthetic messages** (model = `<synthetic>`) are harness-generated, not
  billed. They appear in counts but with $0.
- **Empty sessions** (msgs but no `usage` field) exist because Claude Code
  sometimes writes user-only lines or aborted turns. The aggregator skips
  records without `usage`, which is correct.

## Error handling

- **Empty `~/.claude/projects/`** — script exits with a clear error. Suggest
  running Claude Code at least once first.
- **Malformed JSONL lines** — silently skipped per line (logs sometimes have
  truncated tails after crashes).
- **Unknown model name** — falls back to family heuristic via substring match.
  If neither opus nor haiku is in the name, defaults to Sonnet pricing.

## Lessons Learned

- **Don't trust `npx` for one-off tools in restricted environments.** The
  canonical community tool for this (`ccusage`) is great but is blocked by
  Claude Code's auto-mode classifier (external code execution). Parsing the
  JSONL directly with Python avoids that gate entirely.
- **Project names come from `cwd`-derived directory names**, e.g.
  `-home-user-Documents-github-foo`. The script strips the home prefix
  generically (no hardcoded usernames) so the same code works for any operator.
- **ISO weeks ≠ calendar weeks.** Use `datetime.isocalendar()` to match what
  most billing dashboards report. Don't roll your own week math.
- **`cache_creation_input_tokens` is expensive** (1.25× input price) — a
  session that writes huge cache once then reads it many times is optimal;
  one that re-writes cache every turn burns money.

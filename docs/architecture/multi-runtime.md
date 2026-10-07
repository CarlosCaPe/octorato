# Multi-runtime: all editors, all engines

> **Status:** live as of 2026-09-06 (v7.2.0).
> **Thesis:** Octorato is a **file-native agent OS**. It is not "a Claude Code config" and not "an Anthropic product." The brain grows as new **runtimes** (editors/harnesses) and **engines** (models) become known. Claude was first; Cursor + Grok are **supported peers with live bindings** (see Honest gaps: not every Claude-shaped hook maps 1:1 yet). The next editor or model gets a binding row, not a fork of the OS.

## The invariant

| Layer | What it is | Vendor-coupled? |
|---|---|---|
| **Brain** (`~/.claude/`) | Rules, skills, agents, hooks, FinOps, plain files under git | **No** (path name is historical) |
| **Runtime** | The harness that loads the brain and drives the tool loop | Yes (Claude Code, Cursor, …) |
| **Engine** | The model that reasons inside that loop | Yes (Claude family, Grok, GPT, Composer, …) |

The brain must not assume "I am Claude" or "the only CLI is `claude`". It assumes **Octorato is loaded** and the operator picked a runtime + engine. Identity in chat = the engine the harness selected; the OS brand = Octorato.

## Growth rule (how the OS expands)

When a new editor or model shows up in real operator use:

1. Add a **runtime row** (how brain loads, how hooks fire, how MCP is listed) and/or an **engine binding** (mechanical / bulk / build / judgment slugs).
2. Extend `scripts/_pricing.py` with list prices when FinOps must meter that engine.
3. Keep the **four tiers** stable, never invent a fifth vendor-specific ladder.
4. Ship a CHANGELOG note. Do **not** fork skills into `skills-claude/` vs `skills-grok/`.

Unknown engine today ≠ unsupported forever. Unknown = "binding not yet written"; the OS still runs on whatever the harness selected.

## Supported runtimes (known as of 2026-09-06, v7.2.0)

| Runtime | How the brain is loaded | How hooks fire | How MCP is listed | Detect |
|---|---|---|---|---|
| **Claude Code** | Reads `~/.claude/CLAUDE.md` natively | `~/.claude/hooks.json` | `claude mcp list` / `claude mcp add` | `claude` CLI present, no `CURSOR_AGENT` |
| **Cursor** | Project/user rules + arm `CLAUDE.md`; skills from brain + arm | `scripts/merge-hooks-cursor.py` → `~/.cursor/hooks.json` | Cursor MCP panel / `GetMcpTools` (no `claude` CLI) | `CURSOR_AGENT=1` |

Next candidates (binding TBD when first used in anger): Windsurf, Continue, Aider, OpenAI Codex CLI, JetBrains AI: same four columns, new row.

## Model ladder is tier-first, vendor-second

Four vendor-agnostic tiers. Each runtime maps its available model slugs onto those tiers. Full HOW: `skills/model-routing-by-complexity/SKILL.md`.

| Tier | Job | Anthropic (Claude Code) | xAI Grok / Cursor (typical) | Other Cursor engines |
|---|---|---|---|---|
| **mechanical** | grep, extract, format, inventory | Haiku | `composer-2.5-fast` or `grok-build-0.1` | smallest fast slug the harness lists |
| **bulk** | well-specified batch build | Sonnet (conscious downgrade) | mid Grok (`grok-4.3` / `grok-4.20-*`) | mid GPT (`gpt-5.5-medium`, …) |
| **build** | default implementation | Opus | `grok-4.5` / `grok-4.5-fast-xhigh` | session frontier when already on build-tier |
| **judgment** | QA, review, adversarial verify | **Fable** (no exceptions on Claude Code) | strongest *independent* engine ≥ builder | prefer a **different vendor** than the builder when available; else fresh same-tier session |

**Invariant unchanged:** the verifier must be at least as strong as the builder. A weaker reviewer approves what it cannot see.

## Q2 MCP check is runtime-aware

Same priority everywhere: **registered MCP → register official MCP if one exists → REST → SDK → scrape (last resort).**

| Runtime | Concrete check (not a mental check) |
|---|---|
| Claude Code | `claude mcp list` (+ `claude mcp add …` to register) |
| Cursor | Inspect MCP servers via `GetMcpTools` / Cursor Settings → MCP (no `claude` CLI required) |

`"No MCP connected" ≠ "no MCP available"` holds on every runtime.

## Honest gaps (Cursor peer: do not overclaim)

These are known, intentional, or pending, not silent failures:

1. **`merge-hooks-cursor.py` drops `Skill` / `Agent` matchers**: Cursor has no equivalent tool names; those Claude-only PreToolUse gates do not project. Shell/Write/Edit-class gates still fire.
2. **Composer / bundled GPT list prices**: `_pricing.py` reports `$0` list (UNKNOWN) rather than inventing Anthropic Sonnet rates. Add rows when a public list exists or when reconciling invoices.
3. **Cursor Task allow-list ≠ xAI API names**: prefer harness slugs (`composer-2.5-fast`, `grok-4.5-fast-xhigh`, `gpt-5.5-medium`, …). Treat `grok-4.3` / `grok-build-0.1` as API/FinOps unless the harness lists them.
4. **MCP census**: `capability-census.py` reads Claude registries **and** `.cursor/mcp.json` (user + workspace). In-session truth is still `GetMcpTools`.

## What stays Claude-shaped on purpose

- Install path `~/.claude/` and skill/agent filenames (historical, not identity).
- Anthropic Admin API reconciliation (`anthropic-enterprise-analytics`): Claude Max/Pro FinOps path only.
- Skills whose *subject* is Claude (`claude-usage-report`, `claude-plugins-official`): skip when the session engine is not Claude; do not delete them.

## What must not break a non-Claude session

1. **Do not** require `claude mcp list` when `CURSOR_AGENT=1`.
2. **Do not** claim "I am Claude" when the session engine is Grok (or GPT, or Composer): identity = engine; OS = Octorato.
3. **Do not** pass Anthropic-only aliases (`haiku`/`sonnet`/`opus`/`fable`) into Cursor `Task`: use that harness's allow-listed slugs.
4. **Do** keep projecting hooks via `merge-hooks-cursor.py` so fail-closed gates still fire in Cursor.
5. **Do** meter Grok (and other engines) in `_pricing.py` so FinOps is not Anthropic-blind.

## Related

- `skills/model-routing-by-complexity/SKILL.md`: the ladder
- `scripts/_pricing.py`: multi-vendor list prices
- `scripts/merge-hooks-cursor.py`: Cursor hook projector
- `docs/wiki/Getting-Started.md`: install for either runtime

<!-- moved-from-claude-md v10-T13 -->
## Constitution detail (moved from CLAUDE.md)

These paragraphs were the constitution's own text until v10 (T13), moved here so `CLAUDE.md` keeps only what every session needs. They are kept as written, with em-dashes normalised; `CLAUDE.md` now carries a short paragraph pointing here.

### 2D Q2: the MCP census

| Q | Question | Tool |
|---|---|---|
| Q2 | Is there an MCP/API? (token-efficient access) | **Runtime-aware MCP census (not a mental check).** Claude Code → `claude mcp list` (+ `claude mcp add --transport http <name> <url>` to register). Cursor (`CURSOR_AGENT=1`) → inspect MCP via `GetMcpTools` / Cursor Settings → MCP (no `claude` CLI required). Priority on every runtime: registered MCP > **register a NEW MCP if an official one exists** > REST API > SDK > scraping (last resort). **"No MCP connected" ≠ "no MCP available".** Before dropping to scraping or hand-rolled REST, you MUST verify whether an official MCP server exists for this service (web-search "<service> MCP server") and register it on the active runtime. Skipping this check is a hard failure, not a shortcut. See `docs/architecture/multi-runtime.md`. |

### Route work by complexity across the model ladder

**Route work by complexity across the model ladder** (`model-routing-by-complexity`; architecture: `docs/architecture/multi-runtime.md`): tiers are **vendor-agnostic**, mechanical → bulk (conscious downgrade, never the default) → build DEFAULT → **judgment, no exceptions** (QA, code review, second opinion, adversarial verify). Bind to the active runtime: Claude Code → Haiku / Sonnet / Opus / **Fable**; Cursor+xAI → `composer-2.5-fast` / mid-Grok-or-GPT / `grok-4.5*` / strongest independent ≥ builder. Octorato is for **all models and all editors**, new engines get a binding row, not a fork. The invariant behind the pin: the verifier must run on a model at least as strong as the builder, because a weaker reviewer approves what it cannot see. Never burn the build-tier engine on what a cheaper tier does, delegating *is* Q3 (who does it?), not optional. Identity in chat = the engine the harness selected (Grok, Claude, GPT, …); the OS is Octorato. These verdicts are meant to fire as **reflexes via hooks**, not depend on discipline, see `docs/architecture/hook-orchestration.md` (the Reactive Control Architecture: ECA atoms · Behavior-Tree priority · Statechart 4D · Spreading-Activation recall · Bandit tier-routing). **A gate that depends on the model remembering it WILL be skipped under load** (Q2/Q3 were "mental checks" for too long, so an MCP went unregistered and days were burned on manual scraping); when a rule is chronically ignored, the fix is never "try harder": give the arm a ganglion (a hook that fires on its own). Full HOW in `skills/reflexes-over-discipline/SKILL.md`. Report the 3-line summary in every response that involves work. Full detail in `skills/4d-paradigm-protocol/SKILL.md`.

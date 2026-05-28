---
name: repo-watch
description: Daily monitor for a small watchlist of high-value GitHub repos (competitors, peers, upstream Claude Code ecosystem). Reads `skills/repo-watch/watchlist.yaml`, fetches HEAD SHA per repo, diffs against the previous snapshot, classifies the delta as HIGH/LOW/EMPTY/BASELINE signal, appends to a daily digest at `~/.claude/knowledge/repo-watch/<date>.md`, and writes file-based trigger markers for `/repo-deep-learn` to pick up out-of-band. Use when the operator wants to keep a finger on a competitor's pulse (first target — affaan-m/ECC, the 197K-star octorato parallel) without staring at GitHub all day. Sibling of [[github-trending-curation]] (autonomous breadth) and [[repo-deep-learn]] (manual depth).
metadata:
  type: brain-routine
  trigger: cron (daily) — register in ~/dataqbs-local-cron/runner.py
  origin: repo-deep-learn — affaan-m/ECC 2026-05-28 + multi-agent design session (Workflow Architect + Trend Researcher)
---

# Repo Watch — Daily Competitor / Peer Pulse Monitor

## Why

Without it: you check competitor repos manually, miss the day they ship something interesting, copy late or not at all.

With it: a 30-second cron run identifies HIGH-SIGNAL changes (new agent / skill / architecture doc) and queues them for manual `/repo-deep-learn` analysis. LOW-SIGNAL (dep bumps, typos) gets logged and skipped.

**This is NOT trending discovery** ([[github-trending-curation]] does that). This is **targeted monitoring** of a known watchlist.

## How

```bash
# Manual one-shot
python3 ~/.claude/scripts/repo_watch.py                  # full pass
python3 ~/.claude/scripts/repo_watch.py --dry-run        # preview, no writes
python3 ~/.claude/scripts/repo_watch.py --only ECC       # single repo

# Cron registration (operator action — see "Cron setup" below)
```

## Architecture (design from Workflow Architect, 2026-05-28)

```
PHASE 1 — Bootstrap
  load watchlist.yaml → state.json → open digest <today>.md (append-safe)

PHASE 2 — Per-repo loop
  gh api commits/HEAD → SHA
  if SHA == last_seen → "no change" line, continue (idempotency anchor)
  gh api compare/<last>...<head> → diff files
  on force-push / missing last_sha → fallback to BASELINE (snapshot, no classify)

PHASE 3 — Classify
  HIGH   = file touches a `threshold_signal_paths` entry OR file-count ≥ threshold
  LOW    = changed files below threshold + outside signal paths
  EMPTY  = whitespace/binary only

PHASE 4 — Emission
  LOW   → row in digest, stop
  HIGH  → row + per-file detail + trigger marker at knowledge/repo-watch/triggers/<repo>-<sha>.trigger
          (file-based handoff to /repo-deep-learn; NEVER sync-invoke)

PHASE 5 — Persist
  atomic write state.json + close digest
```

**Lock file** (`state.json.lock`, 10-min stale-detection) prevents concurrent runs.
**Per-repo error isolation** — one bad repo doesn't abort the batch.
**`--dry-run`** shows what would happen without writing state/triggers/digest.

## Watchlist (`watchlist.yaml`)

Curated by Trend Researcher 2026-05-28 — initial 6 entries, **cap at 7**:

| Repo | Cadence | Why |
|---|---|---|
| `affaan-m/ECC` | daily | 197K-star MIT parallel; primary learning target |
| `wshobson/agents` | weekly | largest community persona collection |
| `hesreallyhim/awesome-claude-code` | weekly | aggregator → mindshare leading indicator |
| `disler/claude-code-hooks-mastery` | weekly | reference hooks impl |
| `anthropics/skills` | daily | upstream skill conventions |
| `anthropics/claude-plugins-official` | daily | official plugin marketplace |

**Drop a repo to weekly cadence** (or remove) when 3 consecutive digests yield zero "steal/decide" items.

## File-based trigger handoff to `/repo-deep-learn`

When HIGH-SIGNAL fires:
1. `knowledge/repo-watch/triggers/<owner-repo>-<sha-prefix>.trigger` is written.
2. Operator (or future scheduler) lists `~/.claude/knowledge/repo-watch/triggers/*.trigger`.
3. For each, runs `/repo-deep-learn <repo-url>` and deletes the trigger when done.
4. Triggers older than 30 days → log warning (analysis backlog).

**Why file-based, not in-process?** Architect's reason: deep-learn is a multi-minute LLM operation; chaining it inside the cron run turns a 5-second monitor into a flaky 10-minute job, masks failures, and blocks the next cron tick. Detection state ≠ action state.

## Cron setup (operator action — outside the brain)

Add to `~/dataqbs-local-cron/runner.py` near the existing Workflow definitions (~line 409):

```python
def cmd_brain_repo_watch(env):
    """Run the daily repo-watch monitor against the curated watchlist."""
    return (
        f"python3 {HOME}/.claude/scripts/repo_watch.py"
    )

# Then register:
Workflow("brain-repo-watch", Daily(hour=8, minute=15), cmd_brain_repo_watch),
```

Restart: `systemctl --user restart dataqbs-cron`. (Per the canonical procedure in [[lesson-dataqbs-cron-dns-cache-stuck]].)

## Anti-pattern callout (from Trend Researcher)

- **Don't watch >7 repos.** Beyond that, you read competitor commits before your own users' issues.
- **Don't auto-copy structure.** Any "inspired by X" pattern must pass `check-generic.py` AND be re-derived from first principles in a SKILL.md — never a verbatim port.
- **Don't watch SDK-layer projects** (humanlayer, etc.) unless you start shipping an agent runtime — wrong abstraction level.
- **Don't read digests per-commit.** Batch weekly, triage into decide/ignore/steal.
- **>20% of your roadmap traceable to "X shipped this"** = you've lost vision. Stop watching.

## Why this is healthy for octorato (right now)

- Brain is 4 months old, still establishing architectural patterns
- Direct parallel (ECC) is moving fast — daily-watch is justified WHILE we're extracting *architectural* lessons
- Will downgrade ECC to weekly once the deep-learn open questions are resolved
- Public brain + `check-generic.py` enforces no leakage; daily-watch just adds triage discipline on top

## See also
- [[github-trending-curation]] — autonomous breadth sibling (100 repos/day)
- [[repo-deep-learn]] — manual depth sibling (1 repo, full analysis); receives triggers from this skill
- [[lesson-dataqbs-cron-dns-cache-stuck]] — cron restart procedure
- [[no-history-in-docs]] — digests are append-only; don't try to "clean up" historical state

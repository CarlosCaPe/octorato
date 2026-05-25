# Self-Growth

> How Octorato grows itself — every day, on a schedule, without waiting for permission.

A brain that only changes when a human edits it falls behind the moment the human gets busy. The AI tooling market does not slow down for anyone: a new agent framework, a new MCP server, a new open-source replacement for some $50/mo SaaS ships **every single day**. Octorato treats *staying current* as a first-class system function, not a chore. This page documents the self-growth loop — the daily pipeline that scans the open-source frontier, decides how each discovery should integrate with what the brain already knows, and grows the brain (and the operator's public products) automatically inside a tight safety boundary.

Related reading: [[Skills-System]] (what a skill *is* and how it's loaded), [[Architecture]] (the Octopus brain/arm topology this loop lives inside), [[FinOps]] (the near-zero cost model that makes a daily LLM-gated loop affordable).

---

## 1. The Mission

**Stay current with a brutal, fast-moving market.**

The premise is uncomfortable but honest: an AI agent's value decays. The skills that made the brain sharp six months ago are now table stakes or already superseded by something open-source and better. If the brain doesn't actively hunt for what's new, it silently rots into a museum of last-year's best practices.

So the brain hunts. Daily. The mission has three parts:

1. **Surveillance** — watch the places where new AI/dev tooling actually surfaces first (GitHub, Hacker News, Product Hunt, short-form tech video), not where it gets written up three months later.
2. **Judgment** — most of what trends is noise: gag repos, tutorials, clones, demos. The brain must separate *a new capability* from *a new headline*.
3. **Integration** — a kept discovery isn't just filed away. It's woven into the connected graph of existing skills, published as a product update, and syndicated — turning the act of learning into traffic and credibility.

The brain is open-source and public ([github.com/CarlosCaPe/octorato](https://github.com/CarlosCaPe/octorato)); every growth decision it makes is visible in git history forever. That public-ledger property is *why* the loop is auditable by design (see [§7](#7-the-historymd-audit-ledger)).

---

## 2. The Daily Loop (07:30 UTC)

Once a day, the local cron supervisor (`~/dataqbs-local-cron/runner.py`, workflow `brain-trending-digest`) fires `github_trending_digest.py`, immediately followed by `trending-autopromote.py`. The whole pipeline is stdlib-Python + the `gh` CLI + one Groq call — no heavyweight dependencies.

```
                          ┌─────────────────────────────────────────────┐
   07:30 UTC  ───────────▶│  STAGE 1 · SCAN  (4 sources, parallel, 60s)  │
   (cron supervisor)      │                                              │
                          │   GitHub Trending   ── HTML scrape, top 100  │
                          │   Hacker News       ── Firebase API, top 30  │
                          │   Product Hunt      ── __NEXT_DATA__ scrape   │
                          │   TikTok #hashtags  ── yt-dlp metadata        │
                          └───────────────────────┬─────────────────────┘
                                                   │  (GitHub entries enriched
                                                   │   via `gh api repos/<n>`:
                                                   │   topics, total stars, push)
                                                   ▼
                          ┌─────────────────────────────────────────────┐
                          │  STAGE 2 · CLASSIFY  (heuristics, per item)  │
                          │                                              │
                          │   bucket  ∈ {skill | mcp | pattern |          │
                          │             paid-alternative | SKIP}          │
                          │   action  ∈ {ADD | MERGE-WITH | REPLACE |     │
                          │             EXTEND | SKIP}                     │
                          │   ▲ similarity gate: TF-IDF cosine vs the     │
                          │     connectome (query_connectome.py)          │
                          └───────────────────────┬─────────────────────┘
                                                   ▼
                          ┌─────────────────────────────────────────────┐
                          │  STAGE 3 · LLM QA GATE  (Groq llama-3.3-70b)  │
                          │                                              │
                          │   one batched prompt over the survivors:     │
                          │   "does this beat what we already have?"      │
                          │   → KEEP <reason> | DROP <reason>             │
                          └───────────────────────┬─────────────────────┘
                                                   ▼
                          ┌──────────────────────┬──────────────────────┐
                          │  digest <date>.md     │  sidecar <date>.json  │
                          │  (human-readable      │  (machine-readable,    │
                          │   + Notion mirror)    │   ALL candidates)      │
                          └──────────────────────┴───────────┬──────────┘
                                                              ▼
                          ┌─────────────────────────────────────────────┐
                          │  STAGE 4 · AUTO-PROMOTE  (autopromote.py)    │
                          │                                              │
                          │   filter: action == ADD  AND  llm == KEEP    │
                          │   cap:    ≤ 3 / day                           │
                          │   for each:  scaffold skill ─▶ /news article  │
                          │              ─▶ FB syndication ─▶ HISTORY.md   │
                          │   MERGE / REPLACE / EXTEND ─▶ left for human   │
                          └─────────────────────────────────────────────┘
```

### Stage 1 — Scan four sources

Fetched in parallel under a 60-second soft timeout (`ThreadPoolExecutor`, 4 workers). Any source that fails or times out degrades gracefully to empty — the loop never blocks on a flaky surface.

| Source | Access | Window | Why it matters |
|---|---|---|---|
| **GitHub Trending** | HTML scrape of `/trending?since=daily` (anchored on `<article class="Box-row">`), then `gh api repos/<owner>/<name>` for topics/stars/last-push | Top 100, daily | Where new OSS tools *first* gain velocity |
| **Hacker News** | Firebase API (`hacker-news.firebaseio.com`), no auth | Top 30 front-page | Practitioner signal + launch announcements |
| **Product Hunt** | `__NEXT_DATA__` initial-state scrape (GraphQL if `PRODUCTHUNT_TOKEN` set) | Today's launches | Productized tools, paid-alternative candidates |
| **TikTok hashtags** | `yt-dlp` flat-playlist metadata over `#devtools #opensource #ai #cli #developer` | 5/tag | Tech-curator channels surface tools before they trend on GH |

GitHub scraping is deliberately regex-anchored on the stable `Box-row` article block rather than a brittle CSS selector chain — GitHub removed `data-hovercard-type="repository"` (verified 2026-05-24) and the loop survived because it never depended on it.

### Stage 2 — Heuristic classify

Every candidate is assigned **two** independent labels:

- a **bucket** — *what kind of thing is this?* (`skill-candidate`, `mcp-candidate`, `pattern-reference`, `paid-alternative`, or `SKIP`)
- an **action** — *how should it integrate?* (the harmonization model, [§3](#3-the-harmonization-model))

Bucket assignment runs cheap regexes over name + description + topics: MCP keywords → `mcp-candidate`; "alternative to <SaaS>" → `paid-alternative`; architectural keywords (durable objects, RAG, agent framework, sandbox, eval harness) → `pattern-reference`; action-verb + brain-topic-vocab overlap → `skill-candidate`; nothing → `SKIP`.

### Stage 3 — LLM QA gate

The heuristic survivors go through one **batched** Groq call (`llama-3.3-70b-versatile`, `temperature=0`). A single prompt lists every survivor; the model returns exactly N lines of `KEEP <reason>` / `DROP <reason>`. Cost is roughly 20–30 items in one call per day — negligible (see [[FinOps]]). If `GROQ_API_KEY` is absent or the call fails, the loop surfaces the heuristic survivors as-is rather than crashing.

> **Hard-won detail:** Groq sits behind Cloudflare, which 403s the default `Python-urllib` user-agent with "error code: 1010". A browser-like UA gets through. The loop ships that UA.

### Stage 4 — Outputs

Two files per day, plus optional Notion mirror:

- **`~/.claude/knowledge/github-trending/<date>.md`** — the human digest the operator skims over coffee. Grouped by bucket, each entry showing action, best brain match, similarity, rationale, and LLM verdict.
- **`~/.claude/knowledge/github-trending/<date>.json`** — the machine sidecar carrying **all** candidates including SKIPs *with their reasons*. This is what the autopromote step and the audit ledger consume.
- **Notion page** "GH Trending — <date>" when `NOTION_TOKEN` is set.

---

## 3. The Harmonization Model

> **The brain is a connected graph, not a pile of skills.**

This is the principle that separates Octorato's growth from "just `git add` whatever trended." Adding skills indiscriminately produces a junk drawer: three overlapping skills for the same job, no idea which to load, duplicated and drifting advice. So every candidate doesn't get a binary yes/no — it gets an **integration action**, an instruction for *how* to weave it into the existing graph.

| Action | Meaning | Effect on the brain |
|---|---|---|
| **ADD** | Net-new capability, no meaningful overlap | New `skills/<name>/SKILL.md` |
| **MERGE-WITH:`<skill>`** | Real overlap; brings a new angle to an existing skill | Append a section to the incumbent — *consolidate, don't fragment* |
| **REPLACE:`<skill>`** | Strong overlap **and** the candidate is clearly more mature | Mark incumbent `deprecated: true`, add `replaced_by`; new skill carries a migration section |
| **EXTEND:`<skill>`** | Adjacent pattern under an existing umbrella | New sub-skill `<skill>--<sub>` with `parent:` front-matter |
| **SKIP** | Incumbent already covers it and candidate isn't materially better | Nothing changes |

### The similarity gate (connectome TF-IDF cosine)

The action is chosen by measuring how close the candidate is to what the brain already knows. The loop calls `query_connectome.py` — the same TF-IDF + cosine-similarity graph over every skill/agent that drives agent selection elsewhere (`neural_map.json`, see [[Architecture]]). It returns the **best-matching existing skill** and a similarity **score** in `[0,1]`.

```
similarity < 0.25            →  ADD                 (no overlap — net-new)
0.25 ≤ similarity < 0.55     →  EXTEND  (if pattern-reference)
                                MERGE-WITH (otherwise)   ← real overlap, new angle
similarity ≥ 0.55            →  REPLACE (if beat-factor clears) | SKIP
```

### The beat-factor

When similarity is high (`≥ 0.55`), the candidate genuinely competes with an incumbent skill. Replacing a working skill is a real cost, so the loop demands evidence the newcomer is actually better. The **beat-factor** (default `2.0`) is the bar: the candidate only earns `REPLACE` if its maturity proxy (total GitHub stars) exceeds `beat_factor × incumbent_proxy`. Otherwise the incumbent wins and the action falls back to `SKIP`. The brain is biased toward keeping what works unless something is *demonstrably* better — not merely newer.

Both thresholds and the beat-factor are config (`classifier.similarity_threshold`, `classifier.beat_factor`) so the operator can tune how eager the loop is to churn the graph.

---

## 4. The Safety Boundary

Full daily autonomy with zero human-in-the-loop would be reckless. The line is drawn precisely:

> **Only `ADD` auto-applies. Everything that touches or deprecates an existing skill waits for a human.**

`trending-autopromote.py` enforces this:

- **Auto-promote eligibility** = `action == ADD` **and** `llm_verdict == KEEP`. Net-new skills with no overlap and an explicit LLM keep. Nothing else.
- **MERGE-WITH / REPLACE / EXTEND are never applied unattended.** They modify, consolidate, or deprecate existing skills — decisions with blast radius. They're written into the digest and the [[#7-the-historymd-audit-ledger|HISTORY ledger]] under **"Needs operator review"** and wait for a manual `/trending-promote`.
- **Daily cap of 3.** A blockbuster trending day can't flood the brain with 30 stubs. Surplus `ADD`s are left in the digest for the operator to promote by hand.
- **Idempotent.** A candidate whose skill directory already exists is skipped — safe to re-run, safe to backfill.

The rationale: the worst an unattended `ADD` can do is create a redundant stub skill (cheap to delete, flagged as auto-promoted, low blast radius). The worst an unattended `REPLACE` could do is silently deprecate a skill the operator actively relies on. Asymmetric risk → asymmetric automation.

---

## 5. Two Sources of Growth

External trending is only half the story. The brain grows from two directions.

### External — the market frontier

The daily loop above. The world's open-source output, filtered down to *what beats what we have*. This is how the brain stays aware of tools and patterns it would never have invented on its own.

### Internal — the brain's own experience

The brain also learns from itself. Two internal streams feed the same skills tree:

- **Session logs** — patterns the agent hits repeatedly across sessions. When a workaround or technique recurs (the convention is **3+ times**), the `skill-creator` reflex distills it into a generic skill. Lessons from errors get captured the same way (see `skills/skill-creator/SKILL.md` and the auto-memory ledger).
- **The operator's manual skills** — when the operator hand-writes or hand-edits a skill, that's a deliberate signal mined into the same graph and subject to the same harmonization (does it overlap an existing skill? should it merge?).

External keeps the brain *current*; internal keeps it *coherent with its own lived experience*. Both flow through the connectome so neither produces fragmentation. (Note: internal arm-derived patterns are **anonymized to generic skills before** they enter the public brain — see the Upward Learning rule in [[Architecture]].)

---

## 6. Publication — Learning Becomes a Product

A promotion isn't just a brain edit. Each `ADD` cascades into three artifacts:

1. **The skill** — `~/.claude/skills/<name>/SKILL.md` is scaffolded with front-matter (`name`, `description`, `source`, `discovered_on`, `via: github-trending-curation`) and a stub body: *what it is*, *why it entered the brain*, *how to use* (TODO), *related skills* (TODO). The stub exists so the capability is **registered and discoverable immediately**; it's fleshed out on first real use.
2. **A `/news` changelog article** — the skill is turned into an article on **dataqbs.com/news** (Octorato's product changelog). Crucially, it **credits the source repo** by name and link. The framing is deliberate: *a community to grow with*, not a community to quietly strip-mine. Every growth event publicly acknowledges the open-source work it learned from.
3. **Social syndication** — the published article is then queued to the operator's social channels (e.g. the dataqbs Facebook Page) by the machine-local publishing layer described in the *Generic-brain boundary* note below.

### The business angle: SEO + traffic rotation

This loop is also a content engine. A self-growing brain produces a steady cadence of genuine, dated, source-cited changelog entries on **dataqbs.com/news** and **/blog** — exactly the fresh, topical, keyword-rich content search engines reward. Because the operator runs several public sites, the published growth events double as **traffic-rotation fuel**: each promotion is simultaneously a brain improvement *and* a marketing asset, at near-zero marginal cost. Learning pays for itself. (Cost envelope in [[FinOps]].)

> **Generic-brain boundary:** the skill content written into `~/.claude/` stays generic and public. The dataqbs-specific machinery (repo URL, FB bridge endpoint, secrets) lives in `~/dataqbs-local-cron/` (machine-local, gitignored) and never enters the public brain. dataqbs and dataqbs.com are the operator's own public products and may be named; no dataqbs *client* names ever appear.

---

## 7. The HISTORY.md Audit Ledger

`~/.claude/knowledge/github-trending/HISTORY.md` is the **append-only growth ledger** — the single file that answers "what has the brain been doing while I wasn't watching?" Each day appends one section:

```
## 2026-05-24
Scanned 46 · auto-promoted 0 · needs-review 0 · skipped 46

✅ Auto-promoted (added to brain → /news → FB):
   - `<slug>` ← owner/repo (url)

⏸ Needs operator review (touches existing skills — NOT auto-applied):
   - owner/repo → `MERGE-WITH:<skill>` — <rationale>

⏭ Skipped (had brain-fit, judged not worth adding):
   - owner/repo — <why it lost>

(+N with no brain-fit signal — not listed)
```

The three explicit categories — **added / deferred / ignored-with-reason** — are the point. The ledger doesn't just record what entered the brain; it records what was *deliberately left out and why*. This makes unattended growth **fully auditable on the operator's own cadence**: the operator can scroll the timeline whenever they like and **challenge any ignored item** — "why did you skip X on the 24th?" — and the answer is right there (the similarity score, the beat-factor verdict, or the LLM's drop reason). Autonomy without an audit trail is just drift; the ledger is what makes the autonomy trustworthy.

---

## 8. Site Semantic Versioning

Every growth event leaves a version footprint on the public site, and **who triggered it determines which segment bumps**:

| Trigger | Bump | Meaning |
|---|---|---|
| **Bot identity** (`blog-bot` / `dataqbs-bot` / auto-promote) | **PATCH** | Routine self-growth — a skill stub + changelog entry committed by automation |
| **Operator** (manual edit, manual `/trending-promote`, hand-written skill) | **MINOR** | A deliberate human change |
| **`Octorato-Major:` commit trailer** | **MAJOR** | An architectural / breaking change the operator explicitly flags |

The mechanism is the post-commit hook reading the commit author: a bot-identity commit bumps PATCH, so the daily auto-promotion flow increments the patch version without inflating the human-meaningful version numbers. The operator's own work moves MINOR; only an explicit `Octorato-Major:` trailer moves MAJOR. The version string on the site thus encodes *how much the brain grew by itself* versus *by hand* versus *by design decision* — readable at a glance.

---

## 9. Operate It

**Automatic:** runs daily at 07:30 UTC via the cron supervisor. Nothing to do — read the digest over coffee.

**Manual / backfill:**

```bash
# Generate today's digest (or backfill a past date)
python3 ~/.claude/scripts/github_trending_digest.py
python3 ~/.claude/scripts/github_trending_digest.py --date 2026-05-23
python3 ~/.claude/scripts/github_trending_digest.py --dry-run    # print, don't write
python3 ~/.claude/scripts/github_trending_digest.py --no-llm     # heuristic-only

# Auto-promote the safe (ADD + KEEP) candidates, cap 3
python3 ~/dataqbs-local-cron/scripts/trending-autopromote.py --dry-run
python3 ~/dataqbs-local-cron/scripts/trending-autopromote.py --max 3

# Promote one candidate by hand (the only path for MERGE / REPLACE / EXTEND)
/trending-promote 2026-05-24 owner/repo-name
```

**Tune behavior** via the skill front-matter / env (`classifier.similarity_threshold`, `classifier.beat_factor`, `classifier.llm_gate`, source `enabled` flags, `outputs.notion`).

---

## See Also

- [[Skills-System]] — what a skill is, how SKILL.md front-matter works, how skills are loaded
- [[Architecture]] — the Octopus brain/arm topology, the connectome, Upward Learning / Downward Distribution
- [[FinOps]] — the cost envelope (one Groq call/day, stdlib pipeline) that makes daily LLM-gated curation viable
- `skills/github-trending-curation/SKILL.md` — the routine's own spec and config block
- `skills/skill-creator/SKILL.md` — the internal-growth (session-mined) counterpart

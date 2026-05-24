---
description: Promote a candidate from the daily GH-trending digest to a real brain skill + auto-publish a news article and push to dataqbs FB Page in one shot.
argument-hint: <YYYY-MM-DD> <owner/repo>
allowed-tools: Bash, Read, Edit, Write
---

# /trending-promote — Candidate to Skill in one shot

**Args:** `$ARGUMENTS` (expected: `<YYYY-MM-DD> <owner/repo-or-source-slug>`)

## Pre-flight

1. Parse arguments: first token is the digest date (YYYY-MM-DD); second is the candidate identifier as it appears in the digest (`owner/repo` for GitHub, the full `TT[tag] @uploader: title` or `HN: title` for other sources — easiest: copy the full backticked name from the digest).
2. Read the digest file: `~/.claude/knowledge/github-trending/<date>.md`. If the file is missing, abort with a clear error pointing the operator at the daily cron.
3. Find the entry block whose first heading contains the candidate. Extract:
   - **action** (`ADD` | `MERGE-WITH:<skill>` | `REPLACE:<skill>` | `EXTEND:<skill>` | `SKIP`)
   - **bucket** (skill-candidate / mcp-candidate / pattern-reference / paid-alternative)
   - **best brain match** + similarity
   - **URL**, **description**, **topics**, **language**
4. If `action == SKIP`, abort with "this candidate was already classified as SKIP; promote anyway? (rerun with --force)" — never silently bypass the harmonization decision.

## Behavior per action

### action = ADD — net-new skill

1. Compute `<skill-name-kebab>` from the candidate (slug it, max 60 chars, alpha-numeric + hyphens only).
2. Create `~/.claude/skills/<skill-name-kebab>/SKILL.md` with:
   - YAML front-matter: `name`, `description` (1-line, from digest), `metadata: { type, source, discovered_on }`
   - Body: `## What it does`, `## Why we added it`, `## How to use` (TODO checklist), `## Related skills` (link to nearest brain match for cross-reference, even though similarity was low — homologation)
3. Update `~/.claude/MEMORY.md`: add a single reference-type entry pointing at the new skill, format: `- [<title>](<file>) — one-line hook`.
4. Hand off to the news/FB pipeline (see "Cross-cutting publish" below).

### action = MERGE-WITH:<existing-skill>

1. **Do NOT create a new skill directory.** Locate `~/.claude/skills/<existing-skill>/SKILL.md`.
2. Append a section to that file:
   ```
   ## Update <YYYY-MM-DD> — merged trending signal: <candidate-name>

   - Source: <url>
   - Discovered via /trending-promote on <date>
   - Why merged here (not new skill): <action rationale from digest>
   - New angle this brings: <one paragraph the operator fills>
   ```
3. The intent is **integration, not fragmentation** (per operator instruction "armonizar, homologar, integrar"). The existing skill grows.
4. Hand off to the news pipeline as an "update to existing skill" article (different headline pattern than ADD).

### action = REPLACE:<existing-skill>

1. Mark the incumbent: in `~/.claude/skills/<existing-skill>/SKILL.md` front-matter, set `deprecated: true` and add a `replaced_by: <new-skill>` field.
2. Create `~/.claude/skills/<new-skill-kebab>/SKILL.md` (same as ADD).
3. Add a `## Migration from <existing-skill>` section in the new SKILL.md explaining the upgrade path.
4. News article framing: "we're swapping X for Y because Z".

### action = EXTEND:<existing-skill>

1. Create `~/.claude/skills/<existing-skill>--<sub-slug>/SKILL.md` (the `--` is the convention for sub-skills under an umbrella).
2. In its front-matter, set `parent: <existing-skill>`.
3. In the incumbent's SKILL.md, add a "Sub-skills" section listing the new one.
4. News article framing: "we extended X with sub-skill Y for Z".

## Cross-cutting: publish news + post to FB

After any of the above (except SKIP), in order:

1. `cd ~/dataqbs-local-cron/bot-worktree && git fetch origin main --quiet && git reset --hard origin/main --quiet`
2. Run the existing news pipeline: `cd projects/dataqbs_site && npx tsx scripts/news/skill-to-news-article.ts <skill-name-kebab>` — writes `src/content/news/<date>-<slug>.md`.
3. The post-commit hook (F3) will auto-bump PATCH on the next commit. Make sure the commit author is a bot identity (`blog-bot` / `dataqbs-bot`) so PATCH (not MINOR) is bumped.
4. Commit + push to main: standard bot-worktree pattern, `--no-verify`, `git push https://x-access-token:$BLOG_BOT_PAT@github.com/CarlosCaPe/dataqbs_site.git HEAD:main`.
5. POST to `https://www.dataqbs.com/api/multireach/internal/news-bridge` with `{"slug":"<date>-<slug>"}` and `X-Scheduler-Secret`. The bridge queues a multireach Post for the dataqbs FB Page; `multireach-scheduler` publishes ~60s later.

## Output

When done, print a single summary block:

```
✅ Promoted <candidate> with action=<ACTION>
   Brain:    ~/.claude/skills/<name>/SKILL.md
   News:     <site>/news/<date>-<slug> (PR / direct on main)
   FB Page:  multireach post <post-id> queued
   Version:  bumped <X.Y.Z-1> → <X.Y.Z> (PATCH, bot identity)
```

## Failure modes

- Digest file missing → fail loud, point at the cron.
- Action = SKIP → ask for `--force` to bypass; never silently promote a SKIP.
- Bot-worktree dirty → fail loud, don't try to recover (operator inspects).
- `skill-to-news-article.ts` exit code ≠ 0 → keep the skill change (rollback only if news commit fails entirely).
- FB bridge HTTP ≠ 201/200 → log + continue (news is committed; FB can be retried via `fb-publish-news` cron).

## Notes on harmonization

This command is the operationalization of the operator's principle: **the brain is a connected graph, not a pile of skills**. Every promotion considers integration with what's already there, not just addition. The classifier's `action` field is the operator-instruction layer that makes this happen — never bypass it, never default to ADD when the digest said MERGE.

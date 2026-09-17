---
name: claude-mem-persistent-memory
description: "Persistent cross-session memory for coding agents: captures the session, compresses it and re-injects what is relevant later, with ~75% fewer tokens. Apache-2.0 upstream, permissive."
metadata:
  origin: "https://github.com/thedotmack/claude-mem. This skill DECLARES no license and its manifest carries the repo default over ORIGINAL text (measured against the upstream README at the entry ref eb6344a6: ratio 0.0211, longest shared run 15 characters). The TOOL was Apache-2.0 when this entered on 2026-05-18, relicensed from AGPL-3.0 on 2026-05-08 (36b0929f). Four earlier lines here asserted AGPL 3.0 and gave copyleft advice from it; they were already false on the day they were written and are corrected."
---

# claude-mem — Persistent Memory for Claude Code

Brain-multiplier skill. Compresses past sessions into structured context and re-injects only the relevant chunks into future sessions. The reported token savings: **~75% per session**. Effect on the Octopus: every arm's runtime budget multiplies, every long engagement gets cross-session memory automatically.

## When to use

- A client engagement spans many sessions and context drift is hurting quality
- Token spend is the bottleneck on a high-frequency arm
- You want session-to-session continuity that survives `/clear`, compaction, and machine switches
- You're evaluating whether to standardize cross-session memory across all arms

## When NOT to use

- One-shot tasks (overhead not worth it)
- Arms whose deliverables cannot carry a third-party dependency at all. The copyleft objection that used to sit here was about AGPL and does not apply: upstream has been Apache-2.0 since 2026-05-08. See "License caveat" below for what to check instead
- Engagements where the brain's existing auto-memory at `~/.claude/projects/<arm>/memory/` already covers the need (it's lighter, no compression, no ChromaDB)

## Source of truth

- Repository: `github.com/thedotmack/claude-mem` (76.5k+ stars at time of writing — verify current state)
- License: **Apache-2.0** upstream since 2026-05-08 (36b0929f), before this skill entered on 2026-05-18. It was AGPL-3.0 until then, which is what an older reading of this repo would tell you, so check the LICENSE at the commit you actually vendor.
- Requires: Node >= 18, ChromaDB (vector store) running locally
- Compatible agents per repo: Claude Code, OpenClaw, Codex, Gemini, Hermes, Copilot, OpenCode and more
- Local viewer UI typically at `localhost:37777`

## What it does technically

1. Hooks into the agent's session lifecycle (start, end, key tool calls)
2. Captures: what was investigated, learned, completed, what's next
3. Embeds + compresses into ChromaDB
4. On next session start, retrieves the top-K most relevant compressed memories for current context
5. Injects them as system context so the agent resumes with continuity

## Quick start (rough — verify against current README)

```bash
# Install (npm/npx route)
npx claude-mem init
# This typically: configures hooks in ~/.claude/settings.json, starts ChromaDB, opens viewer
```

After install, the next Claude Code session writes session digests automatically, and subsequent sessions read them. Check `localhost:37777` to see what's been captured.

## License caveat (READ before embedding in client work)

This section used to say AGPL 3.0 and warn about network copyleft. That was WRONG at the time it was written: upstream relicensed to Apache-2.0 on 2026-05-08 (36b0929f), ten days before this skill entered the repo on 2026-05-18. Apache-2.0 is permissive and carries no network-copyleft trigger, so the warning was advice nobody needed against a license nobody had.

What survives is the method, not the verdict. A license is a fact about a DATE: read the LICENSE file at the exact commit you vendor, because this repo alone has been AGPL-3.0 and then Apache-2.0, and a skill that quotes yesterday's answer is a false claim about somebody else's terms.

**Safe usage patterns:**
- Personal / internal tooling (your laptop, your brain) — no issue
- Self-hosted on operator-owned infrastructure — no issue
- Embedded in a hosted SaaS delivered to clients — **legal review required**

When in doubt, treat it like running it inside your laptop is fine, redistributing it as part of a client product is not.

## Relationship to the brain's existing memory

The Octopus brain already has lightweight auto-memory under `~/.claude/projects/<sanitized-cwd>/memory/` (per CLAUDE.md). That system uses plain markdown files and is good for stable facts (user role, feedback, project context).

claude-mem is heavier and dynamic — it captures **session-level activity** and compresses it with embeddings. Complementary, not redundant:

| Need | Use |
|---|---|
| "Who is the user, what are their preferences" | Brain auto-memory (existing) |
| "What did the agent investigate / decide last Tuesday on this arm" | claude-mem |
| "Long-term project facts that won't change" | Brain auto-memory |
| "Compressed history of 50 prior sessions, retrievable by relevance" | claude-mem |

## Risk-aware rollout plan (recommended)

1. Pilot on ONE arm where token cost is high and engagements are long
2. Read the upstream LICENSE at the commit you pin and verify it is OK for that arm's deliverables
3. Measure: actual token-reduction vs claimed ~75%, retrieval quality, false positives
4. If pilot proves out, roll to other arms one at a time
5. Update CLAUDE.md to document the cross-session memory expectation

## Related brain assets

- Auto-memory at `~/.claude/projects/<arm>/memory/` (lightweight, complementary)
- `session-memory-search` skill (existing — searches across sessions via git log + grep, no embeddings)
- `progressive-code-exploration` skill (existing — token-efficient code reading)
- Sister pattern: `token-efficient-prompting` skill

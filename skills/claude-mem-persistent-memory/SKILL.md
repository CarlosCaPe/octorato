---
name: claude-mem-persistent-memory
description: "Persistent cross-session memory for coding agents: captures the session, compresses it and re-injects what is relevant later, with ~75% fewer tokens. AGPL 3.0, watch the copyleft in commercial deliverables."
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
- Highly sensitive arms where AGPL copyleft creates IP issues with client deliverables — see "License caveat" below
- Engagements where the brain's existing auto-memory at `~/.claude/projects/<arm>/memory/` already covers the need (it's lighter, no compression, no ChromaDB)

## Source of truth

- Repository: `github.com/thedotmack/claude-mem` (76.5k+ stars at time of writing — verify current state)
- License: **AGPL 3.0** ← read the License caveat section before adopting
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

AGPL 3.0 is **copyleft and triggers on network use**. If you embed claude-mem inside a hosted service you deliver to a client, that service's source code may need to be made available to its users under AGPL.

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
2. Verify AGPL is OK for that arm's deliverables
3. Measure: actual token-reduction vs claimed ~75%, retrieval quality, false positives
4. If pilot proves out, roll to other arms one at a time
5. Update CLAUDE.md to document the cross-session memory expectation

## Related brain assets

- Auto-memory at `~/.claude/projects/<arm>/memory/` (lightweight, complementary)
- `session-memory-search` skill (existing — searches across sessions via git log + grep, no embeddings)
- `progressive-code-exploration` skill (existing — token-efficient code reading)
- Sister pattern: `token-efficient-prompting` skill

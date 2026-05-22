---
name: phi-aware-rag-ingestion
description: "Multi-stage RAG ingestion pipeline for regulated content. Fetch → text-normalize → PHI-screen → chunk → embed → route → store → digest. Default-deny routing (local LLM for tainted, cloud LLM only for allowlisted clean sources). Per-user folder isolation via sha256(email)[:12]. Manual slash-command trigger principle for sensitive workloads."
metadata:
  short-description: "PHI-aware multi-stage RAG ingestion pipeline"
---

# PHI-Aware RAG Ingestion

## What

A reference architecture for ingesting collaboration-platform content (Teams chats, Outlook mail, calendar, SharePoint files, meeting transcripts) into a per-user vector store, with explicit routing of regulated content to a local LLM and clean content to a cloud LLM.

The pipeline is multi-stage and idempotent. Each stage is a small, replaceable module. The orchestrator runs them in order on every fetch.

## Why

Regulated engagements (HIPAA, GDPR, SOC-2, FedRAMP) often need RAG over collaboration content for legitimate productivity reasons (onboarding, decision archaeology, cross-source search). The naive approach — pipe everything through a cloud LLM — leaks regulated content the moment a single false-negative slips past the PHI detector.

This pipeline defaults to safety:
- **Source-aware override**: if the source is not on a clean-allowlist, content is routed to the local LLM regardless of what the regex / classifier says
- **Per-user folder isolation**: emails never appear in git history (sha256 slugs)
- **Manual trigger**: sensitive workloads do not run unsupervised — a human invokes the pipeline via slash command
- **Idempotent**: re-runs do not duplicate; failed runs do not advance the cursor
- **Local embeddings**: vectors of regulated content are themselves PHI-derivative; embed locally

## Pipeline Architecture

```
              human invokes: /<arm>-sync [args]
                         │
                         ▼
                    orchestrator
                         │
   ┌─────────────────────┼──────────────────────┐
   ▼                     ▼                      ▼
[1] FETCH         [2] NORMALIZE          [3] PHI SCREEN
 (per source,       (NFKC + sig/quote      (regex + classifier;
  delta-query)       strip; stable hash     L4 source allowlist
                     for idempotency)        forces phi_safe if
                                             source not clean)
                              │
                              ▼
                       [4] CHUNK
                       (paragraph-aware,
                        configurable token
                        size + overlap)
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
         partition='clean'             partition='phi_safe'
              │                               │
              ▼                               ▼
        [5] EMBED                       [5] EMBED
        cloud LLM                       local LLM
        (only if BAA                    (always; never
         confirmed)                      cloud)
              │                               │
              ▼                               ▼
        [6] SUMMARIZE                   [6] SUMMARIZE
        cloud LLM                       local LLM
              │                               │
              └───────────────┬───────────────┘
                              ▼
                       [7] STORE
                       (per-user vector
                        store + raw +
                        digest .md)
                              │
                              ▼
                       [8] DIGEST
                       (PHI-scrubbed daily
                        markdown, per-user)
                              │
                              ▼
                  update _cursor.json + _health.log
```

## Module Inventory

| Module | Responsibility | Reuse from existing skill |
|---|---|---|
| `lib/<source>-helpers.js` | Per-source API client (auth, pagination, delta queries) | `browser-bearer-graph-auth` for Microsoft Graph |
| `lib/text-normalize.js` | NFKC, signature/quoted-reply strip, HTML→text, stable hash for idempotency | — |
| `lib/phi-redact.js` | Regex layers (SSN, MRN, DOB, NPI, phone, email, Luhn-validated CC); confidence scoring | — |
| `lib/chunk.js` | Paragraph-aware chunker with configurable size + overlap | — |
| `lib/cosine.js` | Cosine similarity + topK | — |
| `lib/vector-store.js` | JSON-file vector store indexed by date (per-user dir) | — |
| `lib/ollama-client.js` | Local LLM client (chat + embed + classify) | — |
| `lib/<cloud-llm>-client.js` | Cloud LLM client (clean partition only) | — |
| `lib/user-paths.js` | sha256(email)[:12] slug → per-user folder paths | — |
| `<sync-tool>.js` | Orchestrator (one entry point per arm) | — |
| `.claude/commands/<arm>-sync.md` | Slash-command definition | — |

## Default-Deny PHI Routing

The L4 (source-aware) override is the most important safety property. It runs BEFORE any regex / classifier:

```js
function routeChunk(chunk, source, sourceAllowlist) {
  // L4: source-aware override
  if (!sourceAllowlist.has(source)) {
    return 'phi_safe';   // force local route regardless of regex
  }

  // L1-L3: regex + classifier + ML detector
  if (phiRegex(chunk)) return 'phi_safe';
  if (phiClassifier(chunk).confidence > 0.5) return 'phi_safe';
  if (phiMlDetector(chunk).hasPii) return 'phi_safe';

  return 'clean';        // cloud LLM eligible
}
```

Sample initial allowlist (compliance-revisable):

| Source | Clean? | Reason |
|---|---|---|
| Public Confluence space | Yes | Marketing / onboarding without clinical content |
| Public OSS GitHub repo | Yes | No regulated content by definition |
| Internal repo code (no comments-with-data) | Yes | Code itself shouldn't contain regulated content |
| Internal wiki | NO | Default deny — may contain clinical decisions |
| Direct chats | NO | Default deny |
| General team channels | NO | Default deny |
| Tickets / issue tracker | NO | Bug reports may include regulated content |

Override only with **written approval from a Compliance Officer**. Document the allowlist in YAML, not in code, and audit every override.

## Per-User Folder Isolation

```
<arm>/users/<sha256(email)[:12]>/
├── _cursor.json                  ← last sync timestamp [GITIGNORED]
├── _health.log                   ← NDJSON ops events [GITIGNORED]
├── _inventory.json               ← discovery output [GITIGNORED]
├── transcripts/                  ← raw text [GITIGNORED — encrypt before commit]
├── raw/<date>/                   ← raw API payloads [GITIGNORED — encrypt before commit]
├── embeddings/<date>.json        ← chunk index [GITIGNORED — encrypt before commit]
└── digests/<date>.md             ← PHI-scrubbed daily summary [TRACKABLE]
```

Mapping: `<arm>/users/INDEX.md` keeps the slug → email mapping (clear; not regulated). The slug keeps emails out of git history even if the inventory ever leaks.

## Idempotency via Text Normalization

Re-runs must NOT create duplicate chunks. The pipeline normalizes text BEFORE hashing:

1. Unicode NFKC normalization (collapses width / compatibility differences)
2. Strip HTML tags (Outlook bodies arrive as HTML)
3. Strip email signatures (regex on `^-- $` and "Sent from" sentinels)
4. Strip quoted-reply blocks (`^>` lines, `On <date> <person> wrote:` headers)
5. Hash the normalized text → use as the chunk dedup key

Without normalization, the same chat with a slightly different signature line creates a new chunk every sync. With normalization, re-syncs are no-ops on already-seen content.

## Manual Trigger Principle (No Scheduler for Regulated Content)

Sensitive workloads do not run unsupervised. The pipeline is invoked by a human via:

```bash
/<arm>-sync                    # incremental sync (default)
/<arm>-sync --health           # check token + LLMs, no fetch
/<arm>-sync --discovery-only   # list accessible sources
/<arm>-sync --dry-run          # show plan, write nothing
/<arm>-sync --since YYYY-MM-DD # backfill from date
/<arm>-sync --no-summary       # raw capture only, skip LLM
```

Why no scheduler:
- Regulated workloads should not be running while no one is watching
- A token expiry / API throttle / unexpected payload should produce immediate human attention, not a silent failure log
- Audit trails are easier when every run has a known invoker
- The slash command is the unit of human consent

## Health-Check Discipline

Every run starts with a health check that exits early on failure:

```
[1] graph token present + valid for ≥5 min?
[2] local LLM (ollama or equivalent) responding on localhost?
[3] cloud LLM API key present + reachable (if used)?
[4] vector store dir writable + per-user paths exist?
[5] disk space ≥ 100MB free?
```

If any fails, exit code 2 with a specific message. Do not proceed to fetch.

## Fail-Closed Exit Codes (Mandatory Discipline)

Every script in this pipeline family (ingestion, triage, classifier, ad-hoc queries) MUST honor the same exit code semantics. This is the contract that lets a wrapping shell script / cron / CI reliably distinguish "needs operator attention" from "transient infra failure":

| Code | Meaning | Wrapper response |
|---|---|---|
| `0` | Success — all items processed cleanly | Continue / no alert |
| `1` | Generic failure (network, parse error, unexpected) | Retry with backoff; alert after 3 |
| `2` | Auth failure (missing token, expired refresh, scope insufficient) | Halt; surface to operator immediately. Re-auth required. |
| `3` | **PHI detected AND local LLM unavailable** — refused to degrade to cloud | Halt; surface to operator. Start ollama and re-run. |

Exit code 3 is the codified version of the fail-closed posture. The pipeline does NOT silently route PHI items to cloud as a "best-effort" when ollama is down. It refuses, reports which items were blocked, and exits non-zero.

```js
// canonical exit logic at end of orchestrator main()
if (phiBlockedCount > 0 && !ollamaAvailable) {
  console.error(`⚠ ${phiBlockedCount} item(s) contained PHI but ollama is down — could not classify.`);
  console.error('  Start ollama: `ollama serve` (then pull the local LLM model)');
  process.exit(3);
}
```

**Why a distinct code (not just 1)**:
- A monitoring system needs to distinguish "infra glitch, retry" (code 1) from "policy guardrail held, human action required" (code 3)
- Exit 3 documents the fact that PHI was correctly detected and correctly NOT sent to cloud — that's a success-of-policy event worth surfacing, not just a generic failure
- Operators can build wrappers like `&& notify` or `|| start-ollama-and-retry` that branch on the code

**Anti-pattern**: catching the ollama-unavailable case and falling back to Groq with a warning log. This is the worst possible silent failure — the operator never knows PHI was leaked. There is no fallback. Halt with exit 3.

Validated against ADH on 2026-05-22: with ollama deliberately stopped, 1/5 inbox items was correctly marked PHI-blocked (exit 3); subsequent run with ollama started successfully classified all 5 with zero cloud egress on the PHI-tainted item.

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| Cloud LLM by default with regex as the only filter | First clinical-shorthand example ("patient JS dob 4/12 was no-show") bypasses every regex. Default-deny is the only safe posture. |
| Same key directory for embeddings and raw text | Embeddings are PHI-derivative; treat them as regulated. They go in the `users/<slug>/embeddings/` regulated-encrypted path. |
| Storing raw email addresses as folder names | Leaks identity even when content is encrypted. Use sha256 slugs. |
| Auto-scheduling the pipeline | Sensitive workload running unsupervised. Move to manual slash-command. |
| Skipping text normalization before hashing | Re-runs duplicate every chunk. Vector store explodes. |
| Health check that "fails open" on missing LLM | Pipeline silently routes everything to cloud as fallback. Worst possible default. |
| One global allowlist instead of per-arm | Different arms have different sensitivity profiles. Allowlist is per-engagement, never global. |

## Composability

- `browser-bearer-graph-auth` — provides the bearer token for Microsoft Graph fetches
- `inbox-triage-classifier` — reuses this skill's PHI screen + dual-route LLM, but for stateless classification (not RAG ingestion). Shares `phi-redact.js`, `text-normalize.js`, `ollama-client.js`, `groq-client.js`, `user-paths.js` modules verbatim.
- `stream-transcript-dom-scrape` — provides the transcript text input when file-ACL blocks download
- `sops-age-git-encryption` — encrypts the regulated paths (`transcripts/`, `raw/`, `embeddings/`) before commit
- `mcp-stack-setup` (existing) — exposes the resulting vector store via MCP tool calls (e.g., `mcp-teams.search_messages`)
- `security-threat-model` (existing) — threat model justifies the default-deny posture

## Lessons Learned

- The L4 source-aware override is the difference between a safe pipeline and a leak. Without it, regex false-negatives leak. With it, false-negatives still don't leak because the source itself isn't allowlisted.
- Idempotency is non-negotiable. The first re-run that duplicated 76 chunks taught us to normalize before hashing. After normalization, re-runs are exact no-ops on unchanged content.
- Manual slash-command trigger is the right default for regulated workloads. Daily Task Scheduler runs were removed from one engagement after a near-miss with token expiry during an unattended overnight run.
- Per-user sha256-slug folders keep the per-user dir structure stable while keeping email addresses out of git. `users/INDEX.md` provides the mapping for ops; transcripts and raw are stored under the slug.
- Cloud LLM fallback should be a build-time choice, not a runtime fallback. If the local LLM is down, the pipeline halts with exit code 2 — it does not fall back to cloud.

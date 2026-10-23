---
name: inbox-triage-classifier
description: "Triage for inboxes (email, Slack, Teams, JIRA, PRs): classifies what needs action and returns a per-item verdict with urgency. Read-only, never marks as read and never replies. Use it on 'que tengo pendiente?', 'do I owe anyone a reply?'."
metadata:
  short-description: "PHI-aware triage classifier for inbox-like streams"
---

# Inbox-Triage Classifier

## What

A general-purpose classification pipeline that scans a stream of items (emails, chat messages, tickets, mentions) and tells the operator which ones require their attention — with structured reasons and suggested actions, sorted by urgency.

This is the **discovery layer** for "what do I owe anyone today?" workflows. It is intentionally read-only and does not write back to the source (no marking read, no draft replies, no status changes).

## Why

`phi-aware-rag-ingestion` solves the problem of *building a searchable corpus* from regulated content. That's the wrong tool for "tell me what to act on today" because:

- Retrieval-via-query assumes you know what you're looking for. Triage assumes you don't.
- RAG outputs document chunks. Triage outputs verdicts (`needs_followup: bool` + urgency + suggested action).
- RAG runs as a background sync. Triage is a synchronous read on the current state of the inbox.
- RAG accumulates state (vector store, cursor). Triage is stateless.

The plumbing (auth, PHI screen, dual-route LLM) is shared. The downstream goal is not.

## When to Use

Trigger when the operator asks:

- "What do I need to follow up on in my inbox / Slack / Teams?"
- "Do I owe anyone a reply?"
- "What's the most urgent thing in my queue right now?"
- "Triage my JIRA / GitHub / Notion mentions"
- "Read my mail and tell me what's actionable"

Do NOT use for:
- Drafting replies (separate skill / step)
- Building a searchable archive (use `phi-aware-rag-ingestion`)
- Bulk export / backup (use a dedicated scraper)
- Anything that writes back to the source

## Pipeline

```
            operator invokes: /<arm>-triage <source> [args]
                                       │
                                       ▼
                                  orchestrator
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
    [1] FETCH                  [2] NORMALIZE                  [3] PHI SCREEN
    delta-query for             strip HTML, sigs,             regex + (optional)
    last N days,                quoted replies; build         classifier; mark
    READ-ONLY                   stable hash                    each item phi or clean
                                       │
                                       ▼
                              ┌────────┴────────┐
                              ▼                 ▼
                         clean items      phi-tainted items
                              │                 │
                              ▼                 ▼
                    [4a] CLASSIFY        [4b] CLASSIFY
                    cloud LLM            local LLM
                    (Groq / OpenAI)      (ollama)
                              │                 │
                              └────────┬────────┘
                                       ▼
                          [5] STRUCTURED VERDICT
                          { needs_followup: bool,
                            reason, suggested_action,
                            urgency: low|med|high,
                            phi: bool, llm: str }
                                       │
                                       ▼
                               [6] SORT + REPORT
                               sort by urgency, then
                               by recency; print to
                               stdout (+ optional
                               PHI-redacted digest)
```

## Classifier Contract (Mandatory Schema)

The LLM must return a single JSON object with this exact shape. No prose, no markdown, no code fence.

```json
{
  "needs_followup": true,
  "reason": "<=120 chars — why this needs attention",
  "suggested_action": "<=140 chars — what the operator should do",
  "urgency": "low" | "med" | "high"
}
```

**Urgency calibration (consistent across all sources)**:

| Level | Trigger |
|---|---|
| `high` | Explicit deadline today/tomorrow OR explicit blocker on a third party |
| `med` | Soft deadline this week OR external party waiting OR named stakeholder asks directly |
| `low` | No deadline, internal nudge, "when you get a chance", informational reply expected |

**Conservative bias**: when uncertain, the classifier should default to `needs_followup=false` rather than invent urgency. False positives waste operator attention; false negatives are recoverable on the next run.

## Sandwich System Prompt (Critical)

Smaller models (7B-13B local) lose attention on rules placed only at the top. Use the sandwich pattern:

```
# GOLDEN RULES (must obey)
- Output ONLY a single JSON object — no prose, no markdown, no code fence.
- Schema: {"needs_followup": boolean, "reason": "...", "suggested_action": "...", "urgency": "low"|"med"|"high"}
- needs_followup=true only if the item expects an action from the recipient.
- needs_followup=false for FYI broadcasts, auto-notifications, newsletters, already-handled invites.
- Be conservative: when uncertain, prefer needs_followup=false.

# TASK
Classify whether <RECIPIENT_NAME>, a <RECIPIENT_ROLE>, needs to follow up on this <ITEM_TYPE>.

# REMEMBER
- JSON only. No invention. Concrete actions, not vague advice.
```

The `# REMEMBER` block at the bottom is non-negotiable for local models. Without it, ollama llama3.1:8b drifts to markdown 1-in-5 runs.

## Per-Item User Message Template

```
Subject: <subject>                    # or: Channel: <channel>, Ticket: <id>
From: <name> <<email/handle>>
Received: <ISO datetime>
Read: <yes|no>                        # if source supports unread state
Importance/Priority: <normal|high>
Flag: <followup|completed|none>       # if source supports flags

---
<first 3500 chars of normalized body>
```

3500 chars is the sweet spot for Groq llama-3.3-70b and ollama llama3.1:8b. Going higher buys marginal classifier quality at large latency / cost.

## Dual-Route LLM (Reuse `phi-aware-rag-ingestion`)

```js
async function classifyItem(item, normalizedText, ctx) {
  const phiRisk = phi.isPhiRisk(normalizedText, { strictness: 'medium' });
  const messages = [
    { role: 'system', content: SANDWICH_SYSTEM },
    { role: 'user',   content: buildUserMessage(item, normalizedText) },
  ];

  if (phiRisk) {
    if (!ctx.ollamaAvailable) {
      // FAIL CLOSED — do NOT degrade to cloud
      return { error: 'PHI detected but ollama unavailable', phi: true, llm: 'none' };
    }
    return await ollama.chat(messages, { maxTokens: 180, temperature: 0 });
  }
  return await groq.chat(messages, { maxTokens: 180, temperature: 0 });
}
```

PHI policy is non-negotiable: if `phiRisk && !ollamaAvailable`, the item is **not classified** — it is reported as blocked with exit code 3 (see `phi-aware-rag-ingestion` §Fail-Closed Exit Codes).

## CLI Flags (Convention Across Implementations)

| Flag | Default | Effect |
|---|---|---|
| `--days N` | 7 | Time window in days |
| `--limit N` | 50 | Max items to process |
| `--unread-only` | false | Filter to unread items (where source supports it) |
| `--dry-run` | false | List item subjects only, skip LLM classification |
| `--save` | false | Write PHI-redacted markdown digest to `users/<slug>/digests/<source>-<date>.md` |
| `--json` | false | Output machine-readable JSON for piping into other tools |
| `--no-color` | auto | Disable ANSI colors (auto-detected from `isTTY`) |

`--dry-run` is critical — it lets the operator verify auth + fetch + filter logic without spending LLM tokens on bad input.

## Output Format (Human Mode)

```
🐙 <source> follow-up scanner
   window=7d  limit=50  ...

   user: <email>

→ Fetching items...
  N item(s) returned
→ Checking ollama availability...
  ollama: up (M models)
→ Classifying items...
●●·!··●·

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  <source> follow-up report
  <user> · last <N>d · X items scanned
  PHI-tainted: A (ollama)  ·  Clean: B (Groq)  ·  Errors: C
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  K item(s) need follow-up:

● HIGH  2026-05-22 08:21  <subject>
         from: <name> <<email>>
         why:  <reason>
         do:   <suggested_action>
```

Per-item progress glyphs during classification:
- `●` (yellow) — followup needed
- `·` (gray)   — no action needed
- `!` (red)    — classifier error or PHI-blocked

## Sort Order

1. Urgency descending: `high` → `med` → `low`
2. Within same urgency: most recent first

Operators triage top-down. Putting `high` first means they can stop reading as soon as they've handled what matters.

## PHI-Redacted Digest

When `--save` is passed, write a digest at `users/<sha256(email)[:12]>/digests/<source>-<date>.md`:

- Sender names/emails on PHI items go through `phi.redact()` before serialization
- Body content is NEVER copied into the digest — only the LLM's `reason` + `suggested_action`
- `webLink` (deep link back to source) is preserved so the operator can open the raw item in the native app
- The digest is committable IF the arm's `.gitignore` has `users/<slug>/digests/` excluded (recommended — digests still carry metadata)

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| Marking items as read after classification | Side effect that breaks the operator's mental model. Read-only is the contract. |
| Auto-drafting replies | Drafting is a separate step; conflating them creates accidental sends |
| Copying item bodies into the digest | Body may contain PHI even if redacted; digest exists to summarize, not archive |
| Falling back to cloud when ollama is down | PHI policy violation. Halt with exit 3, do not degrade. |
| Sending JSON-mode prompts to local models without sandwich pattern | 7B-13B models drift to markdown ~20% of runs without `# REMEMBER` block |
| Classifying items with empty/preview-only body | Bias toward `needs_followup=false`; mark `llm: 'skipped'` and report separately |
| Caching classifier results across runs | Item state changes (replied to elsewhere, no longer relevant). Run fresh every time. |
| Hardcoding the recipient's name in the system prompt | Per-arm config; resolve from auth token's `upn` / `email` claim |

## Source-Specific Plumbing

The classifier core is source-agnostic. Per-source adapters provide:

| Source | Fetch endpoint | Item shape | Adapter notes |
|---|---|---|---|
| Outlook Mail | Graph `/me/mailFolders/inbox/messages` | `{ subject, from, body, receivedDateTime, isRead, flag, webLink }` | Requires `Mail.Read`; see `browser-bearer-graph-auth` for token |
| Teams chats | Graph `/me/chats?$expand=lastMessagePreview` | `{ topic, members, lastMessage, lastUpdatedDateTime }` | Requires `Chat.Read`; only Outlook-driven token has it |
| Slack DMs | `conversations.list` + `conversations.history` | `{ channel, user, text, ts }` | Requires `mpim:read` + `im:history` scopes |
| JIRA assigned | REST `/search?jql=assignee=currentUser() AND updated > -7d` | `{ key, summary, status, updated, reporter }` | API token auth, no browser |
| GitHub PR reviews | GraphQL `viewer.pullRequests(states: OPEN)` filtered by `reviewRequests` | `{ title, author, repo, updatedAt, url }` | GH token with `repo` scope |
| Notion mentions | Database query filtered by mention property | `{ page, mentionedBy, lastEdited }` | Workspace integration |

Each adapter outputs the common shape:
```js
{
  id: string,
  subject: string,
  from: { name, email|handle },
  body: string,               // raw, may be HTML
  bodyType: 'html' | 'text',
  receivedDateTime: ISO,
  isRead: bool | null,
  flag: string | null,
  importance: 'normal' | 'high',
  webLink: string,            // deep link back to source
  hasAttachments: bool,
}
```

This shape was designed against Outlook first. Slack/JIRA adapters normalize to it via small translation functions — do not invent a new shape per source.

## Composability

- `phi-aware-rag-ingestion` — provides `phi-redact.js`, `text-normalize.js`, `groq-client.js`, `ollama-client.js`, `user-paths.js`; the triage script depends on all of them
- `browser-bearer-graph-auth` — provides the Graph bearer for Outlook/Teams sources
- `sops-age-git-encryption` — encrypts the digest dir if the arm policy treats digests as PHI-derivative
- `incident-capture` — when the classifier mis-categorizes a critical item, file an incident with the raw item ID + LLM verdict + ground truth

## Lessons Learned

- **Read-only by contract**: the first instinct was to mark classified items as "seen" — resist. The operator's existing read/unread state is theirs, not the classifier's.
- **Conservative classification beats aggressive**: false positives in `needs_followup=true` train the operator to ignore the report. False negatives are recoverable next run. Bias conservative.
- **PHI in subject/sender is rare; in body is common**: triage on subject+sender alone gives ~80% accuracy with 0 PHI risk. Body classification is the marginal 20% that pushes accuracy to ~95% — at the cost of needing ollama up. Worth the trade-off when ollama is local.
- **Local model JSON discipline requires sandwich pattern**: llama3.1:8b drifts to markdown without `# REMEMBER`. Top-only rules are not enough.
- **One adapter shape, many sources**: trying to design a per-source classifier shape (different urgency calibration per platform) made the LLM prompts inconsistent. Normalize at the adapter layer; classifier prompt stays identical.
- **Outlook Mail follow-up classification works zero-shot at Groq llama-3.3-70b quality**: no fine-tuning needed for English/Spanish corporate mail. Calibration drift was observed on extremely terse messages ("ok thanks") — those should be filtered out at normalize step (empty after sig/quote strip).

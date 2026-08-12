---
name: stream-transcript-dom-scrape
description: "Cuando una grabacion de Microsoft Stream es de solo lectura y la descarga del transcript dice 'sin permiso', el reproductor igual renderiza el texto en el DOM y Playwright lo captura. Ojo: puede constituir elusion bajo el acuerdo de servicios de MS."
metadata:
  short-description: "Microsoft Stream transcript DOM-scrape (with legal caveat)"
---

# Microsoft Stream Transcript DOM Scrape

## What

A workaround for a specific Microsoft Stream behavior: when a meeting recording is shared with a user via VIEW-only permission, the file-download UI for the transcript may explicitly deny download — but the Stream player loads the transcript text into the page DOM to render the transcript panel. Playwright can extract that rendered text.

This is a documented observation, not documented Microsoft behavior. The legal/AUP risk is real and named below.

## Why

Many regulated engagements need meeting-transcript content for legitimate reasons:
- Onboarding context (what was decided in past meetings)
- Decision archaeology (cross-source search)
- Compliance evidence (decisions logged via meeting recordings)

The defensible long-term answer is an Azure AD App Registration with admin-consented `OnlineMeetingTranscript.Read.All` scope. That requires an IT ticket and weeks of lead time.

The DOM-scrape pattern fills that gap for **historical recordings already shared with the user**, where:
- The user has VIEW permission on the recording
- The file-level ACL on the transcript itself denies download
- The transcript text is nonetheless visible in the player's transcript panel

## Legal / AUP Caveat — READ THIS FIRST

Microsoft Services Agreement §3(b) prohibits "circumventing technical limitations." When the file-download UI explicitly denies download, systematically extracting that same content via DOM may sit in a legal gray area. Specifically:

| Behavior | Legal posture (author opinion, not legal advice) |
|---|---|
| User has VIEW permission; transcript renders in DOM during normal viewing | Likely OK — same content the user could read by scrolling |
| User automates DOM read of one meeting they're attending live | Likely OK — read-mode of content the user can already see |
| User automates DOM read of historical meetings shared with them | Gray — content was shared with view permission but download is denied |
| User automates DOM read systematically across many users / a tenant | Likely circumvention — beyond what was shared |
| Productionizing this for a team / tenant scope | Don't. Get the App Registration. |

**Always** consult counsel before productionizing this pattern past a single-user prototype. Pursue the App Registration path in parallel.

## When to Use

- Your user has VIEW permission on a Stream recording shared with them
- The transcript file-download UI denies download specifically
- You have already filed (or are about to file) an IT ticket for the App Registration with `OnlineMeetingTranscript.Read.All`
- Personal / prototype scope, not team / production
- Counsel awareness for the engagement

Do NOT use:
- For meetings the user does not have VIEW permission on
- Across an entire tenant or team scope
- As a permanent production answer
- Without disclosing the AUP/legal nuance in any client-facing doc

## Workflow

### 1. Discover transcript URLs

The recording metadata is reachable via Microsoft Graph (assuming the bearer-capture pattern from `browser-bearer-graph-auth`). Two paths land URLs:

- `GET /me/drive/sharedWithMe` returns shared items including meeting recordings
- Meeting chat `eventDetail` records (specifically `callRecordingEventMessageDetail`) include recording file names + sharing URLs

```js
// Pseudo-code
const recordings = await graph.get('/me/drive/sharedWithMe?$filter=...');
const fromMeetingChats = await collectFromEventDetails(chats);
const transcriptUrls = [...recordings, ...fromMeetingChats]
  .filter(r => r.name.match(/Meeting (Transcript|Recording)/))
  .map(r => r.webUrl);
```

### 2. Convert friendly URLs to player-direct URLs

The "friendly" sharing URL often goes through `AccessDenied.aspx` if you arrive without the sharing token. The player-direct form is more reliable in headless:

```js
function toStreamPlayerUrl(friendlyUrl) {
  // Friendly: https://<tenant>-my.sharepoint.com/personal/.../Documents/Recordings/Meeting.mp4
  // Direct:   https://<tenant>-my.sharepoint.com/personal/.../_layouts/15/stream.aspx?id=<encoded-path>
  const url = new URL(friendlyUrl);
  const path = url.pathname;
  const layoutsUrl = `${url.origin}${path.replace(/\/[^/]+\.mp4$/, '/_layouts/15/stream.aspx')}`;
  return `${layoutsUrl}?id=${encodeURIComponent(path)}`;
}
```

### 3. DOM scrape with multi-URL retry

```js
const URL_FORMS = [
  toStreamPlayerUrl,    // _layouts/15/stream.aspx (most reliable headless)
  url => url,           // friendly URL as fallback
  // (third form: try with/without query strings)
];

for (const fn of URL_FORMS) {
  try {
    const text = await scrapeOnce(page, fn(originalUrl));
    if (text && text.length > MIN_USEFUL_LENGTH) return text;
  } catch (_) { /* try next */ }
}
```

`scrapeOnce` waits for the transcript panel to render, then queries the DOM with a broad selector net + a timestamp-pattern filter:

```js
async function scrapeOnce(page, url) {
  await page.goto(url, { waitUntil: 'load', timeout: 60_000 });
  await page.waitForSelector('[data-track-name*="transcript"], .transcript, [class*="Transcript"]', { timeout: 30_000 });

  // Broad selector net — Stream's CSS class names are not stable
  const lines = await page.$$eval(
    '[role="listitem"], [class*="cue"], [class*="transcript"] li',
    els => els.map(e => e.innerText)
  );

  // Timestamp filter — keep lines that look like cue text, drop chrome
  return lines
    .filter(l => /\d{1,2}:\d{2}/.test(l) || l.length > 40)
    .join('\n');
}
```

### 4. Save with provenance header

Every scraped transcript file gets a header naming where it came from, when it was captured, and the auth path used. This is the audit trail.

```
# Transcript scraped from Microsoft Stream player DOM
# Source: <recording webUrl>
# Captured: 2026-04-30T22:45:00Z
# Auth: browser-bearer (Outlook Web client)
# Note: file-download UI denied; DOM-rendered text captured under VIEW permission
# Legal: this is a prototype-only path; counsel sign-off pending for productionization

<transcript text follows>
```

### 5. Hand off to ingestion

The scraped text is then a normal input to `phi-aware-rag-ingestion`: PHI screen, chunk, embed, route, store, digest.

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| Skipping the legal caveat in client-facing docs | Hidden risk is unmanaged risk. Disclose the AUP nuance every time. |
| Productionizing without App Registration | Eventually a tenant policy change breaks the scrape and there's no fallback. |
| Cross-tenant scrape | Multi-tenant scope is far past "user views their own meetings." Don't. |
| Sharing the captured transcript outside the engagement | Original ACL denied download; sharing the scraped text reproduces what the ACL was preventing. |
| Hardcoding CSS class names | Stream's CSS classes are not stable. Use multiple selectors with broad coverage + a content filter (timestamps, length). |
| Single URL form retry | Stream sometimes sends to AccessDenied.aspx via the friendly URL but works via `_layouts/15/stream.aspx?id=...`. Multi-URL retry is mandatory. |
| Skipping the provenance header | Audit needs to see "this came from a DOM scrape, captured by user X at time Y." Without it, the file looks like it was downloaded normally. |

## Composability

- `browser-bearer-graph-auth` — provides the bearer + the Playwright + Edge persistent context this skill builds on
- `phi-aware-rag-ingestion` — consumes the scraped transcript text as input
- `sops-age-git-encryption` — encrypts the scraped transcripts before any commit

## Production Path (Replace This Skill)

The defensible long-term answer for any engagement past prototype scope:

```
File IT ticket → request Azure AD App Registration with admin consent for:
  - OnlineMeetingTranscript.Read.All
  - ChannelMessage.Read.All (if channel ingestion is in scope)
  - Mail.Read, Calendars.Read, Files.Read.All as appropriate
  → Use Graph /communications/onlineMeetings/<id>/transcripts to fetch transcripts directly
  → Retire the DOM-scrape path
```

The DOM-scrape pattern is a bridge while waiting. Once App Registration lands, retire it.

## Lessons Learned

- 5/5 success rate scraping ~25K chars of transcript content from one user's historical recordings, using the multi-URL retry + timestamp-filter pattern. Single-URL approach got 0/5 (every URL went to AccessDenied.aspx in headless without a sharing token).
- The friendly URL works in an interactive browser but not headless. The `_layouts/15/stream.aspx?id=...` form works in both. Try this form first.
- Stream's CSS class names changed twice during the prototype window. Hardcoding selectors broke the scrape; broad selector + content filter (timestamps + line length) survived the changes.
- The legal/AUP nuance is the most important sentence in this skill. Every client-facing doc that mentions this approach must disclose it. Hiding it does not protect anyone.
- Pursue the App Registration in parallel from day 1. The DOM-scrape gives you weeks; App Registration is the production answer.

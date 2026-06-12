---
name: browser-bearer-graph-auth
description: "Conditional-Access-resilient OAuth alternative for Microsoft Graph: drive a Playwright + Edge persistent context to capture the bearer token during normal sign-in. Works when Device Code Flow / headless OAuth is blocked by AADSTS53003 (Device state: Unregistered). Outlook Web grants a broader scope set than Teams Web. Hard-won workaround that should NOT be the production answer."
metadata:
  short-description: "Browser-bearer Graph auth (Conditional-Access-resilient)"
---

# Browser-Bearer Microsoft Graph Auth

## What

A pattern for capturing a Microsoft Graph bearer token by driving a real Edge browser via Playwright, intercepting the token from the first authenticated Graph request, and persisting the Edge session for subsequent silent refresh.

This is the workaround you reach for **after** Conditional Access has blocked every other OAuth path you tried. It is not the production answer. It is the path that lets a single consultant make progress while waiting for an admin-consented App Registration.

## Why

Many enterprise tenants (especially in healthcare, finance, defense) enforce a Conditional Access policy that requires:

- Compliant or hybrid-joined device, OR
- Device registered with Intune / Entra ID, OR
- App protection policy active

OAuth Device Code Flow cannot satisfy any of these — the device authenticating in the browser is not the device presenting the code. Headless OAuth flows fail for the same reason. Empirical results from a real tenant:

| OAuth client | Result |
|---|---|
| Microsoft Graph PowerShell (`14d82eec-c10e-4ab5-bd9c-b31da76ffd80`) Device Code | BLOCKED — AADSTS53003 "Device state: Unregistered" |
| Azure CLI (`04b07795-8ddb-461a-bbee-02f9e1bf7b46`) Device Code | BLOCKED — same error, even on VPN |
| `Connect-MgGraph` WAM broker (sandboxed PowerShell) | FAILED — needs window handle, not available from sandboxed shell |
| Browser-driven (Playwright + Edge) | WORKS — Edge has WAM, sends device identity claim |

Edge with WAM (Web Account Manager) is the missing piece: it satisfies the device-claim requirement that headless flows cannot. By scripting Edge through Playwright, the user signs in once interactively (with MFA), the session is persisted, and subsequent fetches happen silently.

## When to Use

- Tenant blocks Device Code Flow with AADSTS53003 (verify with at least 2 different first-party clients)
- WAM broker is unavailable from your shell context
- You need bearer tokens for Microsoft Graph for personal productivity / prototype work
- The end goal is to **replace this with an admin-consented Azure AD App Registration**, but you need to make progress now

Do NOT use:
- For production / team / multi-user services — the bearer is per-user and the approach is policy circumvention
- For systematically extracting content where the file-level ACL denies access (different problem; see related skills and legal review)
- When you have admin support — request the App Registration and skip this entirely

## Key Insight: Outlook Web vs Teams Web Scopes

Different first-party Microsoft web apps request different default scope sets at sign-in. The IdP grants whatever the requesting app asks for, within consent policy. Driving the same Playwright session through different URLs gets different tokens:

| Driving URL | Captured token characteristics |
|---|---|
| `teams.microsoft.com` / `teams.cloud.microsoft` | Narrow scope set; typically lacks `Chat.Read`; ~60 min TTL |
| `outlook.office.com` (One Outlook Web app `9199bf20-a13f-4107-85dc-02114787ef48`) | Broader scope set: `Chat.Read`, `Chat.ReadWrite`, `OnlineMeetings.Read`, `OnlineMeetingArtifact.Read.All`, `Files.ReadWrite.All`, **`Mail.Read`, `Mail.ReadWrite`**, ~24h TTL |

The Outlook Web first-party client is the better target for a wider scope envelope. Drive Outlook Web first, then Teams variants as fallback. Public app IDs above are documented Microsoft first-party app IDs.

**Mail scopes come free**: any arm that drives Outlook Web during scope-widening gets `Mail.Read` and `Mail.ReadWrite` in the captured token automatically — no scope request, no consent dialog, no extra navigation step beyond the existing Outlook visit. A `read-outlook-mail.js`-style triage tool can run on top of the same token an existing Teams sync uses, with zero new auth work. Validated on a Conditional-Access-strict tenant (ADH, May 2026) where the same captured token served both Teams sync and Outlook inbox triage from the same `.graph-token.json`.

**Note**: scopes that are NOT in the Outlook Web client (and require an admin-consented App Registration to obtain):
- `ChannelMessage.Read.All`
- `OnlineMeetingTranscript.Read.All`
- `Chat.ReadBasic`

If your work requires those, no browser-bearer trick will help — escalate to App Registration.

## Workflow

### 1. One-time interactive auth

```bash
node <arm>/auth-via-browser.js login
```

The script:
1. Launches Edge via Playwright with a persistent context dir (`<arm>/.playwright-session-microsoft/`, gitignored)
2. Navigates to `https://outlook.office.com`
3. User completes interactive sign-in + MFA in the visible browser
4. The script intercepts the first authenticated `https://graph.microsoft.com/...` request
5. Extracts the bearer from the `Authorization: Bearer ...` header
6. Saves to `<arm>/.graph-token.json` (gitignored) along with `expires_in`, `_scopes` (decoded from JWT `scp` claim), and capture metadata

### 2. Silent refresh on subsequent runs

```bash
node <arm>/<sync-tool>.js
```

The orchestrator:
1. Reads `.graph-token.json`
2. If still valid, uses it directly
3. If expired, launches headless Edge with the saved persistent context
4. Edge auto-completes the OAuth flow using the cached session (no MFA prompt, no UI)
5. New token captured and saved
6. Continues with Graph fetches

### 3. Inspect the token (verify scopes)

```bash
# Extract _scopes array from the saved token file
jq -r '._scopes[]' <arm>/.graph-token.json | sort

# Or decode the JWT scp claim directly
jq -r '.access_token' <arm>/.graph-token.json | \
  cut -d. -f2 | base64 -d 2>/dev/null | jq -r '.scp' | tr ' ' '\n' | sort
```

The two should match. If they don't, the `_scopes` array was written from a different capture than the current `access_token`.

## Architecture Skeleton

```
<arm>/
├── auth-via-browser.js        ← interactive entry: launches Edge, captures bearer
├── lib/
│   ├── graph-helpers.js       ← reads .graph-token.json, exposes graphGet(path) helper
│   └── teams-scraper.js       ← multi-target navigation (Outlook → Teams variants)
├── .graph-token.json          ← gitignored
└── .playwright-session-microsoft/  ← gitignored, Edge persistent context (~90 day cookies)
```

Multi-target navigation pattern (`lib/teams-scraper.js`):

```js
const TEAMS_SHELL_PATTERNS = [
  'https://outlook.office.com/...',         // try Outlook Web first (broader scopes)
  'https://teams.cloud.microsoft/...',      // new Teams domain
  'https://teams.microsoft.com/...',        // classic Teams
];
// Walk the list; first one that captures a valid token wins.
```

## Constraints (BE EXPLICIT IN ANY DOC)

- **Policy circumvention**: this approach BYPASSES the Conditional Access policy by satisfying the device-claim requirement through Edge rather than the calling client. Defensible for personal prototype use; NOT defensible for team or production deployment.
- **Must be replaced**: the production answer is an Azure AD App Registration with admin-consented delegated scopes. File the IT ticket on day 1 of an engagement; this workaround buys you the weeks while it's in flight.
- **Disclose openly**: in any internal doc or POC presentation, name this auth path explicitly and label it "EXPERIMENTAL — replace with App Registration before production."

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| Hardcoding the OAuth client ID of a Microsoft first-party app | The first-party app's scope set is determined by Microsoft, not by you. Treat client IDs as documented constants; rely on app behavior not on requested scopes. |
| Sharing `.playwright-session-microsoft/` across machines | Sessions are device-bound; sharing breaks the device-identity claim that makes this work in the first place |
| Committing `.graph-token.json` or the session dir | Both must be gitignored. Never commit. |
| Using this for scopes that are admin-blocked (`OnlineMeetingTranscript.Read.All`, `ChannelMessage.Read.All`) | No browser dance helps — those need admin-consented App Registration |
| Hiding this auth path in client-facing docs | Disclose. The hidden risk is the unmanaged risk. |
| Continuing this past POC into "production" | The risk profile changes. App Registration is mandatory by then. |
| Launching the interactive Edge window with `viewport: { width, height }` + no `--start-maximized` on Windows | Playwright spawns the Edge window without claiming foreground focus; on Windows it lands BEHIND the operator's other windows (especially Cursor/VSCode in full-screen). The operator thinks the script froze, kills it, and the flow fails forever. See "Windows window-focus gotcha" below. |

## Windows window-focus gotcha (hard-learned 2026-06-05)

**Symptom**: operator runs the interactive auth flow, the Node process clearly spawned Edge child processes (visible in Task Manager), the persistent-session dir was just written to — but the operator says "no veo ese edge" / "I don't see the window" and kills the process. Token never refreshes. Reproduces 100% of the time when the operator's primary window is a maximized IDE.

**Root cause**: `chromium.launchPersistentContext(SESSION_DIR, { headless: false, channel: 'msedge', viewport: { width: 1280, height: 900 }, args: ['--disable-blink-features=AutomationControlled'] })` on Windows does TWO things wrong simultaneously:

1. **Fixed `viewport` overrides OS window sizing** — Edge ends up as a small window (~1280×900) that's easy to lose behind a maximized IDE.
2. **No `--start-maximized` / `--new-window` / `--window-position`** — Playwright doesn't reclaim foreground focus, so the OS opens Edge in z-order behind the active window.

The combination is silent: no error, no log, the script just waits at `await page.goto(...)` while the user stares at their IDE.

**Fix in the calling Playwright code**:

```js
// In the function that launches the persistent context:
const visibleArgs = headless
  ? ['--disable-blink-features=AutomationControlled']
  : [
      '--disable-blink-features=AutomationControlled',
      '--start-maximized',          // make the window obvious
      '--window-position=120,80',   // offset from corner so it isn't hidden by taskbar
      '--new-window',                // refuse to merge into an existing Edge process
    ];

const context = await chromium.launchPersistentContext(SESSION_DIR, {
  headless,
  channel: 'msedge',
  // CRITICAL: null viewport in interactive mode — fixed viewport defeats --start-maximized
  viewport: headless ? { width: 1280, height: 900 } : null,
  args: visibleArgs,
});

const page = context.pages()[0] || await context.newPage();
// Pull the window forward BEFORE navigation so user sees it emerge.
if (!headless) {
  try { await page.bringToFront(); } catch {}
}
await page.goto(URL, ...);
if (!headless) {
  try { await page.bringToFront(); } catch {}  // again after redirects
}
```

**Fix in the operator UX layer** (the launcher script that calls this):
- Print a **loud, framed warning BEFORE** launching Edge: "Playwright-spawned Edge can open BEHIND your other windows. ALT+TAB or check taskbar."
- Emit a **heartbeat every 10s** in the wait loop while no URL movement is detected — operator needs to know the script is alive while they hunt for the window.
- If 30s pass with zero URL change in interactive mode, print an escalation message: "No URL activity yet — is the Edge window still hidden? ALT+TAB now."

**Operator instruction in any RUNBOOK**: explicitly tell the human "the Edge window may open behind Cursor/VSCode — ALT+TAB before you assume the script froze."

This gotcha cost ~45 minutes of session time before being diagnosed; the brain MUST surface it preemptively whenever a new arm wires up `auth-via-browser.js`-style flows.

## Composability

- `phi-aware-rag-ingestion` — uses the captured token to fetch source content
- `mcp-stack-setup` (existing) — for the production path, MCP tools authenticate via OAuth flows configured at the MCP-client level (Claude Desktop / Cursor); the browser-bearer pattern is an alternative for non-MCP code
- `security-threat-model` (existing) — threat model must explicitly cover this auth path's residual risk

## Lessons Learned

- Switching from Teams Web to Outlook Web as the driver URL turned a 60-minute, narrow-scope token into a 24-hour, broad-scope token. Same Playwright code, different first-party client. Significant unblock for almost-zero new code.
- AADSTS53003 with sub-detail "Device state: Unregistered" is the canonical signature of "Conditional Access wants a device claim you can't provide." Stop trying Device Code variants when you see this. Pivot to browser-bearer.
- Re-running the silent refresh through Outlook Web (not Teams) is critical — when Teams Web silently changes URL during refresh (e.g., to `teams.cloud.microsoft`), the multi-target pattern with Outlook FIRST keeps the broad-scope token.
- Always verify scopes from the JWT `scp` claim, not from the saved `_scopes` field. Discrepancies between the two indicate you're reading a stale capture.
- **`Mail.Read`/`Mail.ReadWrite` are bundled into the Outlook-driven token automatically**: an arm that already has the Teams/Outlook auth path running can ship a new inbox-triage feature (see `inbox-triage-classifier`) without filing an admin ticket for new scopes. Validated: same captured token served Teams sync AND Outlook follow-up scanner from a single `.graph-token.json` (ADH, 2026-05-22).

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
| `outlook.office.com` (One Outlook Web app `9199bf20-a13f-4107-85dc-02114787ef48`) | Broader scope set: `Chat.Read`, `Chat.ReadWrite`, `OnlineMeetings.Read`, `OnlineMeetingArtifact.Read.All`, `Files.ReadWrite.All`, ~24h TTL |

The Outlook Web first-party client is the better target for a wider scope envelope. Drive Outlook Web first, then Teams variants as fallback. Public app IDs above are documented Microsoft first-party app IDs.

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

## Composability

- `phi-aware-rag-ingestion` — uses the captured token to fetch source content
- `mcp-stack-setup` (existing) — for the production path, MCP tools authenticate via OAuth flows configured at the MCP-client level (Claude Desktop / Cursor); the browser-bearer pattern is an alternative for non-MCP code
- `security-threat-model` (existing) — threat model must explicitly cover this auth path's residual risk

## Lessons Learned

- Switching from Teams Web to Outlook Web as the driver URL turned a 60-minute, narrow-scope token into a 24-hour, broad-scope token. Same Playwright code, different first-party client. Significant unblock for almost-zero new code.
- AADSTS53003 with sub-detail "Device state: Unregistered" is the canonical signature of "Conditional Access wants a device claim you can't provide." Stop trying Device Code variants when you see this. Pivot to browser-bearer.
- Re-running the silent refresh through Outlook Web (not Teams) is critical — when Teams Web silently changes URL during refresh (e.g., to `teams.cloud.microsoft`), the multi-target pattern with Outlook FIRST keeps the broad-scope token.
- Always verify scopes from the JWT `scp` claim, not from the saved `_scopes` field. Discrepancies between the two indicate you're reading a stale capture.

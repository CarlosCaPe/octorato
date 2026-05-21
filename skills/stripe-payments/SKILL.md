---
name: stripe-payments
description: Decide and implement the right Stripe integration tier for a use case — Payment Link (zero-code donate / one-off sale), Checkout (hosted multi-product), Elements (custom UI), Connect (marketplace), or Billing (subscriptions). Covers Stripe MCP server registration, Stripe CLI for local dev + webhook forwarding, key hygiene (sk_live_* never in chat), and CF Pages secret deployment. Use when adding any Stripe surface to an arm, when a donate / checkout / subscription button is needed, when choosing between PayPal and Stripe, or when wiring Stripe webhooks against Cloudflare Workers.
---

# Stripe Payments — Pick the Right Tier First

The #1 mistake with Stripe is picking the most powerful primitive when the simplest one would do. Order of preference, simplest first:

| Tier | When to use | Code in your repo | Secrets needed |
|---|---|---|---|
| **Payment Link** | Donate button, one-off sale, paid course, single SKU | 1 anchor tag with `https://buy.stripe.com/...` | None — URL is public |
| **Hosted Checkout** | Multi-product cart, dynamic price, custom metadata | API call to create `checkout.sessions` server-side, then `302` redirect | `STRIPE_SECRET_KEY` |
| **Elements (Stripe.js)** | Custom UI inline on your page (rare — usually overkill) | Stripe.js loaded, Elements mounted, PaymentIntent server-side | `pk_*` (client) + `sk_*` (server) |
| **Billing (Subscriptions)** | Recurring SaaS, tiered plans, trials | Products + Prices in Dashboard, customer portal session | `sk_*` + customer portal config |
| **Connect** | Marketplace where you split funds across N merchants | Onboarding flow, Express/Standard accounts, transfers | `sk_*` + Connect-enabled account |

**Default decision rule:** start at Payment Link. Only move up a tier when a concrete requirement forces it (e.g., "user must select quantity" → Checkout, "I must render the card form in my own UI" → Elements). The Payment Link tier needs **zero code and zero secrets in your repo** — that's the whole point.

## Key hygiene (non-negotiable)

| Key type | Format | Where it lives | Risk if leaked |
|---|---|---|---|
| **Publishable** | `pk_live_*` / `pk_test_*` | Public client JS | None — designed to be visible |
| **Secret** | `sk_live_*` / `sk_test_*` | Server env var only | **Full account control** — drain funds, change account, create charges |
| **Restricted** | `rk_live_*` | Server env var, scoped permissions | Limited to allowed resources |
| **Webhook signing** | `whsec_*` | Server env var | Webhook spoofing |

**Hard rules — every arm, every project:**
- Secret keys NEVER in `.env` committed to git. NEVER in chat transcripts. NEVER in MCP config files committed to git.
- In Cloudflare Pages: `wrangler pages secret put STRIPE_SECRET_KEY --project-name <arm>` (encrypted at rest, never exposed to client).
- If a `sk_live_*` is ever pasted in chat / committed / pushed: **roll it immediately** at Dashboard → Developers → API keys → "Roll key". Then audit Stripe events for the last 24h for unauthorized charges.
- Pre-commit `gitleaks` already catches `sk_live_*` patterns in this repo's stack — never bypass.

## Payment Link recipe (the 90% case)

1. Stripe Dashboard → **Payment Links** → **New**
2. Pick price (fixed) or "Customer chooses what to pay" (donations)
3. Customize success URL, branding, collect email if needed
4. Copy URL → `https://buy.stripe.com/<short-code>`
5. Drop into HTML: `<a href="https://buy.stripe.com/...">Donate</a>` (zero JS)

That's it. Stripe hosts the checkout page, handles PCI compliance, sends the receipt email, posts the funds.

## MCP server (Stripe official)

Stripe ships an official MCP server (`@stripe/mcp`) — exposes the API as agent tool calls. Useful when you want Claude / agents to create Payment Links, refund charges, list customers, etc. programmatically.

**Setup (key stays out of chat):**

```bash
# 1. Create env file in user-space, never committed
mkdir -p ~/.config/stripe && touch ~/.config/stripe/env
chmod 600 ~/.config/stripe/env

# 2. Edit with your $EDITOR — paste sk_live_* or sk_test_* there
$EDITOR ~/.config/stripe/env
# File contents:
#   STRIPE_SECRET_KEY=sk_live_...

# 3. Register MCP (point at the env file, don't inline the key)
claude mcp add stripe --env-file ~/.config/stripe/env -- npx -y @stripe/mcp --tools=all

# 4. Verify
claude mcp list | grep stripe
```

**Tool scoping:** `--tools=all` exposes everything; for production agents use `--tools=customers.read,products.read,payment_links.create` to limit blast radius. Full tool list: https://github.com/stripe/agent-toolkit

**Restricted Key alternative:** instead of `sk_live_*`, create a Restricted Key (`rk_live_*`) in Dashboard → Developers → API keys → Restricted Keys, scoped to only the resources the MCP needs (e.g., `payment_links: write`, `customers: read`). Drastically smaller blast radius if leaked.

## Stripe CLI (local dev + webhook forwarding)

The CLI is essential for local webhook development. Without it, webhooks from Stripe → your localhost can't reach you.

```bash
# Install (Linux, no sudo, binary to ~/.local/bin)
LATEST=$(curl -fsSL https://api.github.com/repos/stripe/stripe-cli/releases/latest | grep -oP '"tag_name": "\K[^"]+')
VER=${LATEST#v}
curl -fsSL "https://github.com/stripe/stripe-cli/releases/download/${LATEST}/stripe_${VER}_linux_x86_64.tar.gz" -o /tmp/stripe.tar.gz
tar -xzf /tmp/stripe.tar.gz -C ~/.local/bin/ stripe
chmod +x ~/.local/bin/stripe

# Login (opens browser, paste auth code)
stripe login

# Forward Stripe webhooks to local endpoint
stripe listen --forward-to localhost:4321/api/stripe/webhook
# Outputs `whsec_*` — use this as STRIPE_WEBHOOK_SECRET in local dev only

# Trigger test events
stripe trigger payment_intent.succeeded
stripe trigger checkout.session.completed

# Tail live mode events (read-only)
stripe events list --limit 5
stripe logs tail
```

## Webhook implementation on Cloudflare Workers

Stripe webhooks require **signature verification** — don't accept any webhook without it.

```typescript
// Pseudocode for src/pages/api/stripe/webhook.ts (CF Pages)
import Stripe from 'stripe';
export const POST: APIRoute = async ({ request, locals }) => {
  const sig = request.headers.get('stripe-signature');
  const body = await request.text(); // raw body required for signature check
  const stripe = new Stripe(locals.runtime.env.STRIPE_SECRET_KEY);
  let event;
  try {
    event = stripe.webhooks.constructEvent(body, sig, locals.runtime.env.STRIPE_WEBHOOK_SECRET);
  } catch (e) {
    return new Response('Invalid signature', { status: 400 });
  }
  // handle event.type — keep handler idempotent (Stripe retries)
  return new Response('ok', { status: 200 });
};
```

CF Pages secrets:
```bash
wrangler pages secret put STRIPE_SECRET_KEY --project-name <arm>
wrangler pages secret put STRIPE_WEBHOOK_SECRET --project-name <arm>
```

Webhook endpoint URL added in Dashboard → Developers → Webhooks → Add endpoint, pointing at `https://<arm-domain>/api/stripe/webhook`.

## PayPal vs Stripe — decision guide

| Need | Pick |
|---|---|
| Lowest friction donation, recipient already has PayPal | **PayPal** form POST |
| Tarjeta de crédito sin que el donante necesite cuenta | **Stripe** (Apple Pay / Google Pay built in) |
| Mejor conversión global (US/EU/MX) | **Stripe** — significantly higher card-acceptance rate |
| Programmatic management from agents | **Stripe MCP** (PayPal MCP doesn't exist officially) |
| Subscriptions / recurring | **Stripe Billing** (PayPal Subscriptions exists but UX is dated) |
| LATAM cash methods (OXXO, SPEI in MX) | **Stripe** — native LATAM payment method support |
| Tienes ambos en la página | **Both side-by-side** — donor picks. Higher overall conversion. |

## Caveats

- **MX-specific:** Stripe MX accepts MXN, USD via international card. OXXO Pago needs explicit enable in Dashboard. CFDI emission (Mexican tax invoice) is NOT automatic — needs separate billing tool (Facturapi, etc.) if you sell to Mexican businesses.
- **Refund policy:** Donations are gifts, not transactions — refunds are at merchant discretion. Document the policy clearly on the page (see `/donate` on dataqbs.com for pattern).
- **Fees:** Stripe MX = 3.6% + $3 MXN per successful card. PayPal varies. Both eat into small donations significantly — flag this to donors transparently.
- **Tax-deductibility:** Neither Stripe nor PayPal makes a donation tax-deductible. That requires the recipient to be a registered non-profit (501(c)(3) in US, Donataria Autorizada in MX). State this on the donate page.

## Companion skills

- `cloudflare-deploy` — wrangler secret management
- `tracking-measurement-specialist` (if available) — Stripe → GA4 conversion tracking
- `security-best-practices` — never log webhook bodies (contain PII)
- `bruno-postman-alternative` — test Stripe API locally without hitting live mode

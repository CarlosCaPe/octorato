---
name: cache-bust-deploy-validation
description: After a production deploy of a CDN-fronted site, force cache-bust on every validation request and inspect Age/cache-status headers — the CDN can serve a stale 200 with old content for hours, hiding a broken deploy. Use whenever validating a freshly-deployed web app, debugging "deploy completed but the live site shows the old version", or building a post-deploy smoke test.
metadata:
  type: skill
---

# Cache-Bust Deploy Validation

## When to use

Trigger this skill any time you are validating that a fresh deploy went live on a CDN-fronted host (Cloudflare Pages, Vercel, Netlify, Fastly, CloudFront, AWS S3+CF).

Concrete triggers:
- "Deploy completed but the live site shows the old version"
- "Validating a deploy / verifying a feature shipped"
- "Why is the new <feature> not visible?"
- Writing a post-deploy smoke test

## The anti-pattern

```bash
# WRONG — the CDN happily returns 200 with cached old content
curl https://prod.example.com/page   # looks fine, but is stale
```

A deploy can be **broken at the worker but green at the edge** for hours because the edge cache holds the last successful response. Validation that doesn't bypass the cache will report "all good" while real users are about to hit 404 / wrong content as soon as the cache expires.

## The correct validation loop

```bash
# 1. Cache-bust on EVERY validation request
curl -sS "https://prod.example.com/page?_=$(date +%s)" -o /tmp/fresh.html
grep -c "<feature-marker>" /tmp/fresh.html   # must be > 0

# 2. Inspect cache headers — Age > 60s on a path you just redeployed = stale
curl -sS -I "https://prod.example.com/page" | grep -iE 'cache|age|x-vercel|cf-'

# 3. Test the deploy preview URL too (each platform exposes one) — it
#    skips the production CDN cache layer entirely.
#    CF Pages:  https://<deploy-hash>.<project>.pages.dev/<path>
#    Vercel:    URL from `vercel ls` / deployment dashboard
#    Netlify:   permalink under each deploy in the dashboard
```

## Headers that signal cache masking

| Header | Meaning |
|---|---|
| `Age: <N>` (N > 60) | Response is N seconds old — served from cache |
| `cf-cache-status: HIT` | Cloudflare served from edge cache |
| `cf-cache-status: DYNAMIC` | NOT cached at edge (the SSR case you usually want) |
| `cf-cache-status: BYPASS` | CF skipped cache by config (also OK) |
| `x-vercel-cache: HIT` | Vercel edge cache hit |
| `x-cache: Hit from cloudfront` | CloudFront hit |
| `cache-control: no-cache, max-age=0` combined with `Age: <large>` | Origin says don't cache, but something cached it anyway — investigate |

## Why it matters

CDN edge caches routinely outlive deploys:
- HTML responses get cached despite `Cache-Control: no-cache` (some CDNs respect only `private` or `no-store`)
- Workers/Pages keep the old version until purge propagates (~30 sec to several min)
- Tiered caches mean different POPs may serve different versions for hours
- A redirect that points to a now-404 URL can be served from cache long after the breaking commit shipped

So **"the site loads correctly"** is not proof **"the deploy worked"** — it might just be proof that the cache hasn't expired.

## How to purge

Use when you need users to see the new version immediately, not whenever the TTL expires.

| Platform | How |
|---|---|
| Cloudflare | Dashboard → Caching → Configuration → Purge by URL. API: `POST /zones/<zone-id>/purge_cache` with `{"files":["https://prod/path"]}` |
| Vercel | `vercel rollback <prev>` then redeploy, or trigger a force-redeploy commit. Vercel auto-invalidates on deploy but a stuck edge sometimes needs this. |
| Netlify | Site → Deploys → "Clear cache and deploy site" |
| Fastly | `curl -X POST -H "Fastly-Key:$KEY" https://api.fastly.com/service/<service-id>/purge_all` |
| CloudFront | `aws cloudfront create-invalidation --distribution-id $ID --paths '/path'` |

## Validation script template (drop into CI smoke tests)

```bash
URL="$1"
MARKER="$2"   # e.g. unique string only present in the new version
fresh=$(curl -sS "${URL}?_=$(date +%s)")
hits=$(echo "$fresh" | grep -c "$MARKER")
if [ "$hits" -lt 1 ]; then
  echo "::error::Marker '$MARKER' not present in $URL — deploy may be stale or broken"
  curl -sS -I "$URL" | grep -iE 'cache|age' >&2
  exit 1
fi
echo "✓ Marker present, deploy live"
```

## Anti-pattern to flag in code review

A `_redirects` / route rule that redirects path A → path B without first verifying that the receiving framework's worker actually has a handler at path B. Common on Astro / Next.js / Remix hybrid SSR: the framework registers routes WITHOUT a trailing slash by default; a CDN-level redirect forcing the trailing slash sends users to a path the worker doesn't serve, producing 404. The edge cache can mask this for hours before users complain.

## Lessons Learned

- An add-only `_redirects` line meant to fix a perceived SEO conflict broke a section of a hybrid-SSR site for ~5h before being caught. The 5h delay was entirely due to edge cache: the production URL kept returning `200` with `Age: ~18000s` (cached pre-regression), so manual checks said "looks fine" while the actual worker was 404-ing. Lesson: every deploy validation MUST cache-bust, and a 200 with a large `Age` is a red flag, not a green one.

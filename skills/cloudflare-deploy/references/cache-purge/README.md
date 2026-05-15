# Cloudflare Cache Purge

Purge cached assets after every deploy to ensure users see fresh content immediately.

## Why

Cloudflare aggressively caches static assets (JS, CSS, images, HTML). After a Pages/Workers deploy, old cached versions may persist for hours. This causes users to see stale UI, broken layouts, or missing features — even after a successful deploy.

## Token Setup

The deploy token (`CF_API_TOKEN`) often lacks cache purge permission. Create a **dedicated token**:

1. Go to https://dash.cloudflare.com/profile/api-tokens → Create Token
2. Template: **Custom token**
3. Permissions: **Zone → Cache Purge → Purge**
4. Zone Resources: **Include → Specific zone → your-domain.com**
5. Save as `CF_CACHE_PURGE_TOKEN` in `.env`

## API Call

```bash
curl -s -X POST \
  "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
  -H "Authorization: Bearer ${CF_CACHE_PURGE_TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{"purge_everything": true}'
```

Response on success:
```json
{"result": {"id": "<zone-id>"}, "success": true, "errors": [], "messages": []}
```

Common error — `10000 Authentication error`: token lacks `Zone:Cache Purge` permission.

## Finding Zone ID

```bash
curl -s "https://api.cloudflare.com/client/v4/zones?name=your-domain.com" \
  -H "Authorization: Bearer ${CF_API_TOKEN}" | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['result'][0]['id'])"
```

## Selective Purge

Purge specific files instead of everything:
```bash
curl -s -X POST \
  "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
  -H "Authorization: Bearer ${CF_CACHE_PURGE_TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{"files": ["https://example.com/app.js", "https://example.com/style.css"]}'
```

Purge by prefix (Enterprise only):
```bash
--data '{"prefixes": ["https://example.com/assets/"]}'
```

## Integration Pattern: Post-Deploy Purge

Add cache purge as the final step in any deploy script:

```bash
# ── After deploy ──
CACHE_TOKEN="${CF_CACHE_PURGE_TOKEN:-${CF_API_TOKEN:-}}"

if [[ -n "$CACHE_TOKEN" ]]; then
  RESULT=$(curl -s -X POST \
    "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
    -H "Authorization: Bearer ${CACHE_TOKEN}" \
    -H "Content-Type: application/json" \
    --data '{"purge_everything": true}')

  if echo "$RESULT" | grep -q '"success":true'; then
    echo "✓ Cache purged"
  else
    echo "⚠ Cache purge failed — check token permissions"
  fi
else
  echo "⚠ No cache purge token. Set CF_CACHE_PURGE_TOKEN in .env"
fi
```

## .env Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `CF_ZONE_ID` | Zone identifier for the domain | Yes |
| `CF_CACHE_PURGE_TOKEN` | Token with Zone:Cache Purge permission | Yes |
| `CF_API_TOKEN` | Fallback (only works if it has purge permission) | No |

## Manual Purge (Dashboard)

Dashboard → your-domain.com → Caching → Configuration → **Purge Everything**

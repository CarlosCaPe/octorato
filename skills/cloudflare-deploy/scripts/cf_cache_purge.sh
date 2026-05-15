#!/usr/bin/env bash
# ── Cloudflare Cache Purge ────────────────────────────
# Purge all cached assets for a Cloudflare zone.
#
# Usage:
#   ./cf_cache_purge.sh                         # purge everything (reads .env)
#   ./cf_cache_purge.sh --files "https://example.com/app.js,https://example.com/style.css"
#
# Env vars (from .env or environment):
#   CF_ZONE_ID             — required
#   CF_CACHE_PURGE_TOKEN   — required (or CF_API_TOKEN as fallback)

set -euo pipefail

# ── Load .env if present ──────────────────────────────
if [[ -f .env ]]; then
  set -a; source .env; set +a
elif [[ -f ../../.env ]]; then
  set -a; source ../../.env; set +a
fi

ZONE_ID="${CF_ZONE_ID:-}"
TOKEN="${CF_CACHE_PURGE_TOKEN:-${CF_API_TOKEN:-}}"
FILES=""

for arg in "$@"; do
  case "$arg" in
    --files=*) FILES="${arg#*=}" ;;
    --files)   shift; FILES="${1:-}" ;;
  esac
done

# ── Validate ──────────────────────────────────────────
if [[ -z "$ZONE_ID" ]]; then
  echo "✖ CF_ZONE_ID not set. Add it to .env or export it." >&2
  exit 1
fi
if [[ -z "$TOKEN" ]]; then
  echo "✖ No token found. Set CF_CACHE_PURGE_TOKEN or CF_API_TOKEN." >&2
  exit 1
fi

# ── Build payload ─────────────────────────────────────
if [[ -n "$FILES" ]]; then
  # Selective purge
  JSON_FILES=$(echo "$FILES" | tr ',' '\n' | sed 's/.*/"&"/' | paste -sd, -)
  PAYLOAD="{\"files\": [$JSON_FILES]}"
  echo "Purging specific files..."
else
  PAYLOAD='{"purge_everything": true}'
  echo "Purging all cache..."
fi

# ── Execute ───────────────────────────────────────────
RESULT=$(curl -s -X POST \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/purge_cache" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  --data "$PAYLOAD")

if echo "$RESULT" | grep -q '"success"[[:space:]]*:[[:space:]]*true'; then
  echo "✓ Cache purged successfully"
else
  echo "✖ Cache purge failed:" >&2
  echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'  Error {e[\"code\"]}: {e[\"message\"]}') for e in d.get('errors',[])]" 2>/dev/null || echo "$RESULT"
  exit 1
fi

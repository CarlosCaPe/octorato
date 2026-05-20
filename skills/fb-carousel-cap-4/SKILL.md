---
name: fb-carousel-cap-4
description: "Meta Graph /feed?attached_media= silently 500s with N>=5 photos + a long caption — cap defensively at 4 inside any FB Page carousel publisher"
metadata:
  short-description: "Cap FB Page photo carousels at 4 photos to avoid the undocumented Meta 500 'reduce the amount of data' error"
---

# FB Carousel Cap = 4

## What

The Meta Graph API endpoint for publishing a multi-photo carousel to a Facebook
Page —

```
POST /{page-id}/feed
  ?attached_media[0]={"media_fbid":"<photo_id_1>"}
  &attached_media[1]={"media_fbid":"<photo_id_2>"}
  ...
  &message=<long caption>
```

returns

```json
{
  "error": {
    "message": "Please reduce the amount of data you're asking for, then retry your request",
    "type": "OAuthException",
    "code": 1,
    "fbtrace_id": "..."
  }
}
```

with `HTTP 500` once the combined request size exceeds an **undocumented**
Meta threshold. In practice the cliff sits around **5+ unpublished photo IDs
with a caption ≥ ~1 KB** (a typical Spanish real-estate caption with a
WhatsApp `wa.me` link is already in the 1–2 KB range).

Single-photo posts and 4-photo carousels with the same caption length succeed.

## Why this matters

- The error message is **misleading** ("reduce the amount of data you're
  asking for") — the operator interprets it as a quota/rate-limit issue and
  burns hours chasing rate limits, when the real fix is a payload-size cap.
- Meta has **no documented limit** on `attached_media[]`. Public docs say "up
  to 10" but in practice the realistic ceiling depends on caption size and
  any URL-encoded payload (deep-link URLs, hashtags with emoji).
- The 500 happens **after** the photos are uploaded as unpublished, so the
  retry surface is awkward: the photos exist orphaned in the Page library
  and need cleanup or re-use.

## Fix

Defensive cap inside the publisher function:

```typescript
// Undocumented Meta limit: /feed?attached_media= 500s with ~5+ photos
// + ~1.5KB caption with URL-encoded WhatsApp prefill. 4 is the safe cap.
const FB_CAROUSEL_MAX_PHOTOS = 4;

async function publishFBPageCarousel(
  pageId: string,
  token: string,
  imageUrls: string[],
  caption: string,
) {
  const capped = imageUrls.slice(0, FB_CAROUSEL_MAX_PHOTOS);
  // ... upload each capped[i] as unpublished, collect IDs, POST /feed
}
```

This is **defense in depth** — even if upstream enqueues 10 image URLs,
the publisher refuses to send more than 4. Posts already scheduled with
N>4 will publish normally on the next attempt.

## When the cap is wrong

If you genuinely need to ship 10+ photos:

1. **Albums instead of carousels** — `POST /{page-id}/albums` then add photos
   one-by-one to that album. Different API, no `attached_media` size limit.
2. **Comment chain** — main post with first 4, then add remaining photos in
   pinned comments. Works but breaks the "swipe carousel" UX.
3. **Shorter caption** — caption + URL-encoded `wa.me` link is the usual
   payload bloat. Move the link to a pinned comment and the threshold lifts
   to ~7-8 photos in practice. Still not 10.

## Diagnostic when this happens

1. Capture the exact request body sent to `/feed`. If `attached_media` has
   5+ entries AND caption length > ~800 chars → almost certainly this.
2. Reproduce with the same photos but caption `"test"` — succeeds → it's
   payload size, not the photos themselves.
3. Reproduce with same caption but 1 photo → succeeds → confirms the cap.

## Lessons Learned

<!-- Date · Caption length · Photo count · What threshold hit -->

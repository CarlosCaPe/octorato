---
name: fb-page-dual-id
description: "A Facebook Page has TWO different identifiers: the URL ID seen in `profile.php?id=N` (and in the page's vanity URL) and the Graph API ID returned by `me/accounts` / used in API calls. They are NOT interchangeable. Worse, the New Pages Experience reuses the `profile.php?id=N` URL shape for Pages too, so the URL no longer tells you whether a target is a Page or a personal Profile. Store and match on the Graph API ID."
metadata:
  short-description: "FB Page URL ID (profile.php?id=N) != Graph API ID (me/accounts.id); New Pages Experience reuses the profile.php URL so the URL no longer distinguishes Page from Profile. Persist the Graph API ID for all API calls."
---

# Facebook Page Dual ID

## What

When you automate posting to a Facebook Page through the Graph API, you
will encounter two numbers that both look like "the Page ID" and are not
the same:

- **URL ID** - the number in `facebook.com/profile.php?id=N`, also what a
  human copies from the address bar.
- **Graph API ID** - the `id` returned by `GET /me/accounts` (the list of
  Pages the token can manage), and the one every Graph endpoint expects in
  `POST /{page-id}/feed`, photo uploads, insights, etc.

Passing the URL ID to a Graph endpoint fails or targets the wrong object.
All API persistence and matching must use the Graph API ID.

## The New Pages Experience trap

Historically you could tell a Page from a personal Profile by the URL: a
Page had a vanity slug, a Profile had `profile.php?id=N`. That heuristic is
DEAD. The New Pages Experience reuses the `profile.php?id=N` URL form for
Pages too. So:

- You can no longer infer "Page vs Profile" from the URL shape.
- A `profile.php?id=N` link may be a Page, and that `N` is the URL ID, not
  the Graph API ID.

To classify and to call the API correctly, resolve through the token:
`GET /me/accounts` returns the managed Pages with their Graph API IDs.
Match against that list, not against the URL.

## The rule

1. **Persist the Graph API ID** (`me/accounts[].id`) as the canonical Page
   identifier in any datastore, config, or mapping. Never persist the URL
   ID as the thing you call the API with.
2. **Never derive Page-ness from the URL.** Resolve via `me/accounts`.
3. If a human hands you a `profile.php?id=N` link, treat `N` as a URL ID to
   be resolved, not as the API target.

## Symptom that points here

- A feed/photo POST 400s with an object-not-found or permissions error
  even though the token clearly manages the Page.
- A "Page" you stored stops matching, or you cannot tell a Page from a
  Profile by its link anymore.

In both cases, re-fetch `me/accounts`, confirm the Graph API ID, and store
that. The URL ID was a red herring.

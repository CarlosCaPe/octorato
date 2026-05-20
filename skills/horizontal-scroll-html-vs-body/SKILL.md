---
name: horizontal-scroll-html-vs-body
description: "Android Chrome ignores overflow-x:hidden on <body> if <html> still allows it — clip the root, not just the body, to kill phantom horizontal scroll"
metadata:
  short-description: "Phantom horizontal scroll on Android — fix lives on <html>, not <body>"
---

# Horizontal Scroll — html vs body

## What

A page renders cleanly on desktop and iOS Safari but on **Android Chrome** the
user can drag the page left/right ("phantom horizontal scroll") even though
nothing visible extends past the viewport. The most common reason is that
`overflow-x: hidden` was placed on `<body>` but not on the `<html>` root.

## Why this is browser-specific

When a descendant element briefly exceeds viewport width — an absolutely
positioned dropdown with a fixed `w-XX` value, an off-screen carousel slide,
an image without `max-width: 100%`, a transformed element, an `inset-x-…`
container — the overflow propagates up to the **initial containing block**,
which is the `<html>` element, not `<body>`.

| Browser | Honors `body { overflow-x: hidden }` alone | Result |
|---|---|---|
| Chrome desktop | Yes | No phantom scroll |
| Firefox / Edge desktop | Yes | No phantom scroll |
| Safari iOS | Yes (usually) | No phantom scroll |
| **Chrome Android** | **No** | **html scrolls horizontally** |

This bites mobile-heavy sites first because dev usually QAs on desktop.

## When to suspect this

- "Site moves left/right when I swipe but I don't see anything wider"
- Only on Android, not iPhone, not desktop
- Affects ALL pages of a layout, not just one (points at root layout, not page-specific)
- Browser devtools "outline every element" trick reveals no visibly overflowing element

## Fix

One line: add `overflow-x: hidden` to the `<html>` element. With Tailwind in
an Astro/Next.js/Svelte layout that's literally:

```diff
- <html lang="es" class="scroll-smooth dark">
+ <html lang="es" class="scroll-smooth dark overflow-x-hidden">
```

In plain CSS:

```css
html, body {
  overflow-x: hidden;
  /* don't forget overscroll-behavior-x: none if pull-to-refresh-x triggers */
}
```

## Diagnostic

1. Open the page in **Android Chrome devtools** (`chrome://inspect` from desktop).
2. In Elements → Computed, select the `<html>` element. Look for `overflow-x`.
3. If it's `visible` (the default) and `<body>` has `hidden`, you have this bug.
4. Inject `document.documentElement.style.overflowX = 'hidden'` in the console —
   the scroll disappears? Confirmed.

## Anti-patterns

- Adding `overflow: hidden` (without the `-x`) — kills vertical scroll too. The
  page becomes a fixed-height card.
- Adding `width: 100vw` to body — on iOS Safari, `100vw` includes the scrollbar
  area on some configs, so the body itself becomes wider than the viewport.
  Stick to `overflow-x: hidden` on both `html` and `body`.
- Trying to track down "what's overflowing" before applying the root-level
  clip. The clip is cheap and the failure mode (silently hiding off-canvas
  content) is rare in practice for well-built layouts.

## Lessons Learned

<!-- Date · Symptom · Element that was overflowing (post-mortem grep) · Fix applied -->

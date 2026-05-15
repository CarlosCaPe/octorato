---
name: svelte-tailwind-gotchas
description: Known gotchas and workarounds when combining Svelte (4/5) with Tailwind CSS. Use when Svelte template compilation fails with Tailwind class names, when class directives break, when dynamic classes don't apply, or when debugging CSS-related Svelte compiler errors. Covers class:directive parser bugs, dark mode, opacity shorthand, arbitrary values, and conditional class patterns.
metadata:
  short-description: Svelte + Tailwind CSS compatibility fixes
  created: 2026-04-01
  origin: Svelte project — CorporateHeader.svelte class:bg-white/80 breaking Svelte parser
---

# Svelte + Tailwind CSS Gotchas

Workarounds for known compatibility issues between Svelte's template compiler and Tailwind CSS class syntax. These issues are subtle — the code looks correct, Tailwind docs confirm the classes, but Svelte refuses to compile.

## When to Use

- Svelte compiler throws unexpected errors on Tailwind classes
- `class:` directive fails with classes containing `/`, `:`, `[`, `]`, or `.`
- Dynamic Tailwind classes don't appear in output
- Conditional class application breaks Svelte's parser
- Migrating a Tailwind project to Svelte (or vice versa)

## Gotcha #1: class: Directive + Special Characters

### The Problem

Svelte's `class:` directive cannot handle Tailwind classes containing `/` (opacity shorthand), `:` (variants), `[` `]` (arbitrary values), or `.` (decimal values).

```svelte
<!-- ❌ BREAKS: Svelte parser interprets / as tag close -->
<div class:bg-white/80={scrolled}>

<!-- ❌ BREAKS: colon conflicts with Svelte's directive syntax -->
<div class:dark:bg-slate-900={darkMode}>

<!-- ❌ BREAKS: brackets confuse the parser -->
<div class:w-[calc(100%-2rem)]={wide}>

<!-- ❌ BREAKS: dot interpreted as class accessor -->
<div class:opacity-[0.85]={faded}>
```

**Error messages** (unhelpful — don't mention the real cause):
- `Expected }`
- `Unexpected token`
- `ParseError: Unexpected /`

### The Fix: Computed Class String

Replace `class:` directives with a reactive computed class string:

```svelte
<script>
  let scrolled = false;

  // ✅ Build the full class string reactively
  $: headerClass = [
    'sticky top-0 z-40 transition-all duration-300',
    scrolled ? 'bg-white/80 dark:bg-slate-900/90 backdrop-blur-md border-b border-slate-200/50' : '',
    scrolled ? 'shadow-sm' : 'bg-transparent',
  ].filter(Boolean).join(' ');
</script>

<!-- ✅ Single class attribute, no directives -->
<header class={headerClass}>
```

### Pattern: Array → Filter → Join

```svelte
$: classes = [
  'base-classes always-applied',
  condition1 ? 'conditional-group-1 with/special dark:chars' : '',
  condition2 ? 'conditional-group-2' : 'fallback-group',
  condition3 && 'single-conditional-class',
].filter(Boolean).join(' ');
```

**Why this works**: The `/`, `:`, `[`, `]` characters are inside JavaScript strings, not in Svelte template syntax. Svelte's parser never sees them as template tokens.

## Gotcha #2: Tailwind Purge + Dynamic Classes

### The Problem

Tailwind's JIT compiler only generates CSS for classes it finds in source files via static analysis. Dynamically constructed class names are invisible to the scanner.

```svelte
<!-- ❌ Class never generated — Tailwind can't see it -->
<div class="text-{color}-500">

<!-- ❌ Template literal — invisible to scanner -->
<div class={`bg-${variant}-100`}>
```

### The Fix: Use Complete Class Names

```svelte
<!-- ✅ Full class names, statically scannable -->
<div class={color === 'red' ? 'text-red-500' : 'text-blue-500'}>

<!-- ✅ Or safelist in tailwind.config -->
// tailwind.config.mjs
safelist: ['text-red-500', 'text-blue-500', 'text-green-500']
```

**Rule**: Every Tailwind class must appear as a complete, unbroken string somewhere in your source files or safelist.

## Gotcha #3: class: Directive Precedence

### The Problem

When combining `class="..."` with `class:name={condition}`, Svelte toggles the class but Tailwind's specificity may not work as expected.

```svelte
<!-- Ambiguous: does bg-blue-500 override bg-white when active? -->
<div class="bg-white" class:bg-blue-500={active}>
```

### The Fix

For conflicting properties, use the computed string pattern:

```svelte
$: bgClass = active ? 'bg-blue-500 text-white' : 'bg-white text-slate-900';
<div class="p-4 rounded {bgClass}">
```

Or ensure non-conflicting toggles (adding a class, not replacing):

```svelte
<!-- ✅ Safe: shadow-lg doesn't conflict with base classes -->
<div class="p-4 rounded bg-white" class:shadow-lg={elevated}>
```

## Gotcha #4: Svelte Transitions + Tailwind

### The Problem

Svelte's `transition:` and `animate:` directives add/remove elements. Tailwind's `transition-*` utilities conflict with Svelte's transition system.

```svelte
<!-- ❌ Svelte transition and Tailwind transition fight -->
<div transition:fade class="transition-all duration-300">
```

### The Fix

Choose one system per element:
- **Svelte transitions**: For mount/unmount animations (`transition:fade`, `transition:slide`)
- **Tailwind transitions**: For property changes on persistent elements (`hover:`, `focus:`, scroll-based)

```svelte
<!-- ✅ Svelte handles mount/unmount -->
{#if visible}
  <div transition:fade={{ duration: 200 }}>Modal content</div>
{/if}

<!-- ✅ Tailwind handles hover/state on persistent element -->
<button class="transition-colors duration-200 hover:bg-blue-500">Click</button>
```

## Quick Reference

| Tailwind Syntax | class: Directive | Computed String | Notes |
|----------------|-----------------|-----------------|-------|
| `bg-white` | ✅ Works | ✅ Works | Simple class, no special chars |
| `bg-white/80` | ❌ Breaks | ✅ Works | `/` = opacity shorthand |
| `dark:bg-slate-900` | ❌ Breaks | ✅ Works | `:` = variant prefix |
| `w-[100px]` | ❌ Breaks | ✅ Works | `[]` = arbitrary value |
| `hover:text-blue-500` | ❌ Breaks | ✅ Works | `:` = variant prefix |
| `shadow-sm` | ✅ Works | ✅ Works | Simple class |
| `-translate-y-1` | ✅ Works | ✅ Works | Leading `-` is fine |

**Rule of thumb**: If the Tailwind class contains `/`, `:`, `[`, `]`, or `.` → use computed string, not `class:` directive.

## Lessons Learned

| Date | Pattern | Root Cause | Fix |
|------|---------|-----------|-----|
| 2026-04-01 | `class:bg-white/80={scrolled}` in CorporateHeader.svelte breaks Svelte parser with "Unexpected token" | Svelte's parser interprets `/` inside `class:` directive as template syntax (tag close). Tailwind's opacity shorthand `bg-white/80` triggers this. | Replaced all `class:` directives with computed `headerClass` string using array→filter→join pattern. |
| 2026-04-01 | `class:dark:bg-slate-900/90={scrolled}` also breaks | Same root cause — `:` in Svelte class directive conflicts with directive syntax itself. | Same fix — computed class string. All special-char Tailwind classes go in JS strings, not template directives. |

---
name: batch-import-relative-paths
description: "When you batch-add an `import` line to N source files via sed/awk, the relative path must be computed PER-FILE (depth varies). Vite/esbuild often silently normalize bad `../` and the bug hides across multiple deploys until a larger rebuild forces strict module resolution."
metadata:
  short-description: "Sed-batched imports with hardcoded `../` chains break silently in Vite/esbuild — compute the path per-file with Python's os.path.relpath, then verify with a full build."
---

# Batch Import Relative Paths

## What

You have a new library module — say `src/lib/timing-safe-equal.ts` — that
you want to import into 10 sibling endpoints under
`src/pages/api/.../*.ts`. A `sed` one-liner that inserts
`import { X } from '../../../../lib/X';` after the last existing import
line LOOKS fine. The typecheck passes. The deploys pass. Then one day a
bigger rebuild fails with `Could not resolve "../../../../lib/X"` and
suddenly you discover the path was wrong all along — and you can't
trivially tell which of the 10 files had which depth.

## Why this happens

Two compounding failure modes:

### Mode A — Hardcoded `../` count assumes uniform depth

`sed` doesn't know how deep each file lives in the tree. If your batch
spans `src/pages/api/X.ts` (3 hops to `src/`) AND
`src/pages/api/internal/X.ts` (4 hops to `src/`), a single sed pass
applies the SAME `../` count to all of them — at least one set will be
wrong.

### Mode B — Vite / esbuild silently normalize extra `../`

When a relative path contains MORE `../` than the actual nesting, modern
bundlers do not error immediately. They collapse the excess at the
filesystem root and then fall through to:

1. Resolver plugins (Astro, SvelteKit, etc. each add their own).
2. Path aliases from `tsconfig.json` (`@lib/*`, `~/*`, etc.).
3. Cached resolved-module entries from prior builds.
4. Implicit `package.json#exports` fallthrough.

Any of these can "find" the module by sheer coincidence — especially in
incremental builds where the previous valid resolution is cached. Your
build passes. Your deploy works. The bug is latent.

A larger rebuild (different entry points, a clean cache, a refactor that
touches the resolver's input graph) finally forces strict re-resolution
and the latent bug surfaces.

### Mode C — Inserting BEFORE the close of a multi-line import block

If sed inserts the new line "after the last `^import ` line" without
checking whether that line is the OPEN of a multi-line block —

```ts
import {                              // <-- last `^import` line
  thingA,
  thingB,
import { newThing } from '../../...'; // <-- sed inserts HERE
} from '../../../lib/old-block';
```

— you get a parser-level syntax error: `Expected "as" but found "{"` or
`Unexpected token`. This is a separate-but-related failure mode of the
same naïve insertion strategy.

## When to suspect this

- Your CI just exploded with `Could not resolve "../../..."` after a
  PR that doesn't touch any imports.
- The `git blame` for the broken import points to a prior batch-insert
  PR that "deployed fine" weeks/days ago.
- `Expected "as" but found "{"` at a `column 7` in a TypeScript file
  whose line 1 is `import {`.
- Different files in the same batch use **the same** `../../../...`
  prefix despite living at different depths.

## Workflow — how to do batch imports correctly

### 1. Compute the relative path PER FILE with Python

```python
import os, sys

TARGET = 'src/lib/timing-safe-equal.ts'           # the new module
FILES = [
    'src/pages/api/X.ts',
    'src/pages/api/Y.ts',
    'src/pages/api/internal/Z.ts',
    'src/pages/api/internal/foo/W.ts',
]

for f in FILES:
    rel = os.path.relpath(TARGET, os.path.dirname(f))
    # Strip .ts/.tsx for the import string
    rel = rel.removesuffix('.ts').removesuffix('.tsx')
    print(f"{f}\n  import {{ X }} from '{rel}';")
```

This is the ONLY reliable way. `os.path.relpath` handles every depth
correctly; `sed` cannot.

### 2. Detect multi-line import blocks before inserting

Insert AFTER the last `} from '...'` (closing line of a multi-line
block) OR after the last single-line `^import ... from '...';`. Use
Python with a tiny regex, not sed:

```python
import re
from pathlib import Path

def insert_import(file_path: str, new_import: str) -> None:
    src = Path(file_path).read_text()
    lines = src.splitlines()
    last_idx = -1
    for i, line in enumerate(lines):
        s = line.strip()
        # Multi-line block CLOSE: } from '...';
        if re.match(r'\}\s*from\s*[\'\"].*[\'\"]\s*;?$', s):
            last_idx = i
        # Single-line import
        elif re.match(r'^import\s+.*\s+from\s+[\'\"].*[\'\"]\s*;?$', s) or \
             re.match(r'^import\s+[\'\"].*[\'\"]\s*;?$', s):
            last_idx = i
        # Type-only import
        elif re.match(r'^import\s+type\s+.*from\s+[\'\"].*[\'\"]\s*;?$', s):
            last_idx = i
    if last_idx < 0:
        # File has no imports; insert at top after any leading comment block
        last_idx = 0
    lines.insert(last_idx + 1, new_import)
    Path(file_path).write_text('\n'.join(lines) + '\n')
```

### 3. ALWAYS run a full project build before committing

```bash
# Astro
npx astro build

# SvelteKit
npm run build

# Next.js
next build

# Vite generic
npm run build
```

A full build forces strict module resolution and is the only signal
that catches Mode B. `tsc --noEmit` / `astro check` / `tsc --build` are
NOT enough — they validate type signatures but lean on the dev server's
lenient resolver.

## Anti-patterns

- **sed `s|FROM|TO|g` on multiple files with a single `../` chain.**
  The depth is almost never uniform; the breakage is silent.
- **Trusting `astro check` / `tsc --noEmit` as your only validation.**
  Both pass with broken relative paths because their resolver is more
  permissive than the production build resolver.
- **Inserting via `awk '/^import /{...}'` without recognizing multi-line
  `import { ... }` blocks.** Splits the block, breaks the parser.
- **Catching one file in a refactor and "fixing it" in isolation.**
  Sister files in the batch will still be wrong; you'll get a second
  failure 3 PRs later when a different rebuild path hits a different
  file.

## Diagnostic when the bug fires

```bash
# 1. Find every suspiciously-long ../ chain
grep -rEn "\.\./\.\./\.\./\.\./\.\." src/ 2>/dev/null

# 2. Compute the correct path for each hit
python3 -c "
import os
target = 'src/lib/<module>.ts'
for f in <files-from-grep>:
    print(f, '→', os.path.relpath(target, os.path.dirname(f)))
"

# 3. Patch + run full build
npx astro build 2>&1 | grep -E '(ERROR|Could not resolve|Build failed)'
```

## Lessons Learned

<!-- Append new cases as encountered. Include: date, framework, how many
files were silently broken, how many deploys passed before exposure. -->

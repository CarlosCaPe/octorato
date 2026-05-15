---
name: progressive-code-exploration
description: "Token-optimized code exploration using index-first, fetch-on-demand principle. Reduces token consumption 4-8x vs reading full files. Use when exploring large codebases, navigating files over 100 lines, or when token budget matters."
metadata:
  source: "Adapted from claude-mem smart-explore skill (thedotmack/claude-mem)"
  version: "1.0.0"
  adopted: "2026-04-13"
---

# Progressive Code Exploration

> Core principle: **Index first, fetch on demand.**
> The question before every file read: "do I need ALL of this,
> or can I get a structural overview first?"
> The answer is almost always: get the map.

## Triggers

- Exploring unfamiliar codebases or large files (>100 lines)
- Token budget constraints
- "explore this codebase", "find where X is defined"
- Cross-cutting feature analysis across many files
- When delegate-check recommends code exploration

## The 3-Layer Workflow

### Layer 1: Search -- Discover Files and Symbols

**Goal:** Find relevant files AND their structure in one pass.

```
# Use semantic_search or grep_search to discover, NOT read_file
semantic_search("shutdown handler")
grep_search("function.*shutdown", isRegexp=true, includePattern="src/**")
```

This replaces the Glob -> Grep -> Read discovery cycle.

**Output:** A mental map of relevant files, function names, line numbers.

### Layer 2: Outline -- Get File Structure

**Goal:** Understand a file's structure without reading its full content.

```
# Use grep_search with broad pattern to get file skeleton
grep_search("^(export |function |class |interface |const |type )",
            isRegexp=true, includePattern="src/services/worker.ts")
```

**Skip this layer** when Layer 1 already provided enough structure.

### Layer 3: Unfold -- Read Only What You Need

**Goal:** Read the specific function/section, not the whole file.

```
# Read ONLY the relevant lines, not the entire file
read_file("src/services/worker.ts", startLine=45, endLine=82)
```

**Never read an entire 500-line file when you need one 30-line function.**

## Decision Matrix: Which Tool When

| Need | Tool | Token Cost |
|------|------|-----------|
| "What files exist?" | file_search, list_dir | ~100 tokens |
| "Where is X defined?" | grep_search (exact string) | ~200-500 tokens |
| "What's in this file?" | grep_search (structural) | ~500-1,500 tokens |
| "Show me this function" | read_file (targeted range) | ~200-800 tokens |
| "Find all X across codebase" | semantic_search | ~2,000-6,000 tokens |
| "Full file content" | read_file (full) | ~5,000-15,000 tokens |
| "Cross-file synthesis" | runSubagent | ~20,000-60,000 tokens |

## Structural Grep Patterns (File Skeleton)

Get a file's structure without reading its full content:

### TypeScript/JavaScript
```
grep_search("^(export |import |function |class |interface |type |const |enum |async function)",
            isRegexp=true, includePattern="path/to/file.ts")
```

### Python
```
grep_search("^(class |def |async def |import |from .* import)",
            isRegexp=true, includePattern="path/to/file.py")
```

### Svelte
```
grep_search("^(<script|<style|export let|function |on:|{#|{:)",
            isRegexp=true, includePattern="path/to/Component.svelte")
```

## Workflow Examples

**Discover how a feature works (cross-cutting):**
```
1. grep_search("handleAuth|authentication", isRegexp=true, includePattern="src/**")
   -> 14 hits across 7 files, full picture of where auth lives
2. read_file("src/middleware/auth.ts", startLine=45, endLine=82)
   -> Just the core handler, not the entire 300-line file
Total: ~1,500 tokens vs ~15,000 to read all 7 files
```

**Navigate a large file (>300 lines):**
```
1. grep_search("^(export|function|class)", isRegexp=true, includePattern="src/services/api.ts")
   -> File skeleton: 15 exports, 3 classes, 8 functions (~500 tokens)
2. read_file("src/services/api.ts", startLine=120, endLine=155)
   -> The specific method (~300 tokens)
Total: ~800 tokens vs ~8,000 to Read the full file
```

**Write documentation about code (hybrid):**
```
1. semantic_search("payment processing")     -- discover all relevant files
2. grep_search (structural) on key files     -- understand structure
3. read_file (targeted) on important funcs   -- get implementation details
4. read_file (full) on small config/md files -- get non-code context
```

## Token Economics

| Approach | Tokens | Savings vs Full Read |
|----------|--------|---------------------|
| Structural grep | ~500-1,500 | 5-10x |
| Targeted read_file | ~200-800 | 10-30x |
| grep + targeted read | ~800-2,000 | 4-8x |
| Full file read | ~5,000-15,000 | baseline |
| runSubagent (cross-file) | ~20,000-60,000 | -3x (more expensive) |

## Integration with Existing Skills

- **deep-grep-code-review** -- Use Layer 1-2 to find files, then deep-grep for
  exhaustive verification of specific patterns
- **token-efficient-prompting** -- This skill reduces INPUT tokens (what we read);
  that skill reduces OUTPUT tokens (what we generate). Complementary.
- **orchestrated-planning** -- Phase 0 Doc Discovery should use progressive
  exploration to minimize token cost during research

## When to Use Standard Approaches Instead

- **Small files (<100 lines)**: Just read_file the whole thing
- **Exact string search**: grep_search is faster than structural exploration
- **Non-code files** (JSON, YAML, markdown): read_file directly
- **Full synthesis needed**: runSubagent when you need cross-file understanding

## Anti-Patterns

- Reading entire 500-line files to find one function
- Running read_file 10 times sequentially on the same file
- Using runSubagent for simple "where is X?" questions
- Skipping Layer 1 (search) and going straight to Layer 3 (read)

## Lessons Learned

1. **4-8x savings** on file understanding (outline + targeted read vs full read)
2. **The narrower the query, the wider the gap** -- a 30-line function costs 20x
   less to read via targeted range than via full file read
3. **Structural grep is underused** -- most files have clear patterns (export,
   function, class) that reveal structure without reading content
4. **Parallel discovery beats sequential** -- batch grep_search calls for
   related patterns instead of reading one file at a time

---
name: repomix-codebase-packer
description: "Empaqueta un repo completo, local o remoto, en un solo archivo optimizado para LLM, con compresion Tree-sitter (~70% menos tokens) y escaneo de secretos. Para auditar un repo entero o preparar contexto de un subagente."
---

# Repomix — Codebase to Single AI-Friendly File

Packs a repo into one structured file (XML / Markdown / JSON / plain text) with metadata, directory tree, per-file token counts, and optional compression. Respects `.gitignore`, includes Secretlint to flag secrets before you paste into an LLM.

Repo: https://github.com/yamadashy/repomix · MIT · `npx repomix@latest`

## When to use

- Sending a whole arm/repo to Claude for architectural review, security audit, or refactor planning
- Preparing context for an `Explore` or `general-purpose` subagent that needs cross-file awareness
- Onboarding a new client repo — pack it once, ask Claude "explain what this does" against the pack
- Generating documentation / tests for a small-to-medium codebase
- Auditing an external OSS dependency before adopting it (pack the remote with `--remote`)

## When NOT to use

- Repo > ~200K tokens even after compression — chunk by directory instead, or use progressive exploration
- You only need one file — `Read` is cheaper than packing the whole repo
- Sensitive client data — pack respects `.gitignore` but Secretlint is not a substitute for a security review; never paste a pack into a third-party LLM without confirming the arm's data classification

## Install

```bash
# zero-install (recommended for ad-hoc)
npx repomix@latest

# global
npm install -g repomix
```

## Core commands

```bash
# pack current directory → repomix-output.xml
repomix

# Markdown output (easier to skim in a code review)
repomix --style markdown

# Tree-sitter compression — drops bodies, keeps signatures (~70% fewer tokens)
repomix --compress

# scope: include/exclude
repomix --include "src/**/*.ts" --ignore "**/*.test.ts,**/*.spec.ts"

# pack a remote repo without cloning
repomix --remote yamadashy/repomix
repomix --remote https://github.com/CarlosCaPe/octorato --remote-branch main

# split output if it blows the context window
repomix --split-output 1mb

# include git context for "why" questions
repomix --include-logs --include-diffs

# token distribution by directory (find the heavy folders before packing)
repomix --token-count-tree 1000
```

## MCP server mode (registered in this brain)

This brain has repomix registered as an MCP server. Inside Claude Code you can call its tools directly without shelling out:

```bash
# registration command (already executed for this brain — for reference only)
claude mcp add repomix -- npx -y repomix --mcp
```

When the MCP is active, Claude can request `pack_codebase`, `pack_remote_repository`, and related tools as native tool calls — no temp file roundtrip.

## Patterns for this brain

**Arm code review.** Inside an arm repo: `repomix --compress --style markdown --ignore "**/node_modules/**,**/.next/**,**/dist/**"` → paste into Claude with prompt "act as Code Reviewer agent, audit this for security + maintainability".

**External OSS audit.** Before adopting a new dependency: `repomix --remote <org/repo> --compress` → ask Claude for license risk, maintainer activity, abandoned-fork detection. Pair with `bruno-postman-alternative` / `tabularis-db-client` evaluations.

**Subagent prep.** When dispatching an `Explore` or `general-purpose` agent for whole-repo questions, pack first and hand it the file path — saves the agent N tool calls and keeps token cost predictable.

**Pre-paste safety.** Always skim the Secretlint warnings printed by repomix before pasting into ANY external LLM. The brain rule "never echo back user-provided secrets" applies to whole-repo dumps.

## Companion skills

- `progressive-code-exploration` — when the repo is too big to pack, use index-first instead
- `token-efficient-prompting` — once packed, ask compact questions
- `security-threat-model` — feed the pack into a structured threat-model pass
- `code-review` — natural downstream skill after `repomix --compress`
- `agent-browser` — for live web targets repomix can't reach (it's repo-only)

## Caveats

- `--compress` uses Tree-sitter; works best on Python, TS/JS, Go, Rust, Java. For exotic languages output may degrade to raw chunks.
- Secretlint catches common patterns (AWS keys, GH tokens, Stripe) but is not exhaustive. Never assume a pack is safe to share publicly.
- Remote packing clones to a temp dir; large monorepos can take minutes. Prefer `--include` to scope down.

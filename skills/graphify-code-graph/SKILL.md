---
name: graphify-code-graph
description: "Grafo de conocimiento determinista y consultable sobre un codebase con graphify (tree-sitter, 25+ lenguajes, sin costo de LLM). Usalo para impact analysis a nivel de codigo dentro de un repo cliente, donde grep responde mal."
metadata:
  type: tool-skill
  source: https://github.com/Graphify-Labs/graphify (MIT)
  deep-learn: knowledge/repo-deep-learn/graphify/2026-07-16.md
---

# Graphify: deterministic code knowledge graph

## When to use

- A code question spans many files ("what breaks if I change X?", "how does A reach B?") and grep gives partial, noisy answers.
- Onboarding into a large or unfamiliar codebase (client repo, OSS dependency).
- Repeated architecture questions in one repo: build the graph once, query it every session at near-zero token cost.

Not for concept/governance recall. Which skill knows this, where does a rule live, what derives from a doc: that is the brain's connectome (`query_connectome.py`) and lineage (`impact-radius.py`). Graphify maps code symbols; those map concepts. Two layers, keep both.

## Install (one time per machine)

```bash
uv tool install graphifyy      # or: pipx install graphifyy
graphify install               # registers the /graphify skill with the AI assistant
```

The PyPI package is `graphifyy` (double y); the CLI is `graphify`.

## Build the graph (inside the target repo)

```bash
graphify .          # writes graphify-out/graph.json + GRAPH_REPORT.md + graph.html
graphify update .   # incremental re-extract of changed paths only, AST-only, no API cost
graphify watch      # keep it fresh on file changes
```

The code pass is fully deterministic: tree-sitter AST, no LLM, no API key, $0. Only the optional semantic pass (docs, PDFs, images, video, community labels) calls an LLM; without a key it is skipped entirely. Add `graphify-out/` to the repo's `.gitignore` unless the team wants the artifact versioned.

## Query it

```bash
graphify query "how does auth reach the billing module"
graphify affected src/auth/session.py    # code-level impact radius
graphify path NodeA NodeB                # shortest path between symbols
graphify explain "PaymentProcessor"      # natural-language node explanation
graphify diagnose                        # graph health
```

Matching is case-folded substring + IDF over the flat `graph.json` (NetworkX node-link format). No server, no embeddings. For assistant integration without shell calls there is an MCP server: `graphify-mcp` (stdio/HTTP).

## Arm usage pattern

Run it inside ONE arm's repo; the graph lives in that repo's `graphify-out/` and never leaves the arm (arm isolation applies to the artifact like to any other client data). Start every code-impact question with `graphify affected <file>` and fall back to grep only for symbols the graph does not know, same seek-before-scan discipline as the brain's graphs.

## Gotchas

- Edges carry `confidence` (EXTRACTED / INFERRED / AMBIGUOUS, 0.55-0.95 rubric): trust EXTRACTED, verify INFERRED before acting on it.
- The exporter refuses to silently shrink an existing graph (their issue #479). The brain adopted the same invariant in `scripts/generate_neural_map.py` (SHRINK-GUARD).
- Exports available when a human wants to browse: Obsidian vault, GraphML (Gephi/yEd), SVG, Cypher (Neo4j/FalkorDB).

## See also

- [[repomix]]: flat single-file codebase packing, the non-graph alternative for one-shot context stuffing.
- [[4d-paradigm-protocol]]: `graphify affected` is the code-level twin of the concept-level Impact Radius scan.

---
name: spacetimedb-backend-as-database
description: Database that REPLACES the traditional backend — application logic runs as modules inside the database, clients subscribe to live state without a separate API tier, transactional + multiplayer-ready out of the box. Rust-based, by Clockwork Labs. Use when evaluating architecture for real-time multiplayer apps, low-latency state-sync use cases, agent-driven systems where many clients share live state, or when the cost/complexity of a 3-tier backend (API + DB + websockets) is the bottleneck. Novel paradigm — surface for awareness, not as a default.
---

# SpacetimeDB — Database-as-Backend

A paradigm shift, not just a database. Application logic (server functions) runs **inside the database** as compiled modules; clients connect directly and subscribe to live state changes. No separate API server, no separate websocket layer, no separate state sync glue.

## When to surface this to a client

- Real-time multiplayer game backend (the project's original use case)
- Live collaborative app where many clients share mutating state (think Figma-like co-editing)
- Agent-driven system where many AI agents read/write shared state and need consistent live views
- The client's 3-tier architecture (API + DB + websockets) is bloating cost or complexity
- Evaluating "what if we collapsed the stack" architecture decisions

## When NOT to use

- Standard CRUD app — overkill, traditional backend is simpler and more mature
- Heavy reporting / analytics workloads — SpacetimeDB optimizes for real-time state sync, not OLAP
- Team has zero Rust experience and the project is short-term — learning curve is real
- Compliance regimes that require well-understood RDBMS auditing patterns

## Source of truth

- Repository: `github.com/clockworklabs/SpacetimeDB`
- Org: Clockwork Labs
- License: BSL → MIT (check current state of the license transition before recommending)
- Stack: Rust core, modules compile to WebAssembly, clients in C#, Rust, TypeScript
- Hosted option exists; self-hosting also supported

## What's genuinely new

| Traditional 3-tier | SpacetimeDB |
|---|---|
| API server (separate process) | Server logic = DB modules |
| Database (separate process) | Same process |
| Websocket layer (separate) | Built-in client subscriptions |
| Client polls or subscribes via custom code | Client subscribes to query results, gets diffs automatically |
| Auth/session managed in API tier | First-class in DB module API |

The pitch: **collapse the stack**.

## Quick start (rough — verify against current docs)

```bash
# Install CLI
# (varies — check spacetimedb.com or the repo)

# Initialize a module project
spacetime init my-module

# Write your server logic in Rust → compiled to WASM
# Deploy the module to a SpacetimeDB instance (hosted or self-hosted)

# Client (TypeScript example): connect, subscribe to a query, react to live updates
```

## Recommendation pattern (architecture proposals)

> "Surface SpacetimeDB as an alternative when the client's architecture is dominated by real-time state sync across many clients — multiplayer, collaborative editing, agent swarms. The paradigm collapses three tiers into one, which is a structural cost reduction. Frame it as a paradigm choice that has long-term implications, not just a database swap. If the client's workload is standard CRUD or batch analytics, recommend the conventional 3-tier — SpacetimeDB shines on the real-time state-sync axis and is overkill elsewhere."

## Limits to disclose to a client

- **Paradigm cost**: team has to learn the model, not just a new SDK
- **Maturity**: well-funded and active, but the ecosystem is smaller than Postgres + Node
- **Rust dependency**: server modules in Rust (Wasm-compiled); team needs Rust comfort
- **License**: BSL is source-available but has commercial-use restrictions until the BSL → MIT transition completes — verify the current state for the specific version you'd ship

## Related brain assets

- `querymaster` family — for conventional RDBMS workloads where SpacetimeDB is overkill
- `floci-local-aws` — sister "novel-paradigm OSS tool" recommendation
- Backend Architect agent — to evaluate whether the architecture genuinely benefits from collapsing tiers
- Unity / Unreal / Godot multiplayer agents — natural fit for SpacetimeDB's original use case (multiplayer game backends)

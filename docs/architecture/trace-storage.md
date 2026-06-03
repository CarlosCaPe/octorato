# Trace Storage Layout — Agent Trace (observability surface 1)

> Phase A task #2 deliverable. Locks the on-disk contract for the trace
> infrastructure before any capture hook (tasks #3-#5) or CLI query helper
> (task #6) is written. Subsequent tasks read from / depend on this layout.

## Where traces live

```
~/.claude/traces/
├── 2026-05-18.jsonl
├── 2026-05-19.jsonl
├── ...
└── 2026-06-17.jsonl     ← (after 30d) auto-deleted by retention sweep
```

- One file per **UTC day**, name format `YYYY-MM-DD.jsonl`.
- Path is **gitignored** at the brain level (entry added to `~/.claude/.gitignore`).
- Each line conforms to `~/.claude/schemas/trace-event.schema.json` (Phase A task #1).
- The directory is created lazily on first write — no init step needed.

## Privacy stance

**Gitignored by default** (decision §9 Q3, 2026-05-18). Traces never enter the
public octorato repository, never sync via `ai-push`, never propagate via
`sync-ai-docs`. They are machine-local — like `state/`, `digests/`, `cache/`,
or the `projects/.../memory/` directory.

Rationale: trace events can contain operator-specific signal (which skills
fired on which days, error patterns, token costs). Even fully anonymized, the
operational pattern itself is private. Surfacing it in a public repo would
leak "how the operator works" without adding any value for outside readers.

## Retention — auto-delete at 30 days

Files older than 30 days are **deleted, not archived**.

| Concern | Resolution |
|---|---|
| Why 30d, not 7d or 90d? | 30d covers one full Hebbian decay window (~half of the 69d half-life) — enough to spot weekly + monthly patterns without unbounded growth |
| What if I want longer history? | Enable the backup opt-in (see below) to sync `.jsonl` files to a private repo before they hit the 30d cutoff |
| Manual override per file? | None. The sweep is unconditional. If a specific day matters, copy it out of `~/.claude/traces/` before day 30 |

**Sweep mechanism** (implemented in Phase A task #7 or a sibling cron job):

```bash
# Run from a daily cron or via ~/.claude/scripts (Phase A wiring)
find ~/.claude/traces -name "*.jsonl" -mtime +30 -delete
```

The `-mtime +30` predicate uses the file's mtime, which matches its UTC day
since each file is append-only and never re-touched.

## Backup opt-in — `TRACE_BACKUP_REPO` env var

By default, traces are local-only. To sync them across machines or keep
arbitrarily long history, set the environment variable:

```bash
export TRACE_BACKUP_REPO=git@github.com:<operator>/<private-traces-repo>.git
```

When set, a daily backup hook will (Phase A task #7+ scope):
1. `git clone --depth 1` the repo to a temp dir if not cached
2. Copy any `~/.claude/traces/*.jsonl` files newer than the last backup marker
3. Commit + push with message `chore(backup): traces YYYY-MM-DD`

When **unset**, no backup runs. The default behaviour is local-only — explicit
opt-in keeps the system simple and lets the operator pick a private repo per
threat model (separate account, separate host, separate encryption).

The brain itself never reads from `TRACE_BACKUP_REPO`. Only the backup hook
process touches it.

## Concurrency — POSIX `O_APPEND` + `fsync`

Multiple processes (main agent + subagents + scheduler workers) may write to
the same daily file. The on-disk write contract:

1. Open with `O_APPEND` (Python: `open(path, "a")` does this).
2. Write exactly one JSONL line per event, terminated with `\n`.
3. Each line must be **strictly smaller than 4096 bytes** (the POSIX
   `PIPE_BUF` atomicity guarantee for appends).
4. `fsync()` after each write only if the operator considers the event
   load-bearing (default: skip fsync; the OS page cache is fine for
   observability data — if the machine crashes we lose the last few events,
   not history).

No file locking is used. POSIX guarantees that appends < 4096 bytes are
atomic when `O_APPEND` is set — two processes writing simultaneously will
produce two complete adjacent lines, never an interleaved partial line.

If a record ever needs more than 4096 bytes (e.g. a future event class with a
large `error` blob), the contract changes: either trim before write, split
into multiple records, or wrap with `flock`. Today's schema caps `error` at
500 chars, keeping all records comfortably below the threshold.

## Schema versioning + on-disk evolution

Each record carries `schemaVersion: "1.0"`. When the schema bumps:

| Change type | Action |
|---|---|
| Additive (new optional field) | Bump version to `1.1`, old records still validate against the v1 reader because new fields are optional |
| Breaking (rename, remove, retype) | Bump major (`2.0`) and add a new `$id` path (e.g. `trace-event-v2.json`). Readers must handle both versions side-by-side during transition |
| New event class | Add to the enum, bump version (minor or major depending on whether existing readers can ignore unknown classes) |

Old `.jsonl` files keep their original `schemaVersion` forever. The query
tooling (Phase A task #6 `trace.py`) reads the version per-record and dispatches
to the right validator.

## What this storage layout does NOT do

- **No real-time streaming.** Traces are append-only flat files. If you need
  live tail, use `tail -f ~/.claude/traces/$(date -u +%Y-%m-%d).jsonl`.
- **No remote write.** Every event lands on the local disk first. Backup
  syncs in batches, not per-event.
- **No tamper-resistance.** A motivated operator can edit `.jsonl` files by
  hand. The trace is observability, not audit log.
- **No encryption at rest.** Files are plain JSON. If the machine is
  compromised, traces are readable. Threat model: the laptop is trusted; the
  public repo is not.
- **No cross-arm correlation.** Each event has an `arm` field (nullable),
  but the trace itself does not bridge between arms. Arm isolation rule
  still applies.

## Cross-references

- Schema: `~/.claude/schemas/trace-event.schema.json`
- Memory: [[user-operator-runway]] (runway is clean — observability surfaces
  can take the time they need)

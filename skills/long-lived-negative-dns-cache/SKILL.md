---
name: long-lived-negative-dns-cache
description: "A long-running process (a cron supervisor, a daemon, a worker pool parent) caches a NEGATIVE DNS result after a transient network blip and then never retries, so every downstream call fails forever even though the network recovered seconds later. A wrapper bug can log a fake `exit=0`, hiding it. Symptom: 'nothing runs anymore' with no error. Fix: restart the process, then bound the DNS/connection cache TTL."
metadata:
  short-description: "Long-lived process caches a failed DNS lookup after a network blip and never re-resolves; a wrapper logs fake exit=0 masking it. 'Nothing runs' with no error. Restart + cap the negative-cache TTL."
---

# Long-Lived Process Negative DNS Cache

## What

A process that stays up for days or weeks (a Python cron supervisor, a
scheduler parent, a connection-pooling daemon) suddenly stops doing useful
work. No error in the logs. No crash. The init system shows it `active`.
Restarting it fixes everything instantly.

The trigger was a brief network blip (a few seconds of no connectivity:
laptop sleep, Wi-Fi handoff, VPN reconnect, host migration). During that
window the process tried to resolve a hostname, got a failure, and CACHED
the failure. After the network came back, the process keeps serving the
cached negative result and never re-resolves. Every outbound call to that
host now fails for the lifetime of the process.

## Why this happens

Two layers compound:

### Layer 1 - the negative cache that never expires

Some resolvers, HTTP client libraries, or connection pools cache a
resolution FAILURE in-process with no TTL, or with a TTL far longer than
the blip. A short-lived process never hits this (it re-resolves on the
next run). A long-lived one caches once and is stuck until restart. This
is the inverse of the usual "stale positive DNS" problem: here the stale
entry is a NEGATIVE one.

### Layer 2 - the wrapper that hides it

A supervising wrapper (a shell loop, a `try/except` that logs and
continues, a task runner that swallows the child's real status) reports a
fake `exit=0` or "ok" even though the inner work never reached the host.
So monitoring sees green while nothing actually happens. The only honest
signal is "the expected side effects stopped appearing" (no new rows, no
published posts, no fired jobs).

## The fix

1. **Immediate:** restart the process. `systemctl --user restart <unit>`
   (or the equivalent). It re-resolves on startup and recovers.
2. **Durable - bound the negative cache.** Cap the resolver / client
   negative-cache TTL so a blip self-heals within minutes:
   - Python `socket`/`urllib3`: avoid module-level cached resolvers that
     outlive a request; create the client per-batch, or set a connection
     pool with a finite `ttl`.
   - System resolver (`systemd-resolved`, `nscd`): cap negative TTL.
   - For schedulers, prefer re-resolving per-tick over caching the host
     across ticks.
3. **Make the wrapper honest.** The supervisor must propagate the child's
   real exit status, not log a synthetic `exit=0`. A masked failure is
   worse than a loud one because it burns days before anyone notices.

## How to diagnose

- Symptom is "nothing runs / nothing publishes" with NO error and the
  service still `active`.
- A restart fixes it instantly and completely. That alone strongly implies
  in-process cached state (DNS, connection, auth) rather than a code bug.
- Correlate the stop time with a known network event (sleep, VPN, host
  move). The blip is usually minutes before the silence began.

## Anti-pattern

Trusting `exit=0` / "active" as proof of work. For long-lived background
processes, health = "the side effects are still appearing," not "the
process is up." Pair this with a side-effect heartbeat sentinel where it
matters.

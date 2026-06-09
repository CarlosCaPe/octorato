---
name: deterministic-shutdown-backstop
description: "A long-lived service that hangs INTERMITTENTLY on SIGTERM (non-reproducible, the init system kills it at the timeout, a false OnFailure alert fires and then self-recovers) is not a bug to chase. Install a deterministic daemon-timer backstop (os._exit after N seconds) inside the shutdown path. The race is unfixable by inspection; the backstop is."
metadata:
  short-description: "Intermittent non-reproducible hang on shutdown: don't chase the race, arm a daemon-timer os._exit backstop so teardown is bounded and the false OnFailure alert stops."
---

# Deterministic Shutdown Backstop

## What

A long-running service (a worker supervisor, an orchestrator's blocking
`serve()` loop, an event-consumer daemon) hangs on shutdown only SOME of
the time. The symptom chain is:

1. The init system (systemd, k8s, supervisord) sends SIGTERM.
2. The process's own shutdown handler stalls instead of exiting.
3. The init system waits its grace period (commonly 30s), then SIGKILLs.
4. An `OnFailure` / restart alert fires, looks like an incident.
5. By the time anyone looks, the service is already back up. It "fixed
   itself." The next 20 restarts are clean. Then it happens again.

Non-reproducible in a minimal repro (a bare `serve()` shuts down in ~2s),
so you cannot validate a surgical fix. Upgrading the framework version
does not help because the hang is in the interaction between a synchronous
stop-and-wait call and a network client talking to a server that is
itself already dying.

## Why this happens

The shutdown handler does something that can block UNBOUNDEDLY:

- A synchronous `stop().result()` that waits on a future which never
  resolves because the thing it waits on is also shutting down.
- An events/telemetry flush that tries to reach a server (ConnectionRefused
  against a moribund endpoint) and retries with backoff inside the SIGTERM
  window.
- A lock or queue drain with no deadline.

Any one of these turns "exit now" into "exit eventually, maybe." Because
it depends on timing between two dying components, it is a race: it shows
up under load and vanishes under inspection. You cannot prove a fix
correct because you cannot make it fail on demand.

## The fix: a bounded backstop, not a better race

Stop trying to make the graceful path fast. ACCEPT that it can hang, and
GUARANTEE an upper bound on teardown with a separate, dumb timer that does
not depend on any of the blocking machinery:

```python
import os, threading, signal

SHUTDOWN_DEADLINE_S = 20  # < the init system's grace period (e.g. 30s)

def _arm_backstop():
    # daemon=True so the timer never KEEPS the process alive on its own.
    t = threading.Timer(SHUTDOWN_DEADLINE_S, lambda: os._exit(0))
    t.daemon = True
    t.start()
    return t

def handle_sigterm(signum, frame):
    _arm_backstop()          # FIRST: guarantee we exit within the deadline.
    graceful_stop()          # THEN attempt the clean path; if it hangs, the timer wins.

signal.signal(signal.SIGTERM, handle_sigterm)
```

Key properties:

- **`os._exit`, not `sys.exit`.** `sys.exit` raises an exception that the
  hung handler can swallow. `os._exit` is immediate and uncatchable. That
  is the point: the backstop must not be blockable by the thing it is
  backstopping.
- **Deadline strictly under the init system's grace period.** If systemd
  kills at 30s, fire at ~20s. You want a clean self-exit (exit 0) recorded,
  not a SIGKILL that trips the failure alert.
- **`daemon=True`.** The timer must never be the reason the process stays
  alive; it only fires if the process is still up at the deadline.
- **Arm the timer BEFORE calling the graceful stop**, so a hang in the
  graceful stop is already covered.

## When to reach for this

- Intermittent hang on SIGTERM / SIGINT that you cannot reproduce.
- A false-positive restart/OnFailure alert that always self-clears.
- Surgery is unvalidatable because the failure is a timing race between two
  shutting-down components.

Do NOT use it to paper over a graceful path that ALWAYS hangs (that is a
real deadlock to fix). The backstop is for the unreproducible tail, where
chasing the race costs more than bounding it.

## Anti-pattern

Bumping the framework version and hoping. If the hang is in the
stop-and-wait + dying-network-client interaction, the new version usually
ships the same shape. Bound the teardown instead of trusting the upstream
fix.

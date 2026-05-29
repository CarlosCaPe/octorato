"""Octorato hook profile + disable-list parsing.

Adopted from affaan-m/ECC (scripts/lib/hook-flags.js) — runtime hook gating
without editing hook files. Read by every hook script via:

    from lib.hook_flags import profile, is_disabled
    if is_disabled("pre:bash:tmux-reminder"): sys.exit(0)
    if profile() == "minimal" and not always_on(): sys.exit(0)

Env vars:
- OCTO_HOOK_PROFILE=minimal | standard | strict   (default: standard)
- OCTO_DISABLED_HOOKS=hook1,hook2,...             (default: empty)

Profile semantics:
- minimal:  only "always_on" hooks run (leak-guard, secret-scan, hooks-drift)
- standard: default — everything except hooks tagged `strict_only`
- strict:   everything including `strict_only` hooks (e.g. extra type-checks, slow scans)

A hook is identified by a short id (e.g. `pre:bash:tmux-reminder`); the id
is the hook script's own choice (passed to `is_disabled`). Hook scripts
that don't opt into this system are always active — that preserves the
existing behavior of any hook not yet ported.
"""
from __future__ import annotations

import os
from typing import Literal

Profile = Literal["minimal", "standard", "strict"]

_VALID_PROFILES = {"minimal", "standard", "strict"}


def profile() -> Profile:
    """Resolve OCTO_HOOK_PROFILE → one of {minimal, standard, strict}.

    Falls back to 'standard' on any unrecognized value (with a stderr warning
    suppressed — hooks must stay quiet on hot paths).
    """
    raw = os.environ.get("OCTO_HOOK_PROFILE", "standard").strip().lower()
    return raw if raw in _VALID_PROFILES else "standard"  # type: ignore[return-value]


def _disabled_set() -> frozenset[str]:
    raw = os.environ.get("OCTO_DISABLED_HOOKS", "")
    return frozenset(s.strip() for s in raw.split(",") if s.strip())


def is_disabled(hook_id: str) -> bool:
    """True if `hook_id` is listed in OCTO_DISABLED_HOOKS.

    `hook_id` is the hook script's self-declared identifier, e.g.
    `pre:bash:tmux-reminder` or `post:edit:typecheck`. Convention:
    `<phase>:<event>:<short-name>`.
    """
    return hook_id in _disabled_set()


def should_run(hook_id: str, *, always_on: bool = False, strict_only: bool = False) -> bool:
    """One-call decision for a hook script.

    Returns True if the hook should execute, False if it should exit 0 immediately.

    - `always_on=True` → runs regardless of profile (use for leak-guard, secret-scan).
    - `strict_only=True` → runs ONLY when profile == 'strict'.
    - Default behavior: runs in 'standard' + 'strict', skipped in 'minimal'.

    `OCTO_DISABLED_HOOKS` overrides everything except `always_on`.
    """
    if always_on:
        return True  # leak-guard etc. cannot be disabled via env
    if is_disabled(hook_id):
        return False
    prof = profile()
    if prof == "minimal":
        return False
    if strict_only and prof != "strict":
        return False
    return True


__all__ = ["profile", "is_disabled", "should_run", "Profile"]

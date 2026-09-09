#!/usr/bin/env python3
"""Kill a child's process group without ever killing our own.

ONE implementation, imported by every spawner that needs it, because this is a
primitive where a second copy is not duplication but a live hazard. The copy that
existed proved it: `install-skill-from-github.py` called
`os.killpg(os.getpgid(proc.pid), SIGKILL)` with no guard, two lines below its own
`start_new_session=True`, and when a mutant removed that flag the call did not fail a
test, it SIGKILLed the test runner (`exit -9`, no summary printed). The guard belongs
next to the syscall, once, not next to each caller who remembers it.

Why a group at all: the direct child is often a shell or a porcelain command that has
forked the process actually doing the work. `git clone` over ssh runs `ssh` as a
grandchild, and that grandchild is the one holding the terminal. Killing only the child
returns a tidy rc 124 while the real process is still alive on the prompt, which is the
exact wedge the deadline exists to end.

WHAT THIS CANNOT REACH, measured, and load-bearing for anyone reading a clean timeout:
a descendant that puts ITSELF in a new session or process group (setsid, setpgid) is no
longer in the group being killed and survives. `group_gone` will not see it either, so
such a survivor is reported as an ordinary timeout with no warning at all. A double-fork
daemon that stays in the group does die. The reach of this module is the group, not the
process tree, and nothing here should be read as promising otherwise.
"""

from __future__ import annotations

import os
import signal

# SIGKILL, not SIGTERM, because the thing being killed has already ignored a deadline
# and may be a shell that would pass a catchable signal to nobody. A child that traps
# TERM survives it; the test suite pins that with a child that does exactly that.
KILL_SIGNAL = getattr(signal, "SIGKILL", getattr(signal, "SIGTERM", 15))


def kill_group(proc) -> bool:
    """SIGKILL the group of `proc`. True when the GROUP call is what landed.

    False means the fallback ran: the caller's own group (see below), a platform with
    no killpg, or a pid already reaped. The caller should treat False as "the direct
    child was killed and descendants may remain".
    """
    if hasattr(os, "killpg"):
        try:
            group = os.getpgid(proc.pid)
            # The guard, and the reason this module exists. A group kill is safe only
            # because the spawner passed start_new_session=True and the child leads a
            # group of its own. If that ever comes off, the child shares OUR group and
            # this line kills the caller, its runner, and every sibling process.
            if group != os.getpgid(0):
                os.killpg(group, KILL_SIGNAL)
                return True
        except (ProcessLookupError, PermissionError, OSError):
            pass
    proc.kill()          # Windows, an already-dead group, or a child sharing ours
    return False


def group_gone(proc, group: int | None) -> bool:
    """Whether the killed group still has members.

    Asked directly with signal 0, which tests for existence and delivers nothing. The
    previous version inferred this from whether the output pipe was still held, which
    answered a different question: a survivor that closed its pipe came back as a clean
    timeout with no warning. Silence is not an answer.

    True when there is nothing left to warn about, which includes the case where we
    never learned the group id.
    """
    if group is None or not hasattr(os, "killpg"):
        return True
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return True      # cannot tell; do not cry wolf
    return False


def group_of(proc) -> int | None:
    """The child's process group, or None if it is already gone. Read BEFORE the kill:
    afterwards the pid may be reaped and getpgid raises."""
    if not hasattr(os, "getpgid"):
        return None
    try:
        return os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError, OSError):
        return None

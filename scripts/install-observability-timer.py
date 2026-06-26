#!/usr/bin/env python3
"""install-observability-timer.py - schedule the brain's daily observability digest.

The digest (scripts/brain-digest.py, which chains slos/watchdog/finops) reads
LOCAL session JSONL under ~/.claude/projects, so it must run on the operator's
own machine, not in CI. This installer wires it as a systemd --user timer so it
fires daily and, thanks to Persistent=true, recovers a run missed while the
laptop was asleep (the multi-machine reality).

Idempotent: safe to re-run. Run it once per machine.

  python3 ~/.claude/scripts/install-observability-timer.py            # install + enable
  python3 ~/.claude/scripts/install-observability-timer.py --status   # show timer state
  python3 ~/.claude/scripts/install-observability-timer.py --uninstall # disable + remove

If systemd --user is not available, it prints a cron fallback and exits 0
(never fails the brain over a scheduling backend it cannot find).
"""
from __future__ import annotations
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

BRAIN = Path.home() / ".claude"
TEMPLATES = BRAIN / "templates" / "systemd"
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
UNITS = ["octorato-brain-digest.service", "octorato-brain-digest.timer"]
TIMER = "octorato-brain-digest.timer"


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args],
                          capture_output=True, text=True)


def systemd_user_available() -> bool:
    if sys.platform != "linux" or not shutil.which("systemctl"):
        return False
    # is-system-running returns running/degraded (both usable) when the user
    # manager is up; it errors with "Failed to connect to bus" when it is not.
    probe = _systemctl("is-system-running")
    return "Failed to connect" not in (probe.stderr or "")


def _cron_fallback() -> int:
    line = "0 7 * * *  /usr/bin/env python3 %s/scripts/brain-digest.py" % BRAIN
    print("systemd --user is not available on this machine.")
    print("Cron fallback: add this line with `crontab -e` (runs daily at 07:00):")
    print("  " + line)
    return 0


def install() -> int:
    if not systemd_user_available():
        return _cron_fallback()
    missing = [u for u in UNITS if not (TEMPLATES / u).is_file()]
    if missing:
        print("ERROR: missing unit template(s): %s" % ", ".join(missing))
        return 1
    USER_UNIT_DIR.mkdir(parents=True, exist_ok=True)
    for u in UNITS:
        shutil.copyfile(TEMPLATES / u, USER_UNIT_DIR / u)
        print("installed: %s" % (USER_UNIT_DIR / u))
    _systemctl("daemon-reload")
    en = _systemctl("enable", "--now", TIMER)
    if en.returncode != 0:
        print("ERROR enabling timer: %s" % (en.stderr or en.stdout).strip())
        return 1
    print("enabled + started: %s" % TIMER)
    return status()


def status() -> int:
    if not systemd_user_available():
        return _cron_fallback()
    lst = _systemctl("list-timers", "--all", TIMER)
    out = (lst.stdout or "").strip()
    print(out if out else "(timer not found; run without --status to install)")
    return 0


def uninstall() -> int:
    if not systemd_user_available():
        print("systemd --user not available; nothing to uninstall.")
        return 0
    _systemctl("disable", "--now", TIMER)
    for u in UNITS:
        target = USER_UNIT_DIR / u
        if target.exists():
            target.unlink()
            print("removed: %s" % target)
    _systemctl("daemon-reload")
    print("uninstalled: %s" % TIMER)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Install the brain observability digest timer.")
    ap.add_argument("--status", action="store_true", help="show timer state and exit")
    ap.add_argument("--uninstall", action="store_true", help="disable and remove the timer")
    args = ap.parse_args()
    if args.uninstall:
        return uninstall()
    if args.status:
        return status()
    return install()


if __name__ == "__main__":
    sys.exit(main())

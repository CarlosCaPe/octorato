#!/usr/bin/env python3
"""Run the CURRENT isolation fixtures through the CURRENT gate scripts with
ONLY the liveness reader swapped for another commit's, and print both counts.

WHY THE SWAP IS THE MODULE AND NOT THE COMMIT. Checking out an older commit
whole and running today's fixtures against it measures nothing: the older
`build_sandbox` does not know today's `_setup` keys, so it silently no-ops the
attack and every fixture reads "blocked" for the wrong reason. QA cycle 7 caught
a cross-version number produced exactly that way and could not reproduce it. So
this holds the fixtures, the sandbox builder and both gate scripts fixed at the
working tree and replaces one file, `kernel_proc.py`, with the version from
`<ref>` - plus `forge_journal`, which is fixture machinery rather than the thing
under test and does not exist in older versions.

    python3 scripts/tests/crossversion_isolation.py [ref]      # default HEAD

A fixture that BLOCKS under the working tree and ALLOWS under `ref` is a
fixture that measures this change. One that blocks under both measures
something that was already true, which is worth knowing and is not evidence for
the change.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATES = ("g__pretool-write__tree-owner.py", "g__pretool-bash__tree-owner.py")
COUNTS = re.compile(r"(\d+) block \+ (\d+) allow")


def _git(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(("git",) + args, cwd=ROOT, capture_output=True,
                          text=True, env=env).stdout


def _selftest(tree):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = {}
    for gate in GATES:
        cp = subprocess.run([sys.executable, os.path.join(tree, "scripts", gate),
                             "--selftest"], capture_output=True, text=True,
                            env=env, timeout=1800)
        m = COUNTS.search(cp.stdout + cp.stderr)
        out[gate] = (cp.returncode, m.groups() if m else None,
                     (cp.stdout + cp.stderr).strip().splitlines()[-1:])
    return out


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    base = tempfile.mkdtemp(prefix="crossver-")
    tree = os.path.join(base, "wt")
    shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    print("== working tree")
    for gate, res in _selftest(tree).items():
        print("  %-38s rc=%d %s" % (gate, res[0], res[1]))

    old = _git("show", "%s:scripts/kernel_proc.py" % ref)
    if not old:
        sys.exit("could not read scripts/kernel_proc.py at %s" % ref)
    cur = open(os.path.join(ROOT, "scripts", "kernel_proc.py"), encoding="utf-8").read()
    # Carry the FIXTURE MACHINERY across, all of it. These helpers build the
    # attacks; they are not the thing under test, and an older module that
    # lacks one raises AttributeError inside `build_sandbox`, which reads as
    # "the fixture blocked" and is the same wrong-reason pass this harness
    # exists to catch. The span runs from the first helper to `selftest_flow`,
    # so adding another one needs no edit here.
    helpers = ("def forge_exit_line(", "def forge_journal(")
    if any(h not in old for h in helpers):
        i = min(cur.index(h) for h in helpers)
        j = cur.index("def selftest_flow(")
        for h in helpers:                       # drop any half-present copy
            if h in old:
                sys.exit("refusing to splice: %s already exists at that ref" % h)
        old = old.replace("def selftest_flow(", cur[i:j] + "def selftest_flow(", 1)
    with open(os.path.join(tree, "scripts", "kernel_proc.py"), "w",
              encoding="utf-8") as fh:
        fh.write(old)
    print("== reader from %s (fixtures, sandbox and gates unchanged)" % ref)
    for gate, res in _selftest(tree).items():
        print("  %-38s rc=%d %s" % (gate, res[0], res[1]))
        for line in res[2]:
            print("      %s" % line[:200])
    shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()

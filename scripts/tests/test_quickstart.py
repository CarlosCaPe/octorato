#!/usr/bin/env python3
"""quickstart.py wires the brain in one command (v10, AC-14 and AC-15).

Each test builds a throwaway HOME holding a minimal brain checkout at
`$HOME/.claude` (its own git repo, the real quickstart, merge-hooks, spec_lint,
the spec templates, the push guard and .gitignore), then runs quickstart there
with HOME pointed at it. Nothing under the real HOME is read or written. The
connectome, runners and doctor scripts are left out of the fake brain on
purpose: quickstart skips an absent script, and those three are proven by the
fresh-clone CI job (.github/workflows/fresh-clone.yml), not here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain_doctor  # noqa: E402
import quickstart  # noqa: E402

COPY = [
    "scripts/quickstart.py",
    "scripts/merge-hooks.py",
    "scripts/spec_lint.py",
    "templates/spec/feature.md.template",
    "templates/spec/plan.md.template",
    ".githooks/pre-push",
    ".gitignore",
    "CLAUDE.md",
]


def _clean_env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "OCTO_", "CLAUDE"))}
    env["HOME"] = str(home)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def make_brain(home: Path) -> Path:
    brain = home / ".claude"
    for rel in COPY:
        dst = brain / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    # A hooks.json whose commands point at scripts that exist in the fake brain,
    # because merge-hooks.py drops an entry whose script is missing.
    cmd = "python3 ~/.claude/scripts/merge-hooks.py --selftest"
    (brain / "hooks.json").write_text(json.dumps({
        "$schema": "x",
        "SessionStart": [{"hooks": [{"type": "command", "command": cmd}]}],
        "Stop": [{"hooks": [{"type": "command", "command": cmd}]}],
    }), encoding="utf-8")
    env = _clean_env(home)
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@example.invalid", "-c", "user.name=t",
                  "commit", "-q", "-m", "fake brain"]):
        subprocess.run(["git", "-C", str(brain), *args], check=True, env=env,
                       capture_output=True)
    return brain


def run_quickstart(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(home / ".claude" / "scripts" / "quickstart.py"), *args],
                          env=_clean_env(home), capture_output=True, text=True, timeout=120,
                          stdin=subprocess.DEVNULL)


def git_out(home: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(home / ".claude"), *args], env=_clean_env(home),
                          capture_output=True, text=True).stdout.strip()


class QuickstartWiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.brain = make_brain(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def _specs(self, root: Path):
        d = root / "docs" / "specs"
        return sorted(d.glob("*-first-spec")) if d.is_dir() else []

    def test_one_command_wires_hooks_hookspath_and_first_spec(self):
        self.assertEqual(git_out(self.home, "config", "--get", "core.hooksPath"), "")
        self.assertFalse((self.brain / "settings.json").exists())
        cp = run_quickstart(self.home)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        hooks = json.loads((self.brain / "settings.json").read_text())["hooks"]
        self.assertEqual(sorted(hooks), ["SessionStart", "Stop"])
        self.assertEqual(git_out(self.home, "config", "--get", "core.hooksPath"), ".githooks")
        specs = self._specs(self.brain / "company")
        self.assertEqual(len(specs), 1, cp.stdout)
        lint = subprocess.run([sys.executable, str(ROOT / "scripts" / "spec_lint.py"), str(specs[0])],
                              capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        self.assertIn("Spec-Format:** ears-1", (specs[0] / "feature.md").read_text())
        # The example and settings.json are gitignored: the public brain stays clean.
        self.assertEqual(git_out(self.home, "status", "--porcelain"), "")

    def test_rerun_is_idempotent(self):
        self.assertEqual(run_quickstart(self.home).returncode, 0)
        cp = run_quickstart(self.home)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertEqual(len(self._specs(self.brain / "company")), 1)

    def test_project_flag_writes_the_spec_into_the_project(self):
        project = Path(self.tmp.name) / "my-project"
        cp = run_quickstart(self.home, "--project", str(project))
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertEqual(len(self._specs(project)), 1)
        self.assertEqual(self._specs(self.brain / "company"), [])

    def test_a_tracked_path_inside_the_brain_is_refused(self):
        cp = run_quickstart(self.home, "--project", str(self.brain))
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("git does not ignore it", cp.stdout)
        self.assertEqual(self._specs(self.brain), [])
        self.assertEqual(git_out(self.home, "status", "--porcelain"), "")

    def test_a_checkout_outside_home_claude_is_not_wired(self):
        other = Path(self.tmp.name) / "elsewhere"
        shutil.copytree(self.brain, other)
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            ok, detail = quickstart.wire_claude_hooks(other)
        self.assertFalse(ok)
        self.assertIn("clone the brain to ~/.claude", detail)

    def test_missing_pre_push_fails_the_hooks_path_step(self):
        (self.brain / ".githooks" / "pre-push").unlink()
        with mock.patch.dict(os.environ, _clean_env(self.home), clear=True):
            ok, detail = quickstart.set_git_hooks_path(self.brain)
        self.assertFalse(ok)
        self.assertIn("pre-push is missing", detail)


class DoctorFastProfileTest(unittest.TestCase):
    def test_fast_skips_exactly_the_slow_checks(self):
        ran = []

        def fake(key):
            def fn(fix):
                ran.append(key)
                return brain_doctor.Result(key, brain_doctor.PASS, "ok")
            return fn
        keys = [k for k, _ in brain_doctor.CHECKS]
        with mock.patch.object(brain_doctor, "CHECKS", [(k, fake(k)) for k in keys]):
            brain_doctor.run_all(False, fast=True)
            fast = list(ran)
            ran.clear()
            brain_doctor.run_all(False)
        self.assertEqual(ran, keys, "the full profile must still run every check")
        self.assertEqual(set(keys) - set(fast), set(brain_doctor.SLOW_CHECKS))
        self.assertIn("gate-liveness", brain_doctor.SLOW_CHECKS)

    def test_every_slow_key_names_a_real_check(self):
        keys = {k for k, _ in brain_doctor.CHECKS}
        self.assertEqual(set(brain_doctor.SLOW_CHECKS) - keys, set())

    def test_fast_refuses_the_pre_push_modes(self):
        for mode in ("--registry", "--gate-receipt"):
            cp = subprocess.run([sys.executable, str(ROOT / "scripts" / "brain_doctor.py"), "--fast", mode],
                                capture_output=True, text=True, timeout=60)
            self.assertEqual(cp.returncode, 2, mode)


if __name__ == "__main__":
    unittest.main()

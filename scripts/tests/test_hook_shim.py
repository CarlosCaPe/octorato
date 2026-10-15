#!/usr/bin/env python3
"""g__shim__hook.py: the Hook_Shim of v11 AC-05.

The selftest drives every fixture of registry/fixtures/ARCHITECTURE.hook-shim
through real gates. These cases pin what the selftest does not show by name:
the registry reader agrees with a YAML load of registry/runtimes.yaml, a
repeated entry reads as unknown, and the Gemini MCP name is rebuilt only from
an mcp_context whose parts reproduce it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
_spec = importlib.util.spec_from_file_location("hook_shim", SCRIPTS / "g__shim__hook.py")
shim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shim)


class RegistryStatus(unittest.TestCase):
    def test_reader_agrees_with_yaml(self):
        import yaml
        data = yaml.safe_load((ROOT / "registry" / "runtimes.yaml").read_text(encoding="utf-8"))
        for hid, entry in data["runtimes"].items():
            self.assertEqual(shim.registry_status(hid), entry["status"], hid)

    def test_repeated_entry_is_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "runtimes.yaml"
            p.write_text("runtimes:\n  gemini-cli:\n    status: supported\n"
                         "  gemini-cli:\n    status: supported\n", encoding="utf-8")
            self.assertIsNone(shim.registry_status("gemini-cli", str(p)))

    def test_missing_file_is_unknown(self):
        self.assertIsNone(shim.registry_status("gemini-cli", "/nonexistent/runtimes.yaml"))


class Translation(unittest.TestCase):
    def _gem(self, **kw):
        p = {"hook_event_name": "BeforeTool", "cwd": "/w", "session_id": "s",
             "tool_name": "mcp_gmail_send_email", "tool_input": {"to": ["a@b.c"]}}
        p.update(kw)
        return json.dumps(p)

    def test_gemini_mcp_rebuilt_from_context(self):
        calls = shim.translate("gemini-cli", self._gem(
            mcp_context={"server_name": "gmail", "tool_name": "send_email"}))
        self.assertEqual(calls[0]["tool_name"], "mcp__gmail__send_email")

    def test_gemini_mcp_without_context_raises(self):
        with self.assertRaises(shim.TranslationError):
            shim.translate("gemini-cli", self._gem())

    def test_codex_patch_every_path(self):
        patch = ("*** Begin Patch\n*** Add File: a.txt\n+x\n*** Update File: /abs/b.py\n"
                 "*** Move to: c.py\n@@\n-o\n+n\n*** Delete File: d.txt\n*** End Patch\n")
        calls = shim.translate("codex-cli", json.dumps({
            "hook_event_name": "PreToolUse", "cwd": "/w", "tool_name": "apply_patch",
            "tool_input": {"command": patch}}))
        paths = [c["tool_input"]["file_path"] for c in calls]
        self.assertEqual(paths, [os.path.normpath(os.path.join("/w", "a.txt")), os.path.normpath("/abs/b.py"),
                                 os.path.normpath(os.path.join("/w", "c.py")),
                                 os.path.normpath(os.path.join("/w", "d.txt"))])


class Selftest(unittest.TestCase):
    def test_selftest_passes(self):
        cp = subprocess.run([sys.executable, str(SCRIPTS / "g__shim__hook.py"), "--selftest"],
                            capture_output=True, text=True, timeout=600)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        self.assertIn("selftest PASS", cp.stdout)


if __name__ == "__main__":
    unittest.main()

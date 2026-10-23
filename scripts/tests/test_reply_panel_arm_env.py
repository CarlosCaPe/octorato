#!/usr/bin/env python3
"""brain_doctor's reply-panel-arm-env check (FLOW.panel-before-reply, AC-16).

An arm's `.claude/settings*.json` that sets OCTO_REPLY_PANEL in its env block
switches the reply panel off for later sessions there (residual R-10). The
doctor warns and names the file, for the arm paths in arms-paths.json only.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain_doctor  # noqa: E402


def _settings(home: Path, arm: str, env: dict, name: str = "settings.local.json") -> Path:
    d = home / arm / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps({"env": env}), encoding="utf-8")
    return p


def run(home: Path, arms) -> brain_doctor.Result:
    arms_file = home / "arms-paths.json"
    if arms is not None:
        arms_file.write_text(json.dumps(arms), encoding="utf-8")
    with mock.patch.object(brain_doctor, "HOME", home):
        return brain_doctor.check_reply_panel_arm_env(False, arms_file)


class ReplyPanelArmEnvTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.listed = _settings(self.home, "arm-a", {"OCTO_REPLY_PANEL": "off"})
        _settings(self.home, "arm-b", {"OTHER": "1"}, "settings.json")
        self.unlisted = _settings(self.home, "not-an-arm", {"OCTO_REPLY_PANEL": "off"})

    def tearDown(self):
        self._tmp.cleanup()

    def test_listed_arm_that_sets_the_switch_is_named(self):
        r = run(self.home, {"a": "arm-a", "b": ["missing", "arm-b"]})
        self.assertEqual(r.status, brain_doctor.WARN)
        self.assertIn(str(self.listed), r.message)

    def test_unlisted_directory_is_not_scanned(self):
        r = run(self.home, {"a": "arm-a"})
        self.assertNotIn("not-an-arm", r.message)
        r = run(self.home, {"b": "arm-b"})
        self.assertEqual(r.status, brain_doctor.PASS, r.message)
        self.assertNotIn(str(self.unlisted), r.message)

    def test_no_arms_file_scans_nothing(self):
        r = run(self.home, None)
        self.assertEqual(r.status, brain_doctor.PASS)


if __name__ == "__main__":
    unittest.main()

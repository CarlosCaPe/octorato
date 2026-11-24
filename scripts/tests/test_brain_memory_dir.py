#!/usr/bin/env python3
"""brain_doctor._brain_memory_dir honours the memory_sync config.

The canonical brain memory store is whatever `brain_memory.path` in
company/config/memory.json names. When the doctor derived the dir from the home
path instead, it read a near-empty folder and reported every reflex-triage
decision as naming a memory that no longer exists.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain_doctor  # noqa: E402


def _home_slug_dir(d: Path) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path.home()))
    return d / "projects" / slug / "memory"


class BrainMemoryDirTest(unittest.TestCase):
    def _with_config(self, d: Path, payload) -> None:
        cfg = d / "company" / "config"
        cfg.mkdir(parents=True)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        (cfg / "memory.json").write_text(text, encoding="utf-8")

    def test_configured_relative_path_wins(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            self._with_config(d, {"brain_memory": {"path": "projects/store-x/memory", "remote": "r"}})
            with mock.patch.object(brain_doctor, "CLAUDE_DIR", d):
                self.assertEqual(brain_doctor._brain_memory_dir(), d / "projects" / "store-x" / "memory")

    def test_configured_absolute_path_is_kept(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            target = d / "elsewhere" / "memory"
            self._with_config(d, {"brain_memory": {"path": str(target)}})
            with mock.patch.object(brain_doctor, "CLAUDE_DIR", d):
                self.assertEqual(brain_doctor._brain_memory_dir(), target)

    def test_no_config_falls_back_to_home_slug(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            with mock.patch.object(brain_doctor, "CLAUDE_DIR", d):
                self.assertEqual(brain_doctor._brain_memory_dir(), _home_slug_dir(d))

    def test_bad_or_empty_config_falls_back(self):
        for payload in ("{not json", {"brain_memory": {"path": "  "}}, {"brain_memory": None}, []):
            with tempfile.TemporaryDirectory() as t:
                d = Path(t)
                self._with_config(d, payload)
                with mock.patch.object(brain_doctor, "CLAUDE_DIR", d):
                    self.assertEqual(brain_doctor._brain_memory_dir(), _home_slug_dir(d), payload)

    def test_reflex_triage_reads_configured_store(self):
        """The regression: a decision whose memory lives in the configured
        store is not reported as dead."""
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            self._with_config(d, {"brain_memory": {"path": "projects/store-x/memory"}})
            mem = d / "projects" / "store-x" / "memory"
            mem.mkdir(parents=True)
            (mem / "feedback_kept.md").write_text("a second time this happened\n", encoding="utf-8")
            reg = d / "registry"
            reg.mkdir()
            (reg / "reflex-triage.yaml").write_text(
                "decisions:\n  - slug: feedback_kept\n    decision: demote\n    reason: x\n    decided: 2026-01-01\n",
                encoding="utf-8")
            with mock.patch.object(brain_doctor, "CLAUDE_DIR", d):
                r = brain_doctor.check_reflex_triage(False)
            self.assertEqual(r.status, brain_doctor.PASS, r)


if __name__ == "__main__":
    unittest.main()

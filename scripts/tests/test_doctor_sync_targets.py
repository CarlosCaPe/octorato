#!/usr/bin/env python3
"""brain_doctor sync-targets over the v11 instruction files (AC-07).

The check compares each arm's mirrors with its .claude/CLAUDE.md: the two base
mirrors plus the instruction file of every `supported` harness. It WARNs on a
mirror that is a symlink (sync refuses to write through it) and on an
instruction file of a harness that is not supported (a stale mirror sync no
longer updates). Temp arm, temp arms-paths.json and temp registry only.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain_doctor  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts" / "tests"))
from test_ai_sync_instruction_files import SOURCE, _can_symlink, registry_text  # noqa: E402

PASS, WARN = brain_doctor.PASS, brain_doctor.WARN


class SyncTargets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.arm = base / "arm"
        (self.arm / ".claude").mkdir(parents=True)
        (self.arm / ".claude" / "CLAUDE.md").write_bytes(SOURCE)
        (self.arm / ".github").mkdir()
        for rel in (".github/copilot-instructions.md", ".cursorrules"):
            (self.arm / rel).write_bytes(SOURCE)
        self.arms = base / "arms-paths.json"
        self.arms.write_text(json.dumps({"arm": str(self.arm)}), encoding="utf-8")
        self.registry = base / "runtimes.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, text: str):
        self.registry.write_text(text, encoding="utf-8")
        return brain_doctor.check_sync_targets(False, self.arms, self.registry)

    def test_gap_registry_base_mirrors_in_sync_passes(self):
        res = self.run_check(registry_text())
        self.assertEqual([r.status for r in res], [PASS], [r.message for r in res])

    def test_supported_harness_file_missing_warns(self):
        res = self.run_check(registry_text(codex="supported"))
        self.assertTrue(any(r.status == WARN and "AGENTS.md missing" in r.message for r in res))

    def test_supported_harness_file_in_sync_passes(self):
        (self.arm / "AGENTS.md").write_bytes(SOURCE)
        res = self.run_check(registry_text(codex="supported"))
        self.assertEqual([r.status for r in res], [PASS], [r.message for r in res])

    def test_stale_mirror_of_gap_harness_warns(self):
        (self.arm / "GEMINI.md").write_bytes(SOURCE)
        res = self.run_check(registry_text(gemini="gap"))
        msgs = [r.message for r in res if r.status == WARN]
        self.assertTrue(any("GEMINI.md is a stale mirror" in m for m in msgs), msgs)

    @unittest.skipUnless(_can_symlink(), "this OS user cannot create symlinks")
    def test_symlinked_mirror_warns(self):
        (self.arm / ".cursorrules").unlink()
        os.symlink(self.arm / ".claude" / "CLAUDE.md", self.arm / ".cursorrules")
        res = self.run_check(registry_text())
        msgs = [r.message for r in res if r.status == WARN]
        self.assertTrue(any(".cursorrules not synced, .cursorrules is a symlink" in m for m in msgs), msgs)


if __name__ == "__main__":
    unittest.main()

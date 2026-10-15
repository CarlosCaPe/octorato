#!/usr/bin/env python3
"""ai_sync sync writes AGENTS.md / GEMINI.md per arm only for `supported` harnesses.

v11 spec 202610141000, AC-07, task T09. The Instruction_Sync reads
registry/runtimes.yaml and adds, beside `.github/copilot-instructions.md` and
`.cursorrules`, the `instruction_file` of every harness whose status is
`supported`, from the arm's own `.claude/CLAUDE.md`. A second run with no
source change leaves every file byte-identical and unwritten (same mtime).

Every case runs on a temp arm and a temp registry; load_arms is stubbed, so no
arms-paths.json and no real arm is read or written.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_sync  # noqa: E402

SOURCE = "# Arm instructions\n\nAcentos: ñ, é, · and a dash.\n".encode("utf-8")


def registry_text(gemini: str = "gap", codex: str = "gap", extra: str = "") -> str:
    return f"""schema: 1
runtimes:
  claude-code:
    name: Claude Code
    status: supported
    instruction_file: ~/.claude/CLAUDE.md
  cursor:
    name: Cursor
    status: supported
    instruction_file: .cursorrules
  gemini-cli:
    name: Gemini CLI
    status: {gemini}
    instruction_file: GEMINI.md
  codex-cli:
    name: Codex CLI
    status: {codex}
    instruction_file: AGENTS.md
{extra}"""


class InstructionSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.arm = base / "arm"
        (self.arm / ".claude").mkdir(parents=True)
        (self.arm / ".claude" / "CLAUDE.md").write_bytes(SOURCE)
        self.registry = base / "runtimes.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def _sync(self, text: str | None):
        if text is None:
            if self.registry.exists():
                self.registry.unlink()
        else:
            self.registry.write_text(text, encoding="utf-8")
        out = io.StringIO()
        with mock.patch.object(ai_sync, "RUNTIMES", self.registry), \
                mock.patch.object(ai_sync, "load_arms", return_value={"arm": self.arm}), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = ai_sync.sync(None)
        self.assertEqual(rc, 0)
        return out.getvalue()

    def _present(self) -> set:
        return {rel for rel in (".github/copilot-instructions.md", ".cursorrules",
                                "AGENTS.md", "GEMINI.md") if (self.arm / rel).exists()}

    def test_gap_harnesses_get_no_file(self):
        self._sync(registry_text())
        self.assertEqual(self._present(), {".github/copilot-instructions.md", ".cursorrules"})

    def test_supported_codex_gets_agents_md_only(self):
        self._sync(registry_text(codex="supported"))
        self.assertEqual(self._present(),
                         {".github/copilot-instructions.md", ".cursorrules", "AGENTS.md"})
        self.assertEqual((self.arm / "AGENTS.md").read_bytes(), SOURCE)

    def test_supported_gemini_gets_gemini_md_only(self):
        self._sync(registry_text(gemini="supported"))
        self.assertIn("GEMINI.md", self._present())
        self.assertNotIn("AGENTS.md", self._present())
        self.assertEqual((self.arm / "GEMINI.md").read_bytes(), SOURCE)

    def test_second_run_is_a_noop(self):
        text = registry_text(gemini="supported", codex="supported")
        self._sync(text)
        files = sorted(self._present())
        self.assertEqual(len(files), 4)
        old = 1_000_000_000_000_000_000  # a fixed past mtime, in ns
        for rel in files:
            os.utime(self.arm / rel, ns=(old, old))
        before = {rel: (self.arm / rel).read_bytes() for rel in files}
        out = self._sync(text)
        self.assertIn("0 rewritten", out)
        for rel in files:
            self.assertEqual((self.arm / rel).read_bytes(), before[rel], rel)
            self.assertEqual((self.arm / rel).stat().st_mtime_ns, old, f"{rel} was rewritten")

    def test_source_change_rewrites_every_mirror(self):
        text = registry_text(codex="supported")
        self._sync(text)
        (self.arm / ".claude" / "CLAUDE.md").write_bytes(SOURCE + b"one more line\n")
        out = self._sync(text)
        self.assertIn("3 rewritten", out)
        self.assertEqual((self.arm / "AGENTS.md").read_bytes(), SOURCE + b"one more line\n")

    def test_unsafe_or_home_paths_are_never_written(self):
        extra = """  evil-up:
    name: Evil up
    status: supported
    instruction_file: ../ESCAPE.md
  evil-abs:
    name: Evil abs
    status: supported
    instruction_file: /tmp/ABS.md
"""
        files = ai_sync.harness_instruction_files
        self.registry.write_text(registry_text(extra=extra), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(files(self.registry), [])
        self._sync(registry_text(extra=extra))
        self.assertFalse((self.arm.parent / "ESCAPE.md").exists())

    def test_missing_registry_writes_base_mirrors_only(self):
        out = self._sync(None)
        self.assertIn("unreadable", out)
        self.assertEqual(self._present(), {".github/copilot-instructions.md", ".cursorrules"})

    def test_tracked_registry_matches_its_supported_entries(self):
        import yaml
        data = yaml.safe_load((ROOT / "registry" / "runtimes.yaml").read_text(encoding="utf-8"))
        expect = sorted(e["instruction_file"] for e in data["runtimes"].values()
                        if e.get("status") == "supported"
                        and e["instruction_file"] in ("AGENTS.md", "GEMINI.md"))
        with redirect_stdout(io.StringIO()):
            got = sorted(ai_sync.harness_instruction_files(ROOT / "registry" / "runtimes.yaml"))
        self.assertEqual(got, expect)


if __name__ == "__main__":
    unittest.main()

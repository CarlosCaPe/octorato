#!/usr/bin/env python3
"""ai_sync sync writes AGENTS.md / GEMINI.md per arm only for `supported` harnesses.

v11 spec 202610141000, AC-07, task T09. The Instruction_Sync reads
registry/runtimes.yaml and adds, beside `.github/copilot-instructions.md` and
`.cursorrules`, the `instruction_file` of every harness whose status is
`supported`, from the arm's own `.claude/CLAUDE.md`. A second run with no
source change leaves every file byte-identical and unwritten (same mtime).

Security (every mirror, the two base ones included): a mirror that is a
symlink, or sits under a symlinked directory, is never written, even when the
link points inside the arm; only a plain file name is accepted from the
registry; and an instruction file of a harness that is not `supported` is left
in place with a stale-mirror warning, never deleted.

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


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as d:
        try:
            os.symlink(os.path.join(d, "t"), os.path.join(d, "l"))
            return True
        except (OSError, NotImplementedError):
            return False


ALL_MIRRORS = (".github/copilot-instructions.md", ".cursorrules", "AGENTS.md", "GEMINI.md")
BOTH = registry_text(gemini="supported", codex="supported")


@unittest.skipUnless(_can_symlink(), "this OS user cannot create symlinks")
class MirrorNeverFollowsALink(unittest.TestCase):
    """QA reproduction: AGENTS.md in the arm linked to a file outside it, codex
    flipped to supported, and sync overwrote the outside file. Each case turns
    red when mirror_refusal is bypassed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.arm = base / "arm"
        (self.arm / ".claude").mkdir(parents=True)
        (self.arm / ".claude" / "CLAUDE.md").write_bytes(SOURCE)
        self.outside = base / "outside"
        self.outside.mkdir()
        self.registry = base / "runtimes.yaml"
        self.registry.write_text(BOTH, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _sync(self) -> str:
        out = io.StringIO()
        with mock.patch.object(ai_sync, "RUNTIMES", self.registry), \
                mock.patch.object(ai_sync, "load_arms", return_value={"arm": self.arm}), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(ai_sync.sync(None), 0)
        return out.getvalue()

    def test_symlinked_mirror_file_outside_the_arm_is_not_written(self):
        for rel in ALL_MIRRORS:
            with self.subTest(rel=rel):
                victim = self.outside / f"victim-{rel.replace('/', '_')}"
                victim.write_bytes(b"precious")
                link = self.arm / rel
                link.parent.mkdir(parents=True, exist_ok=True)
                if os.path.lexists(link):
                    link.unlink()
                os.symlink(victim, link)
                out = self._sync()
                self.assertEqual(victim.read_bytes(), b"precious")
                self.assertTrue(link.is_symlink(), "the link itself must be left alone")
                self.assertIn(f"{rel} NOT written", out)
                link.unlink()

    def test_symlinked_github_dir_is_not_written_through(self):
        os.symlink(self.outside, self.arm / ".github", target_is_directory=True)
        out = self._sync()
        self.assertFalse((self.outside / "copilot-instructions.md").exists())
        self.assertIn(".github is a symlink", out)
        for rel in (".cursorrules", "AGENTS.md", "GEMINI.md"):
            self.assertEqual((self.arm / rel).read_bytes(), SOURCE, rel)

    def test_symlink_pointing_inside_the_arm_is_still_refused(self):
        for rel in ALL_MIRRORS:
            with self.subTest(rel=rel):
                inside = self.arm / "notes.txt"
                inside.write_bytes(b"arm notes")
                link = self.arm / rel
                link.parent.mkdir(parents=True, exist_ok=True)
                if os.path.lexists(link):
                    link.unlink()
                os.symlink(inside, link)
                self._sync()
                self.assertEqual(inside.read_bytes(), b"arm notes")
                self.assertTrue(link.is_symlink())
                link.unlink()

    def _assert_no_mirror(self, out: str, why: str):
        for rel in ALL_MIRRORS:
            self.assertFalse(os.path.lexists(self.arm / rel), rel)
        self.assertIn("SKIPPED, source not read", out)
        self.assertIn(why, out)

    def test_symlinked_source_file_is_not_read(self):
        secret = self.outside / "id_rsa"
        secret.write_bytes(b"PRIVATE KEY")
        src = self.arm / ".claude" / "CLAUDE.md"
        src.unlink()
        os.symlink(secret, src)
        self._assert_no_mirror(self._sync(), ".claude/CLAUDE.md is a symlink")

    def test_symlinked_claude_dir_is_not_read(self):
        secret_dir = self.outside / "brain"
        secret_dir.mkdir()
        (secret_dir / "CLAUDE.md").write_bytes(b"brain secret")
        real = self.arm / ".claude"
        (real / "CLAUDE.md").unlink()
        real.rmdir()
        os.symlink(secret_dir, real, target_is_directory=True)
        self._assert_no_mirror(self._sync(), ".claude is a symlink")

    def test_hardlinked_source_is_not_read(self):
        secret = self.outside / "token"
        secret.write_bytes(("gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8").encode())
        src = self.arm / ".claude" / "CLAUDE.md"
        src.unlink()
        try:
            os.link(secret, src)
        except OSError as e:
            self.skipTest(f"hard links unavailable: {e}")
        self._assert_no_mirror(self._sync(), "hard links")

    def test_regular_files_are_replaced_in_place_not_followed(self):
        self._sync()
        for rel in ALL_MIRRORS:
            p = self.arm / rel
            self.assertFalse(p.is_symlink())
            self.assertEqual(p.read_bytes(), SOURCE, rel)
        leftovers = [q.name for q in self.arm.rglob(".*.tmp")]
        self.assertEqual(leftovers, [])


class RegistryValuesAreFileNames(unittest.TestCase):
    def test_only_a_plain_file_name_is_accepted(self):
        bad = [".git/config", "./AGENTS.md", ".", "..", "a/b.md", "a\\b.md", ".hidden",
               "~/x.md", "/abs.md", "C:x.md", "", " AGENTS.md"]
        for rel in bad:
            self.assertFalse(ai_sync.plain_filename(rel), rel)
        for rel in ("AGENTS.md", "GEMINI.md", "X_1-a.md"):
            self.assertTrue(ai_sync.plain_filename(rel), rel)

    def test_registry_with_bad_names_writes_nothing_extra(self):
        with tempfile.TemporaryDirectory() as d:
            reg = Path(d) / "runtimes.yaml"
            extra = "".join(f"""  bad-{i}:
    name: Bad {i}
    status: supported
    instruction_file: '{v}'
""" for i, v in enumerate((".git/config", "./AGENTS.md", "..", ".")))
            reg.write_text(registry_text(extra=extra), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(ai_sync.harness_instruction_files(reg), [])
            self.assertIn("not a plain file name", out.getvalue())


class StaleMirror(InstructionSync):
    """A harness flipped back to gap: its file stays (never deleted in an arm)
    and sync warns that it no longer tracks CLAUDE.md."""

    def test_flip_to_gap_leaves_the_file_and_warns(self):
        self._sync(registry_text(codex="supported"))
        self.assertEqual((self.arm / "AGENTS.md").read_bytes(), SOURCE)
        (self.arm / ".claude" / "CLAUDE.md").write_bytes(SOURCE + b"newer\n")
        out = self._sync(registry_text(codex="gap"))
        self.assertEqual((self.arm / "AGENTS.md").read_bytes(), SOURCE, "never rewritten or deleted")
        self.assertIn("AGENTS.md is a stale mirror", out)
        self.assertNotIn("GEMINI.md is a stale mirror", out)


if __name__ == "__main__":
    unittest.main()

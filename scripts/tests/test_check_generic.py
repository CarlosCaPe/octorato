#!/usr/bin/env python3
"""Tests for scripts/check-generic.py message scanning (issue #15).

check-generic.py is security-critical: it blocks commits whose message or
staged content leaks a token from the private blocklist. These tests exercise
the message-scan path end-to-end via subprocess and assert exit codes.

The script resolves its blocklist from ``$CLAUDE_DIR/company/brain-blocklist.txt``
(``CLAUDE_DIR`` defaults to ~/.claude). Every test points ``CLAUDE_DIR`` at a
throwaway temp dir with a *sample* blocklist, so the real, private
``company/brain-blocklist.txt`` is never read or touched.

Stdlib only, no network/services:

    python3 -m unittest scripts.tests.test_check_generic
    python3 scripts/tests/test_check_generic.py
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "check-generic.py"

# Exit codes per check-generic.py docstring: 0 clean, 1 blocked, 2 config error.
EXIT_CLEAN = 0
EXIT_BLOCKED = 1

SAMPLE_TOKENS = ["AcmeCorp", "secret-vendor-x", "Jane Coworker"]


class CheckGenericMessageScanTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.claude_dir = Path(self._tmp.name)
        (self.claude_dir / "company").mkdir(parents=True)
        self.blocklist = self.claude_dir / "company" / "brain-blocklist.txt"
        self.blocklist.write_text(
            "# sample blocklist — test fixture only\n" + "\n".join(SAMPLE_TOKENS) + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, message: str, claude_dir: Path | None = None) -> int:
        env = dict(os.environ)
        env["CLAUDE_DIR"] = str(claude_dir if claude_dir is not None else self.claude_dir)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--message", message, "--quiet"],
            env=env, capture_output=True, text=True,
        )
        return proc.returncode

    # --- pass case: clean message ---------------------------------------
    def test_clean_message_passes(self) -> None:
        self.assertEqual(self._run("feat(brain): add a generic skill"), EXIT_CLEAN)

    # --- fail case: message hits the blocklist --------------------------
    def test_blocklisted_token_blocks(self) -> None:
        self.assertEqual(self._run("feat: integrate AcmeCorp connector"), EXIT_BLOCKED)

    def test_match_is_case_insensitive(self) -> None:
        self.assertEqual(self._run("wire up acmecorp export"), EXIT_BLOCKED)

    def test_multiword_token_blocks(self) -> None:
        self.assertEqual(self._run("thanks to Jane Coworker for the fix"), EXIT_BLOCKED)

    # --- word boundary: substring of a larger word must NOT match -------
    def test_substring_does_not_match(self) -> None:
        # 'AcmeCorporation' contains 'AcmeCorp' but \b…\b should not fire.
        self.assertEqual(self._run("AcmeCorporationXyz is unrelated"), EXIT_CLEAN)

    # --- config edge cases: never block when not configured -------------
    def test_missing_blocklist_soft_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            # No company/brain-blocklist.txt → soft-fail, allow commit.
            self.assertEqual(
                self._run("feat: integrate AcmeCorp connector", claude_dir=Path(empty)),
                EXIT_CLEAN,
            )

    def test_empty_blocklist_passes(self) -> None:
        self.blocklist.write_text("# only comments, no tokens\n", encoding="utf-8")
        self.assertEqual(self._run("feat: integrate AcmeCorp connector"), EXIT_CLEAN)


if __name__ == "__main__":
    unittest.main(verbosity=2)

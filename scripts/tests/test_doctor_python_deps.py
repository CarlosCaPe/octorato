#!/usr/bin/env python3
"""brain_doctor's python-deps check reads requirements.txt as DISTRIBUTIONS.

It used to probe `import <name>`, so a distribution imported under another name
(`pyyaml` is `yaml`) read as missing on a machine where it was installed, and the
FAIL blocked every push from the live brain.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain_doctor  # noqa: E402


def check(requirements: str):
    with tempfile.TemporaryDirectory() as d:
        Path(d, "requirements.txt").write_text(requirements, encoding="utf-8")
        with mock.patch.object(brain_doctor, "CLAUDE_DIR", Path(d)):
            return brain_doctor.check_python_deps(False)


class PythonDepsTest(unittest.TestCase):
    def test_a_distribution_imported_under_another_name_is_found(self):
        # PyYAML is in requirements.txt, so every place this suite runs has it
        # (pre-push on a brain, the CI job after `pip install -r`).
        self.assertEqual(check("pyyaml>=6.0\n").status, brain_doctor.PASS)

    def test_a_missing_distribution_is_still_reported(self):
        r = check("pyyaml>=6.0\nno-such-distribution-octorato-test>=1\n")
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("no-such-distribution-octorato-test", r.message)
        self.assertNotIn("pyyaml", r.message)

    def test_the_repository_requirements_resolve_here(self):
        # The suite runs only where requirements.txt was installed (pre-push on a
        # brain, the CI job after `pip install -r`), so every entry must resolve.
        r = check((ROOT / "requirements.txt").read_text(encoding="utf-8"))
        self.assertEqual(r.status, brain_doctor.PASS, r.message)

    def test_installed_but_unimportable_is_reported(self):
        # Metadata alone is not enough: a distribution whose own dependency is
        # gone keeps its metadata while `import` fails. Build one on a path the
        # probe's interpreter sees, and require the check to call it missing.
        with tempfile.TemporaryDirectory() as site:
            info = Path(site, "octo_broken_dist-1.0.dist-info")
            info.mkdir()
            (info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: octo-broken-dist\nVersion: 1.0\n")
            (info / "top_level.txt").write_text("octo_broken_mod\n")
            Path(site, "octo_broken_mod.py").write_text(
                "raise ImportError('a dependency of this package is missing')\n")
            env = {"PYTHONPATH": site + os.pathsep + os.environ.get("PYTHONPATH", "")}
            with mock.patch.dict(os.environ, env):
                r = check("octo-broken-dist>=1\n")
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("octo-broken-dist", r.message)

    def test_requirement_lines_are_read_by_their_name(self):
        text = ("# a comment\n"
                "pyyaml  # a bare name with a comment\n"
                "PyYAML[libyaml]~=6.0 ; python_version >= '3.8'\n"
                "-r other.txt\n"
                "--index-url https://example.invalid/simple\n")
        r = check(text)
        self.assertEqual(r.status, brain_doctor.PASS, r.message)
        self.assertIn("pyyaml, PyYAML", r.message)

if __name__ == "__main__":
    unittest.main()

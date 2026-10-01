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

def fake_dist(site: str, dist: str, modules: dict, top_level=None) -> None:
    """A dist-info for `dist` on `site`, plus module files {name: source}."""
    info = Path(site, dist.replace("-", "_") + "-1.0.dist-info")
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist}\nVersion: 1.0\n")
    if top_level is not None:
        (info / "top_level.txt").write_text("".join(t + "\n" for t in top_level))
    for mod, src in modules.items():
        Path(site, mod + ".py").write_text(src)


def check_on(site: str, requirements: str):
    env = {"PYTHONPATH": site + os.pathsep + os.environ.get("PYTHONPATH", "")}
    with mock.patch.dict(os.environ, env):
        return check(requirements)


class ModuleListTest(unittest.TestCase):
    def test_no_module_list_and_no_module_of_that_name_rests_on_metadata(self):
        # An apt flat .egg-info (PyGObject provides `gi`) or a metapackage: guessing
        # the module from the name is the pyyaml-for-yaml mistake again.
        with tempfile.TemporaryDirectory() as site:
            fake_dist(site, "octo-gi-like", {"octo_gi_mod": ""})
            self.assertEqual(check_on(site, "octo-gi-like\n").status, brain_doctor.PASS)

    def test_a_listed_module_that_is_not_shipped_is_skipped(self):
        with tempfile.TemporaryDirectory() as site:
            fake_dist(site, "octo-extra-listed", {"octo_real_mod": ""},
                      top_level=["octo_real_mod", "octo_never_shipped"])
            self.assertEqual(check_on(site, "octo-extra-listed\n").status, brain_doctor.PASS)

    def test_none_of_the_listed_modules_present_is_a_broken_install(self):
        with tempfile.TemporaryDirectory() as site:
            fake_dist(site, "octo-all-gone", {}, top_level=["octo_gone_a", "octo_gone_b"])
            r = check_on(site, "octo-all-gone\n")
            self.assertEqual(r.status, brain_doctor.FAIL)
            self.assertIn("octo-all-gone", r.message)

    def test_a_present_module_that_raises_still_fails(self):
        with tempfile.TemporaryDirectory() as site:
            fake_dist(site, "octo-half-broken", {"octo_ok_mod": "", "octo_bad_mod": "raise ImportError('x')\n"},
                      top_level=["octo_ok_mod", "octo_bad_mod", "octo_never_shipped"])
            self.assertEqual(check_on(site, "octo-half-broken\n").status, brain_doctor.FAIL)


def _marker_evaluator() -> bool:
    """The probe reads markers with `packaging`, else pip's vendored copy. A bare
    venv (uv creates one without pip) has neither, and then the probe checks the
    requirement as written, by design."""
    import importlib.util
    return any(importlib.util.find_spec(m) is not None for m in ("packaging", "pip"))


class RequirementFileTest(unittest.TestCase):
    @unittest.skipUnless(_marker_evaluator(), "no marker evaluator in this interpreter")
    def test_a_marker_that_excludes_this_interpreter_skips_the_check(self):
        r = check('no-such-distribution-octorato-test ; python_version < "3.0"\n')
        self.assertEqual(r.status, brain_doctor.PASS, r.message)

    def test_a_marker_that_includes_this_interpreter_still_checks(self):
        r = check('no-such-distribution-octorato-test ; python_version >= "3.0"\n')
        self.assertEqual(r.status, brain_doctor.FAIL)

    def test_an_include_is_followed(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "requirements.txt").write_text("-r more.txt\npyyaml>=6.0\n")
            Path(d, "more.txt").write_text("no-such-distribution-octorato-test\n-r requirements.txt\n")
            with mock.patch.object(brain_doctor, "CLAUDE_DIR", Path(d)):
                r = brain_doctor.check_python_deps(False)
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("no-such-distribution-octorato-test", r.message)

    def test_bare_urls_name_no_distribution(self):
        text = ("git+https://example.invalid/repo.git#egg=x\n"
                "https://example.invalid/pkg-1.0.tar.gz\n"
                "pyyaml>=6.0\n")
        r = check(text)
        self.assertEqual(r.status, brain_doctor.PASS, r.message)
        self.assertNotIn("git", r.message.replace("pyyaml", ""))

    def test_a_file_with_no_distribution_warns(self):
        self.assertEqual(check("-r nowhere.txt\n--index-url https://example.invalid\n").status,
                         brain_doctor.WARN)

if __name__ == "__main__":
    unittest.main()

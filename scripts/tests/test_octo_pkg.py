#!/usr/bin/env python3
"""Unit tests for the v8 PACKAGE primitive (scripts/octo_pkg.py + gen_skill_manifests.py).

Every test runs against a throwaway HOME and a throwaway brain checkout. Nothing here
touches the real ~/.claude, the real lock, or the real signers file: the whole point
of the primitive is that an install is a controlled write, so a test that wrote into
the live brain would be its own counter-example.

The end-to-end ladder (install, refuse, tamper-before-signature, verify tiers, sync,
uninstall) lives in `octo_pkg.py --selftest`, which is also the registry's liveness
proof. These tests cover the units around it: the hash function's properties, the
signer resolution, the git-exclude bookkeeping, the JSON verify contract the doctor
parses, and the manifest generator.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent.parent
SCRIPTS = BRAIN / "scripts"
FIXTURE = BRAIN / "registry" / "fixtures" / "META.kernel-package"
# Captured at IMPORT, before any test in this run has moved HOME. A sibling test
# module that leaves HOME pointing at its own deleted sandbox would otherwise be
# what a child process here inherits, and the child loses its pip --user imports.
_REAL_HOME = os.environ.get("HOME")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIT_BODY_TEXT = """\
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
# The Apache 2.0 HEADER: its title line, version line and first section heading, and
# nothing else. It used to be this module's stand-in for the Apache license, and the
# recognizer answered it with a clean SPDX id. It is not the license: it is the first
# eight lines of it, and a package stamped Apache-2.0 from those eight lines was named
# after a document nobody had read to the end. It is a NEGATIVE fixture now, and the
# real text (verbatim, and shipped in this repo as a real skill's license) is the
# positive one.
APACHE_HEAD_TEXT = """\
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.
"""
MIT_FILE_TEXT = "MIT License\n\nCopyright (c) 2026 Someone Else, Inc.\n\n" + MIT_BODY_TEXT
APACHE_FULL_TEXT = (BRAIN / "skills" / "cloudflare" / "LICENSE").read_text(encoding="utf-8")


def mutate(text: str, old: str, new: str) -> str:
    """Replace `old` with `new`, and REFUSE a no-op.

    Three fixtures in this module were edits that never landed: the phrase they meant
    to change is wrapped across two lines in the fixture, `str.replace` matched nothing,
    and the test then asserted that verbatim MIT is MIT. It passed against the code it
    was written to catch. A mutation that does not mutate is not a fixture.
    """
    if old not in text:
        raise AssertionError(f"fixture does not contain {old!r}, so this edit is a no-op")
    if old == new:
        raise AssertionError(f"the edit replaces {old!r} with itself, so it is a no-op")
    return text.replace(old, new)


def cut_before(text: str, marker: str) -> str:
    """Everything before `marker`, and REFUSE when the marker is absent.

    `text.split(marker)[0]` returns the WHOLE text when the marker is not there, so a
    fixture edit that silently stopped cutting would assert that verbatim Apache is
    Apache. That is `mutate`'s no-op class wearing a different verb, and it was in this
    module, in the test that proves a clause-9 copy is still a whole license.
    """
    if marker not in text:
        raise AssertionError(f"fixture does not contain {marker!r}, so this cut is a no-op")
    return text.split(marker)[0]


def cut_after(text: str, marker: str) -> str:
    """Everything after `marker`, and REFUSE when the marker is absent."""
    if marker not in text:
        raise AssertionError(f"fixture does not contain {marker!r}, so this cut is a no-op")
    return text.split(marker, 1)[1]


def one_line(text: str) -> str:
    """The same license with each PARAGRAPH unwrapped onto one line.

    Wrapping is not terms, so this is the same document to the recognizer, and it lets
    a test edit one phrase without having to know where the fixture happens to break
    its lines. Paragraph breaks are kept: collapsing the whole file onto a single line
    would put the title, the copyright notice and the license body in one line, which
    is not a shape any license ships in and is not what these fixtures are testing.
    """
    return "\n\n".join(" ".join(block.split())
                       for block in re.split(r"\n\s*\n", text) if block.strip())

octo_pkg = _load("octo_pkg_under_test", SCRIPTS / "octo_pkg.py")
gen = _load("gen_skill_manifests_under_test", SCRIPTS / "gen_skill_manifests.py")


def _ssh_ok() -> bool:
    return shutil.which("ssh-keygen") is not None and octo_pkg.ssh_keygen_y_supported()


class SandboxCase(unittest.TestCase):
    """A brain checkout in a temp dir, with a key minted per test class."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-octo-pkg-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._home = _REAL_HOME or os.environ.get("HOME")
        home = self.tmp / "home"
        self.root = home / ".claude"
        (self.root / "schemas").mkdir(parents=True)
        (self.root / "registry").mkdir(parents=True)
        (self.root / "skills").mkdir(parents=True)
        shutil.copy2(BRAIN / "schemas" / "skill-manifest.schema.json",
                     self.root / "schemas" / "skill-manifest.schema.json")
        (self.root / "packages.lock.json").write_text(
            json.dumps({"version": 1, "packages": []}, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        os.environ["HOME"] = str(home)
        self.addCleanup(self._restore_home)
        self.brain = octo_pkg.Brain(self.root)

    def _restore_home(self):
        if self._home is not None:
            os.environ["HOME"] = self._home

    def mint_key(self, principal: str = "octorato-release") -> Path:
        key = self.tmp / f"key-{principal}"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", principal,
                        "-f", str(key)], check=True, capture_output=True)
        pub = key.with_suffix(".pub").read_text(encoding="utf-8").split()
        line = f"{principal} {pub[0]} {pub[1]}\n"
        f = self.root / octo_pkg.PUBLIC_SIGNERS_REL
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line)
        return key

    def stage(self, which: str = "signed") -> Path:
        dst = self.tmp / f"src-{which}"
        shutil.copytree(FIXTURE / which, dst)
        return dst

    def sign(self, key: Path, pkg: Path):
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n",
                        octo_pkg.SIG_NAMESPACE, str(pkg / "skill.json")],
                       check=True, capture_output=True)


class TestTreeHash(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-tree-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _pkg(self) -> Path:
        d = self.tmp / "pkg"
        (d / "sub").mkdir(parents=True)
        (d / "SKILL.md").write_text("body\n", encoding="utf-8")
        (d / "sub" / "a.txt").write_text("a\n", encoding="utf-8")
        return d

    def test_stable_across_calls(self):
        d = self._pkg()
        self.assertEqual(octo_pkg.tree_sha256(d), octo_pkg.tree_sha256(d))

    def test_manifest_and_signature_excluded(self):
        d = self._pkg()
        before = octo_pkg.tree_sha256(d)
        (d / "skill.json").write_text('{"name":"x"}\n', encoding="utf-8")
        (d / "skill.json.sig").write_text("sig\n", encoding="utf-8")
        self.assertEqual(before, octo_pkg.tree_sha256(d),
                         "the manifest carries the hash, so it cannot be inside it")

    def test_content_change_changes_the_hash(self):
        d = self._pkg()
        before = octo_pkg.tree_sha256(d)
        (d / "sub" / "a.txt").write_text("b\n", encoding="utf-8")
        self.assertNotEqual(before, octo_pkg.tree_sha256(d))

    def test_rename_changes_the_hash(self):
        """Path is fed into the digest, so moving identical bytes is a different tree."""
        d = self._pkg()
        before = octo_pkg.tree_sha256(d)
        (d / "sub" / "a.txt").rename(d / "sub" / "b.txt")
        self.assertNotEqual(before, octo_pkg.tree_sha256(d))

    def test_added_file_changes_the_hash(self):
        d = self._pkg()
        before = octo_pkg.tree_sha256(d)
        (d / "extra.md").write_text("x\n", encoding="utf-8")
        self.assertNotEqual(before, octo_pkg.tree_sha256(d))

    def test_symlink_inside_a_package_is_refused(self):
        d = self._pkg()
        os.symlink("/etc/passwd", d / "escape")
        with self.assertRaises(octo_pkg.PkgError):
            octo_pkg.tree_sha256(d)

    def test_git_dir_is_hashed_not_skipped(self):
        """Reversed deliberately in QA cycle 1. A .git inside an installed package is
        a second repository in the always-on discovery path, able to carry hooks. It
        is content, and a planted one must move the hash."""
        d = self._pkg()
        before = octo_pkg.tree_sha256(d)
        (d / ".git").mkdir()
        (d / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        self.assertNotEqual(before, octo_pkg.tree_sha256(d))

    def test_fixture_hashes_match_their_manifests(self):
        """The shipped fixtures are only a proof while their embedded hash is true."""
        for which, should_match in (("signed", True), ("unsigned", True), ("tampered", False)):
            man = json.loads((FIXTURE / which / "skill.json").read_text(encoding="utf-8"))
            actual = octo_pkg.tree_sha256(FIXTURE / which)
            self.assertEqual(man["tree_sha256"] == actual, should_match, which)


class TestSigners(SandboxCase):
    def test_no_signers_file_means_no_principals(self):
        self.assertEqual(self.brain.known_principals(), {})

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_second_allowed_signers_file_is_honored(self):
        """An adopter adds principals in the gitignored company/config/pkg-signers.
        The file whose principal matches is the one passed to ssh-keygen with -f."""
        key = self.mint_key("adopter-local")
        # move that line from the public file into the private one
        pubfile = self.root / octo_pkg.PUBLIC_SIGNERS_REL
        line = pubfile.read_text(encoding="utf-8")
        pubfile.write_text("", encoding="utf-8")
        priv = self.root / octo_pkg.PRIVATE_SIGNERS_REL
        priv.parent.mkdir(parents=True, exist_ok=True)
        priv.write_text(line, encoding="utf-8")

        self.assertEqual(self.brain.known_principals(), {"adopter-local": priv})
        pkg = self.stage("signed")
        self.sign(key, pkg)
        self.assertEqual(
            octo_pkg._verify_signature(self.brain, pkg / "skill.json", pkg / "skill.json.sig"),
            "adopter-local")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_key_that_is_in_no_signers_file_does_not_verify(self):
        stray = self.tmp / "stray"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(stray)],
                       check=True, capture_output=True)
        self.mint_key()  # a known principal exists, but it is not this key
        pkg = self.stage("signed")
        self.sign(stray, pkg)
        with self.assertRaises(octo_pkg.PkgError):
            octo_pkg._verify_signature(self.brain, pkg / "skill.json", pkg / "skill.json.sig")

    def test_comments_and_blank_lines_are_not_principals(self):
        f = self.root / octo_pkg.PUBLIC_SIGNERS_REL
        f.write_text("# a comment\n\noctorato-release ssh-ed25519 AAAA\n", encoding="utf-8")
        self.assertEqual(sorted(self.brain.known_principals()), ["octorato-release"])


class TestExclude(SandboxCase):
    def test_add_is_idempotent_and_remove_is_clean(self):
        self.assertTrue(self.brain.exclude_add("skills/x"))
        self.assertTrue(self.brain.exclude_add("skills/x"))
        excl = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertEqual(excl.count("skills/x"), 1)
        self.assertTrue(self.brain.exclude_has("skills/x"))
        self.brain.exclude_remove("skills/x")
        self.assertFalse(self.brain.exclude_has("skills/x"))

    def test_remove_leaves_other_entries_alone(self):
        self.brain.exclude_add("skills/a")
        self.brain.exclude_add("skills/b")
        self.brain.exclude_remove("skills/a")
        self.assertFalse(self.brain.exclude_has("skills/a"))
        self.assertTrue(self.brain.exclude_has("skills/b"))


class TestVerifyContract(SandboxCase):
    """The doctor and pre-push read this contract; a change here is a change there."""

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_empty_lock_is_pass_zero_of_zero(self):
        rc = octo_pkg.main(["--brain", str(self.root), "verify", "--all", "--json"])
        self.assertEqual(rc, 0)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_json_shape(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            octo_pkg.main(["--brain", str(self.root), "verify", "--all", "--json"])
        data = json.loads(buf.getvalue())
        self.assertEqual(
            sorted(data), ["fail", "ok", "pass", "ssh_keygen_y", "total", "warn"])
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 0)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_lock_signer_unknown_is_fail_tier(self):
        """A lock entry whose signer is in no allowed-signers file FAILs even when the
        package is absent on disk: an unknown signer is not a sync problem."""
        lock = self.brain.load_lock()
        lock["packages"].append({"name": "ghost", "kind": "skill", "version": "1.0.0",
                                 "tree_sha256": "0" * 64, "signer": "someone-else",
                                 "source": "/nowhere", "installed_at": "2026-01-01T00:00:00Z"})
        self.brain.save_lock(lock)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 1)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_absent_on_disk_is_warn_not_fail(self):
        self.mint_key()
        lock = self.brain.load_lock()
        lock["packages"].append({"name": "ghost", "kind": "skill", "version": "1.0.0",
                                 "tree_sha256": "0" * 64, "signer": "octorato-release",
                                 "source": "/nowhere", "installed_at": "2026-01-01T00:00:00Z"})
        self.brain.save_lock(lock)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0,
                         "a second machine that pulled the lock offline must still push")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_replacing_the_symlink_with_a_real_dir_is_fail(self):
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(pkg)]), 0)
        link = self.brain.link_path("sample-package")
        link.unlink()
        link.mkdir()
        (link / "SKILL.md").write_text("impostor\n", encoding="utf-8")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 1)


class TestInstallRefusals(SandboxCase):
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_manifest_that_fails_the_schema_is_refused(self):
        key = self.mint_key()
        pkg = self.stage("signed")
        man = json.loads((pkg / "skill.json").read_text(encoding="utf-8"))
        man["typo_field"] = "additionalProperties is false, so this must surface"
        (pkg / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        self.sign(key, pkg)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(pkg)]), 1)
        self.assertFalse(self.brain.vendor_path("sample-package").exists())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_installing_twice_is_refused_and_leaves_the_first_intact(self):
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(pkg)]), 0)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(pkg)]), 1)
        self.assertEqual(len(self.brain.load_lock()["packages"]), 1)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_pre_existing_real_dir_at_the_link_path_is_never_replaced(self):
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        squatter = self.brain.link_path("sample-package")
        squatter.mkdir(parents=True)
        (squatter / "SKILL.md").write_text("the operator's own skill\n", encoding="utf-8")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(pkg)]), 1)
        self.assertEqual((squatter / "SKILL.md").read_text(encoding="utf-8"),
                         "the operator's own skill\n")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_uninstall_refuses_to_delete_a_dir_that_is_not_our_symlink(self):
        squatter = self.brain.link_path("mine")
        squatter.mkdir(parents=True)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "uninstall", "mine"]), 1)
        self.assertTrue(squatter.is_dir())


class TestRelock(SandboxCase):
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_relock_refuses_a_tampered_tree_rather_than_laundering_it(self):
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        octo_pkg.main(["--brain", str(self.root), "install", str(pkg)])
        before = self.brain.load_lock()["packages"][0]["tree_sha256"]
        edited = self.brain.vendor_path("sample-package") / "SKILL.md"
        edited.write_text(edited.read_text(encoding="utf-8") + "injected\n", encoding="utf-8")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "lock"]), 1)
        self.assertEqual(self.brain.load_lock()["packages"][0]["tree_sha256"], before,
                         "re-lock must not bless a tree whose manifest no longer matches")


class TestSelftest(unittest.TestCase):
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_selftest_passes_as_a_subprocess(self):
        """The same invocation the registry proof and pre-push use."""
        cp = subprocess.run([sys.executable, str(SCRIPTS / "octo_pkg.py"), "--selftest",
                             "registry/fixtures/META.kernel-package"],
                            cwd=str(BRAIN), capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("selftest OK", cp.stdout)


class TestGitHubPath(SandboxCase):
    """Defect 1: the helper module was executed without being registered in
    sys.modules, so its dataclasses could not resolve their own module and EVERY
    GitHub install died with 'cannot load installer helpers'."""

    def test_helper_module_loads_and_exposes_the_fetch_helpers(self):
        gh = octo_pkg._github_module()
        for fn in ("_git_sparse_checkout", "_download_repo_zip", "_prepare_repo",
                   "_validate_relative_path", "Source"):
            self.assertTrue(hasattr(gh, fn), fn)
        self.assertIs(gh, octo_pkg._github_module(), "second call must reuse the module")

    def _seed_repo(self, branch: str = "main") -> Path:
        """A real git repo holding the fixture at skills/sample-package.

        Local, so the git path is exercised WITHOUT the network: same
        _git_sparse_checkout call the GitHub path makes. Chosen over cloning
        CarlosCaPe/octorato because a unit test that needs github.com is a test that
        fails on a plane, and the code under test is identical either way."""
        repo = self.tmp / f"repo-{branch}"
        (repo / "skills").mkdir(parents=True)
        shutil.copytree(FIXTURE / "signed", repo / "skills" / "sample-package")
        for cmd in (["git", "init", "-q", "-b", branch, str(repo)],
                    ["git", "-C", str(repo), "add", "-A"],
                    ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "-m", "seed"]):
            subprocess.run(cmd, check=True, capture_output=True)
        return repo

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_install_from_a_git_repo_source(self):
        key = self.mint_key()
        repo = self._seed_repo()
        self.sign(key, repo / "skills" / "sample-package")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "sig"], check=True, capture_output=True)
        rc = octo_pkg.main(["--brain", str(self.root), "install", str(repo),
                            "--path", "skills/sample-package"])
        self.assertEqual(rc, 0)
        self.assertTrue(self.brain.vendor_path("sample-package").is_dir())
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0)

    def test_ref_defaults_fall_back_from_main_to_master(self):
        """Defect 12: --ref used to default to the literal 'main', so a repo on
        master failed with a clone error that named the wrong thing."""
        repo = self._seed_repo(branch="master")
        gh = octo_pkg._github_module()
        with tempfile.TemporaryDirectory() as td:
            root, used = octo_pkg._sparse_checkout(gh, str(repo), None,
                                                   "skills/sample-package", Path(td))
            self.assertEqual(used, "master")
            self.assertTrue((root / "skills" / "sample-package" / "SKILL.md").is_file())

    def test_a_git_repo_directory_is_not_treated_as_a_package_directory(self):
        repo = self._seed_repo()
        self.assertFalse(octo_pkg._is_local_source(str(repo)))
        self.assertTrue(octo_pkg._is_local_source(str(FIXTURE / "signed")))


class TestUrlParsing(unittest.TestCase):
    """Defect 9 (CodeQL py/incomplete-url-substring-sanitization) and the
    /tree/<ref-with-slash>/ split."""

    def test_lookalike_hosts_are_refused(self):
        for bad in ("https://github.com.evil.test/o/r/tree/main/p",
                    "https://evil.test/?u=https://github.com/o/r",
                    "https://gitlab.com/o/r/tree/main/p",
                    "https://notgithub.com/o/r"):
            with self.assertRaises(octo_pkg.PkgError, msg=bad):
                octo_pkg.parse_github_url(bad, None, None)

    def test_real_host_forms_accepted(self):
        for good in ("https://github.com/o/r/tree/main/p", "https://www.github.com/o/r/tree/main/p"):
            owner, repo, ref, path = octo_pkg.parse_github_url(good, None, None)
            self.assertEqual((owner, repo, ref, path), ("o", "r", "main", "p"))

    def test_ref_with_slashes_is_exact_when_path_is_supplied(self):
        owner, repo, ref, path = octo_pkg.parse_github_url(
            "https://github.com/o/r/tree/feat/v8/kernel", "skills/x")
        self.assertEqual((ref, path), ("feat/v8/kernel", "skills/x"))

    def test_dot_git_suffix_stripped(self):
        owner, repo, _, _ = octo_pkg.parse_github_url("https://github.com/o/r.git", "p", "main")
        self.assertEqual(repo, "r")


class TestQaCycle2(SandboxCase):
    """Regressions found in QA cycle 2, one test per item."""

    def _seed(self, branch="master", extra_ref=None) -> Path:
        repo = self.tmp / f"r-{branch}-{extra_ref}"
        (repo / "skills").mkdir(parents=True)
        shutil.copytree(FIXTURE / "signed", repo / "skills" / "pdf")
        run = lambda *c: subprocess.run(c, check=True, capture_output=True)
        run("git", "init", "-q", "-b", branch, str(repo))
        run("git", "-C", str(repo), "add", "-A")
        run("git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "-m", "seed")
        if extra_ref:
            run("git", "-C", str(repo), "branch", extra_ref)
        return repo

    # -- item 1 -----------------------------------------------------------
    def test_no_substring_host_test_survives_in_the_source(self):
        src = (SCRIPTS / "octo_pkg.py").read_text(encoding="utf-8")
        for banned in ('"://" in source', 'startswith("github.com', "'://' in source"):
            self.assertNotIn(banned, src,
                             "the host decision must live only in urlsplit().netloc")

    def test_url_shaped_lookalikes_are_refused_through_fetch_source(self):
        """Each of these previously took the 'is a URL' branch on a substring."""
        for bad in ("https://evil.test/github.com/o/r",
                    "https://github.com.evil.test/o/r/tree/main/p",
                    "github.com.evil.test/o/r",
                    "https://user@evil.test/o/r"):
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(octo_pkg.PkgError, msg=bad) as cm:
                    octo_pkg.fetch_source(bad, "p", "main", Path(td))
                self.assertIn("not a GitHub URL", str(cm.exception), bad)

    def test_owner_repo_and_bare_host_still_normalize_to_github(self):
        self.assertEqual(octo_pkg._as_url("openai/skills"), "https://github.com/openai/skills")
        self.assertEqual(octo_pkg._as_url("github.com/o/r"), "https://github.com/o/r")
        self.assertEqual(octo_pkg._as_url("https://github.com/o/r"), "https://github.com/o/r")
        owner, repo, _, _ = octo_pkg.parse_github_url(octo_pkg._as_url("openai/skills"), "p")
        self.assertEqual((owner, repo), ("openai", "skills"))

    # -- item 2 -----------------------------------------------------------
    def test_split_source_spec_returns_the_pinned_ref(self):
        self.assertEqual(octo_pkg._split_source_spec("git+file:///r@v1.2.0#skills/pdf"),
                         ("/r", "skills/pdf", "v1.2.0"))
        self.assertEqual(octo_pkg._split_source_spec("/plain/dir"), ("/plain/dir", None, None))

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_restores_a_package_pinned_at_a_non_default_ref(self):
        """The ref was parsed off the lock source and thrown away, so sync refetched
        at master, got a different tree, and the WARN never cleared."""
        key = self.mint_key()
        repo = self._seed(branch="master", extra_ref="release-1")
        pkg_in_repo = repo / "skills" / "pdf"
        self.sign(key, pkg_in_repo)
        run = lambda *c: subprocess.run(c, check=True, capture_output=True)
        run("git", "-C", str(repo), "checkout", "-q", "release-1")
        (pkg_in_repo / "ONLY-ON-RELEASE-1.md").write_text("pinned\n", encoding="utf-8")
        man = json.loads((pkg_in_repo / "skill.json").read_text(encoding="utf-8"))
        man["tree_sha256"] = octo_pkg.tree_sha256(pkg_in_repo, "skill")
        (pkg_in_repo / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        (pkg_in_repo / octo_pkg.SIG_NAME).unlink()
        self.sign(key, pkg_in_repo)
        run("git", "-C", str(repo), "add", "-A")
        run("git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "-m", "release-1")
        run("git", "-C", str(repo), "checkout", "-q", "master")

        rc = octo_pkg.main(["--brain", str(self.root), "install", str(repo),
                            "--path", "skills/pdf", "--ref", "release-1"])
        self.assertEqual(rc, 0)
        entry = self.brain.load_lock()["packages"][0]
        self.assertIn("@release-1#", entry["source"])
        dest = self.brain.vendor_path("sample-package")
        self.assertTrue((dest / "ONLY-ON-RELEASE-1.md").is_file())

        shutil.rmtree(dest)
        self.brain.link_path("sample-package").unlink()
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "sync"]), 0)
        self.assertTrue((dest / "ONLY-ON-RELEASE-1.md").is_file(),
                        "sync must refetch at the pinned ref, not at the default branch")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0)

    # -- item 3 -----------------------------------------------------------
    def test_browser_url_ending_in_the_path_plus_explicit_path(self):
        """The wiki's own install line shape: .../tree/master/skills/pdf --path skills/pdf."""
        owner, repo, ref, path = octo_pkg.parse_github_url(
            "https://github.com/CarlosCaPe/octorato/tree/master/skills/pdf", "skills/pdf")
        self.assertEqual((owner, repo, ref, path), ("CarlosCaPe", "octorato", "master", "skills/pdf"))

    def test_ref_with_slashes_still_exact_when_the_tail_does_not_match(self):
        _, _, ref, path = octo_pkg.parse_github_url(
            "https://github.com/o/r/tree/feat/v8/kernel", "skills/x")
        self.assertEqual((ref, path), ("feat/v8/kernel", "skills/x"))

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_the_wiki_command_shape_installs_against_a_local_repo(self):
        key = self.mint_key()
        repo = self._seed()
        self.sign(key, repo / "skills" / "pdf")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "sig"], check=True, capture_output=True)
        # same argument shape as the wiki line: a path-carrying source plus --path
        rc = octo_pkg.main(["--brain", str(self.root), "install", str(repo),
                            "--path", "skills/pdf"])
        self.assertEqual(rc, 0)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0)

    # -- item 4 -----------------------------------------------------------
    def test_clone_retry_does_not_collide_on_a_shared_dest_dir(self):
        """https then ssh both cloned into <tmp>/repo, so the retry always died with
        'destination path already exists' and hid the real error."""
        gh = octo_pkg._github_module()
        repo = self._seed()
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(Exception) as cm:
                gh._git_sparse_checkout(str(self.tmp / "does-not-exist"), "master",
                                        ["skills/pdf"], td)
            self.assertNotIn("already exists", str(cm.exception),
                             "the retry must report the real failure, not a path collision")
            a = gh._git_sparse_checkout(str(repo), "master", ["skills/pdf"], td)
            b = gh._git_sparse_checkout(str(repo), "master", ["skills/pdf"], td)
            self.assertNotEqual(a, b)
            for d in (a, b):
                self.assertTrue(Path(d, "skills", "pdf", "SKILL.md").is_file())

    # -- item 5 -----------------------------------------------------------
    def test_lock_scratch_files_are_gitignored_by_a_tracked_pattern(self):
        brain_root = BRAIN
        names = [f"packages.lock.json.{os.getpid()}.tmp", "packages.lock.json.lock"]
        cp = subprocess.run(["git", "check-ignore", "-v", "--no-index", *names],
                            cwd=str(brain_root), capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, f"not ignored: {cp.stdout or cp.stderr}")
        self.assertEqual(len(cp.stdout.strip().splitlines()), len(names), cp.stdout)
        for line in cp.stdout.strip().splitlines():
            self.assertTrue(line.startswith(".gitignore:"), f"must be the TRACKED file: {line}")

    def test_save_lock_temp_name_matches_the_ignored_pattern(self):
        self.brain.save_lock({"version": 1, "packages": []})
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])

    # -- item 6 -----------------------------------------------------------
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_hash_write_removes_a_stale_signature(self):
        """ssh-keygen -Y sign over an existing .sig prompts, declines on EOF, keeps the
        OLD signature and exits 0. Measured. So the stale file cannot be left there."""
        import contextlib, io
        key = self.mint_key()
        d = self.tmp / "pub"
        shutil.copytree(FIXTURE / "signed", d)
        self.sign(key, d)
        old_sig = (d / octo_pkg.SIG_NAME).read_bytes()
        (d / "NEW.md").write_text("a later edit\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            octo_pkg.main(["--brain", str(self.root), "hash", str(d), "--write"])
        self.assertFalse((d / octo_pkg.SIG_NAME).exists(), "the stale .sig must be gone")
        self.assertIn("removed stale", buf.getvalue())
        # and the publisher flow now produces a signature over the NEW manifest
        self.sign(key, d)
        self.assertNotEqual(old_sig, (d / octo_pkg.SIG_NAME).read_bytes())
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(d)]), 0)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_without_the_fix_the_stale_signature_would_install_a_lie(self):
        """Control: signing over a kept .sig is a no-op that exits 0, so an install
        would carry a signature made over a manifest nobody shipped."""
        key = self.mint_key()
        d = self.tmp / "control"
        shutil.copytree(FIXTURE / "signed", d)
        self.sign(key, d)
        before = (d / octo_pkg.SIG_NAME).read_bytes()
        man = json.loads((d / "skill.json").read_text(encoding="utf-8"))
        man["version"] = "9.9.9"
        (d / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        cp = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n",
                             octo_pkg.SIG_NAMESPACE, str(d / "skill.json")],
                            stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(cp.returncode, 0, "ssh-keygen reports success")
        self.assertEqual(before, (d / octo_pkg.SIG_NAME).read_bytes(),
                         "and silently keeps the old signature: this is why hash --write deletes it")


class TestLockIntegrity(SandboxCase):
    def _write_lock(self, packages):
        self.brain.lock_path.write_text(
            json.dumps({"version": 1, "packages": packages}, indent=2) + "\n", encoding="utf-8")

    def test_escaped_name_refuses_the_whole_lock(self):
        self._write_lock([{"name": "../../../escaped", "kind": "skill", "version": "1.0.0",
                           "tree_sha256": "0" * 64, "signer": "octorato-release",
                           "source": "/nowhere", "installed_at": "2026-01-01T00:00:00Z"}])
        with self.assertRaises(octo_pkg.PkgError):
            self.brain.load_lock()
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 1,
                         "an unreadable lock is never a PASS")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "sync"]), 1)
        self.assertFalse((self.tmp / "escaped").exists())
        self.assertFalse((self.root.parent / "escaped").exists())

    def test_absolute_and_reserved_names_refused(self):
        for bad in ("/etc/passwd", "vendor", "learned", "Bad-Case", "a", "x" * 65, ""):
            self._write_lock([{"name": bad, "kind": "skill", "version": "1.0.0",
                               "tree_sha256": "0" * 64, "signer": "s", "source": "/x",
                               "installed_at": "2026-01-01T00:00:00Z"}])
            with self.assertRaises(octo_pkg.PkgError, msg=bad):
                self.brain.load_lock()

    def test_duplicate_names_refused(self):
        e = {"name": "dup", "kind": "skill", "version": "1.0.0", "tree_sha256": "0" * 64,
             "signer": "s", "source": "/x", "installed_at": "2026-01-01T00:00:00Z"}
        self._write_lock([e, dict(e)])
        with self.assertRaises(octo_pkg.PkgError):
            self.brain.load_lock()

    def test_save_lock_is_atomic_and_leaves_no_temp_file(self):
        self.brain.save_lock({"version": 1, "packages": []})
        strays = [p.name for p in self.root.iterdir() if ".tmp" in p.name]
        self.assertEqual(strays, [])

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_two_concurrent_installs_keep_both_entries(self):
        """Defect 4: load-modify-save without a lock loses one of two racing writes."""
        key = self.mint_key()
        srcs = []
        for name in ("pkg-alpha", "pkg-beta"):
            d = self.tmp / f"src-{name}"
            shutil.copytree(FIXTURE / "signed", d)
            man = json.loads((d / "skill.json").read_text(encoding="utf-8"))
            man["name"] = name
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n# {name}\n", encoding="utf-8")
            man["tree_sha256"] = octo_pkg.tree_sha256(d, "skill")
            (d / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
            self.sign(key, d)
            srcs.append(d)
        procs = [subprocess.Popen(
            [sys.executable, str(SCRIPTS / "octo_pkg.py"), "--brain", str(self.root),
             "install", str(d)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            # The sandbox HOME is fine in-process (sys.path is fixed at startup) but a
            # CHILD re-derives its user site-packages from HOME, so it would lose
            # jsonschema. The brain is pinned by --brain, not by HOME.
            env={**os.environ, "HOME": self._home or os.environ["HOME"]}) for d in srcs]
        outs = [pr.communicate() for pr in procs]
        for pr, (o, e) in zip(procs, outs):
            self.assertEqual(pr.returncode, 0, e.decode())
        names = sorted(p["name"] for p in self.brain.load_lock()["packages"])
        self.assertEqual(names, ["pkg-alpha", "pkg-beta"],
                         "a racing install must not drop the other's lock entry")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0)


class TestHashCommandAndKinds(SandboxCase):
    def test_arm_json_inside_a_skill_package_is_hashed(self):
        """Defect 5: excluding by filename across kinds left a hole to hide bytes in."""
        d = self.tmp / "pkg"
        shutil.copytree(FIXTURE / "signed", d)
        before = octo_pkg.tree_sha256(d, "skill")
        (d / "arm.json").write_text('{"payload": "not excluded"}\n', encoding="utf-8")
        self.assertNotEqual(before, octo_pkg.tree_sha256(d, "skill"))

    def test_git_dir_is_hashed_now(self):
        d = self.tmp / "pkg2"
        shutil.copytree(FIXTURE / "signed", d)
        before = octo_pkg.tree_sha256(d, "skill")
        (d / ".git").mkdir()
        (d / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        self.assertNotEqual(before, octo_pkg.tree_sha256(d, "skill"),
                            "a second repo in the discovery path must not be invisible")

    def test_unknown_kind_refused(self):
        with self.assertRaises(octo_pkg.PkgError):
            octo_pkg.tree_sha256(FIXTURE / "signed", "banana")

    def test_hash_command_prints_and_embeds_the_same_digest(self):
        import contextlib, io
        d = self.tmp / "pkg3"
        shutil.copytree(FIXTURE / "signed", d)
        (d / "extra.txt").write_text("changes the tree\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(octo_pkg.main(["--brain", str(self.root), "hash", str(d)]), 0)
        printed = buf.getvalue().splitlines()[0].strip()
        self.assertEqual(printed, octo_pkg.tree_sha256(d, "skill"))
        with contextlib.redirect_stdout(io.StringIO()):
            octo_pkg.main(["--brain", str(self.root), "hash", str(d), "--write"])
        self.assertEqual(json.loads((d / "skill.json").read_text(encoding="utf-8"))["tree_sha256"],
                         printed, "the embedded digest must be the one the installer recomputes")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_hash_write_then_sign_then_install_is_the_documented_publisher_flow(self):
        key = self.mint_key()
        d = self.tmp / "published"
        shutil.copytree(FIXTURE / "signed", d)
        (d / "NOTES.md").write_text("a real edit by the publisher\n", encoding="utf-8")
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            octo_pkg.main(["--brain", str(self.root), "hash", str(d), "--write"])
        self.sign(key, d)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(d)]), 0)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0)


class TestNoHalfInstalls(SandboxCase):
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_failure_after_the_copy_leaves_no_orphan_tree(self):
        """Defect 7: a raise between copytree and the lock write used to leave an
        unverifiable tree sitting in the discovery path."""
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        original = octo_pkg.Brain.save_lock

        def boom(self_, lock):
            raise OSError("disk full")
        octo_pkg.Brain.save_lock = boom
        try:
            rc = octo_pkg.main(["--brain", str(self.root), "install", str(pkg)])
        finally:
            octo_pkg.Brain.save_lock = original
        self.assertEqual(rc, 1)
        self.assertFalse(self.brain.vendor_path("sample-package").exists())
        self.assertFalse(self.brain.link_path("sample-package").is_symlink())
        self.assertFalse(self.brain.exclude_has("skills/sample-package"))
        self.assertEqual(self.brain.load_lock()["packages"], [])

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_never_overwrites_a_first_party_directory(self):
        """Defect 8: sync used to copytree over whatever sat at skills/<name>."""
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        octo_pkg.main(["--brain", str(self.root), "install", str(pkg)])
        shutil.rmtree(self.brain.vendor_path("sample-package"))
        self.brain.link_path("sample-package").unlink()
        mine = self.brain.link_path("sample-package")
        mine.mkdir()
        (mine / "SKILL.md").write_text("the operator's own work\n", encoding="utf-8")
        octo_pkg.main(["--brain", str(self.root), "sync"])
        self.assertEqual((mine / "SKILL.md").read_text(encoding="utf-8"),
                         "the operator's own work\n")
        self.assertFalse(self.brain.vendor_path("sample-package").exists())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_vendor_entry_that_is_a_symlink_is_fail(self):
        """Defect 6: resolve() would follow it and report PASS on unverified bytes."""
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        octo_pkg.main(["--brain", str(self.root), "install", str(pkg)])
        dest = self.brain.vendor_path("sample-package")
        moved = self.tmp / "moved-tree"
        shutil.move(str(dest), str(moved))
        os.symlink(str(moved), dest, target_is_directory=True)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 1)


class TestProbeAndExclude(SandboxCase):
    def test_ssh_keygen_absence_is_fail_on_an_empty_lock_too(self):
        """Defect 11: verify used to PASS with an empty lock while the doctor,
        reading the same machine, went FAIL on the probe."""
        original = octo_pkg.ssh_keygen_y_supported
        octo_pkg.ssh_keygen_y_supported = lambda: False
        try:
            self.assertEqual(self.brain.load_lock()["packages"], [])
            self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 1)
        finally:
            octo_pkg.ssh_keygen_y_supported = original

    def test_exclude_is_never_written_into_an_enclosing_unrelated_repo(self):
        """Defect 12: a brain root inside someone else's checkout would get its
        symlink excluded in THEIR .git/info/exclude."""
        outer = self.tmp / "outer"
        inner = outer / "nested" / "brain"
        inner.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(outer)], check=True, capture_output=True)
        b = octo_pkg.Brain(inner)
        self.assertIsNone(b._exclude_file())
        self.assertFalse(b.exclude_add("skills/x"))
        outer_excl = outer / ".git" / "info" / "exclude"
        # git init writes this file itself, so its existence proves nothing. What must
        # hold is that OUR line never reached it.
        body = outer_excl.read_text(encoding="utf-8") if outer_excl.exists() else ""
        self.assertNotIn("skills/x", body)

    def test_a_git_worktree_still_gets_its_exclude_written(self):
        """The first guard for the case above required the git dir to sit UNDER the
        brain root, which silently disabled the exclude in every worktree: a worktree
        keeps its common dir back in the main checkout. Found by running the wiki's
        own commands in a worktree, where install printed 'not a git checkout'."""
        main_repo = self.tmp / "mainrepo"
        main_repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "master", str(main_repo)],
                       check=True, capture_output=True)
        (main_repo / "f.txt").write_text("x\n", encoding="utf-8")
        for cmd in (["git", "-C", str(main_repo), "add", "-A"],
                    ["git", "-C", str(main_repo), "-c", "user.email=t@t", "-c",
                     "user.name=t", "commit", "-q", "-m", "seed"],
                    ["git", "-C", str(main_repo), "worktree", "add", "-q", "-b", "wt",
                     str(self.tmp / "wt")]):
            subprocess.run(cmd, check=True, capture_output=True)
        b = octo_pkg.Brain(self.tmp / "wt")
        self.assertIsNotNone(b._exclude_file())
        self.assertTrue(b.exclude_add("skills/x"))
        self.assertTrue(b.exclude_has("skills/x"))
        b.exclude_remove("skills/x")
        self.assertFalse(b.exclude_has("skills/x"))


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-gen-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "skills"
        self.root.mkdir()

    def _skill(self, name: str, body: str) -> Path:
        d = self.root / name
        d.mkdir()
        (d / "SKILL.md").write_text(body, encoding="utf-8")
        return d

    def _gen(self, *extra: str) -> tuple[int, str]:
        """Run the generator and return (exit code, what it printed). The report is
        part of the contract: a refusal that names the wrong reason is a wrong answer."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gen.main(["--root", str(self.root), "--write", *extra])
        return rc, buf.getvalue()

    def test_dry_run_writes_nothing(self):
        d = self._skill("alpha", "---\nname: alpha\ndescription: does a thing\n---\n# Alpha\n")
        gen.main(["--root", str(self.root)])
        self.assertFalse((d / "skill.json").exists())

    def test_write_produces_a_schema_valid_manifest(self):
        from jsonschema import Draft202012Validator
        self._skill("alpha", "---\nname: alpha\ndescription: does a thing\n---\n# Alpha\n")
        self.assertEqual(gen.main(["--root", str(self.root), "--write"]), 0)
        man = json.loads((self.root / "alpha" / "skill.json").read_text(encoding="utf-8"))
        schema = json.loads((BRAIN / "schemas" / "skill-manifest.schema.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(man)), [])
        self.assertEqual(man["version"], "1.0.0")
        self.assertEqual(man["kind"], "skill")
        self.assertNotIn("tree_sha256", man,
                         "an in-repo manifest must not carry a hash that goes stale on edit")

    def test_description_falls_back_to_the_first_heading(self):
        self._skill("beta", "---\nname: beta\n---\n# Beta does something\n")
        gen.main(["--root", str(self.root), "--write"])
        man = json.loads((self.root / "beta" / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(man["description"], "Beta does something")

    def test_short_description_metadata_is_used(self):
        self._skill("gamma", "---\nname: gamma\nmetadata:\n  short-description: terse\n---\n")
        gen.main(["--root", str(self.root), "--write"])
        man = json.loads((self.root / "gamma" / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(man["description"], "terse")

    def test_a_skill_with_nothing_to_describe_is_reported_not_guessed(self):
        self._skill("delta", "no front matter, no heading\n")
        self.assertEqual(gen.main(["--root", str(self.root), "--write"]), 1)
        self.assertFalse((self.root / "delta" / "skill.json").exists())

    def test_existing_manifest_is_left_alone_without_force(self):
        d = self._skill("eps", "---\nname: eps\ndescription: d\n---\n")
        (d / "skill.json").write_text('{"kept": true}\n', encoding="utf-8")
        gen.main(["--root", str(self.root), "--write"])
        self.assertEqual(json.loads((d / "skill.json").read_text(encoding="utf-8")),
                         {"kept": True})
        gen.main(["--root", str(self.root), "--write", "--force"])
        self.assertIn("name", json.loads((d / "skill.json").read_text(encoding="utf-8")))

    def test_vendor_and_learned_are_skipped(self):
        for skipped in ("vendor", "learned"):
            d = self.root / skipped
            d.mkdir()
            (d / "SKILL.md").write_text("---\nname: x\ndescription: d\n---\n", encoding="utf-8")
        gen.main(["--root", str(self.root), "--write"])
        for skipped in ("vendor", "learned"):
            self.assertFalse((self.root / skipped / "skill.json").exists())

    def test_per_skill_license_beats_the_repo_default(self):
        d = self._skill("zeta", "---\nname: zeta\ndescription: d\n---\n")
        (d / "LICENSE.txt").write_text(APACHE_FULL_TEXT, encoding="utf-8")
        gen.main(["--root", str(self.root), "--write", "--default-license", "MIT"])
        man = json.loads((d / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(man["license"], "Apache-2.0")

    # --- the four roads a license value can be reached by --------------------
    # A LICENSE that is present says something. Absent is the only case a default
    # may speak for, and the two failure roads (unrecognized, unreadable) must be
    # reported rather than relabelled: a wrong license on a public package is a
    # legal claim about someone else's work.

    # The MIT license in full, written out in this module rather than imported from the
    # one under test: a fixture derived from the recognizer agrees with it by
    # construction. The fixture this replaces was an ABRIDGED MIT on one line (a grant
    # cut off at "without restriction", a disclaimer cut off at "EXPRESS OR IMPLIED")
    # and the recognizer called it MIT, which is the same defect as the EULA: a prefix
    # match names a document after reading its first clause.
    _MIT_BODY = MIT_BODY_TEXT
    _FOREIGN_TERMS = ('Use of these skills and related files ("Materials") is governed by the Vendor Developer Terms (available at https://vendor.example/legal/developer-terms/).\\n')

    def test_no_license_falls_back_to_the_repo_default(self):
        self._skill("eta", "---\nname: eta\ndescription: d\n---\n")
        self.assertEqual(gen.main(["--root", str(self.root), "--write",
                                   "--default-license", "MIT"]), 0)
        man = json.loads((self.root / "eta" / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(man["license"], "MIT")

    def test_an_unrecognized_license_is_reported_not_defaulted(self):
        d = self._skill("theta", "---\nname: theta\ndescription: d\n---\n")
        (d / "LICENSE.txt").write_text(self._FOREIGN_TERMS, encoding="utf-8")
        rc, out = self._gen("--default-license", "MIT")
        self.assertEqual(rc, 1)
        self.assertFalse((d / "skill.json").exists(),
                         "a manifest was written claiming the repo default over foreign terms")
        self.assertIn("does not recognize", out)

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "chmod 000 does not deny the owner on Windows or as root")
    def test_an_unreadable_license_is_reported_not_defaulted(self):
        d = self._skill("iota", "---\nname: iota\ndescription: d\n---\n")
        lic = d / "LICENSE.txt"
        lic.write_text(self._MIT_BODY, encoding="utf-8")
        lic.chmod(0o000)
        self.addCleanup(lic.chmod, 0o644)
        rc, out = self._gen("--default-license", "MIT")
        self.assertEqual(rc, 1)
        self.assertFalse((d / "skill.json").exists(),
                         "present-and-unreadable was collapsed into absent")
        # The road matters, not just the refusal: an unreadable LICENSE and an
        # unrecognized one both stop the write, and reporting the wrong one sends
        # whoever fixes it to read terms nobody could open.
        self.assertIn("unreadable", out)

    def test_an_uppercase_license_extension_is_still_found(self):
        d = self._skill("kappa", "---\nname: kappa\ndescription: d\n---\n")
        (d / "LICENSE.TXT").write_text(self._FOREIGN_TERMS, encoding="utf-8")
        self.assertEqual(gen.main(["--root", str(self.root), "--write",
                                   "--default-license", "MIT"]), 1)
        self.assertFalse((d / "skill.json").exists(),
                         "LICENSE.TXT was never opened, so foreign terms read as no terms")

    def test_verbatim_mit_without_a_header_line_is_recognized(self):
        d = self._skill("lambda", "---\nname: lambda\ndescription: d\n---\n")
        (d / "LICENSE.txt").write_text("Copyright 2025 Someone Else, Inc.\n\n" + self._MIT_BODY,
                                       encoding="utf-8")
        self.assertEqual(gen.main(["--root", str(self.root), "--write",
                                   "--default-license", "Apache-2.0"]), 0)
        man = json.loads((d / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(man["license"], "MIT")

    def test_prose_that_merely_quotes_mit_is_not_claimed_as_mit(self):
        d = self._skill("mu", "---\nname: mu\ndescription: d\n---\n")
        (d / "LICENSE.txt").write_text(
            self._FOREIGN_TERMS
            + "\nThese terms are not the MIT License. For reference, MIT reads:\n\n"
            + self._MIT_BODY, encoding="utf-8")
        self.assertEqual(gen.main(["--root", str(self.root), "--write",
                                   "--default-license", "MIT"]), 1)
        self.assertFalse((d / "skill.json").exists(),
                         "a document that quotes the MIT grant was claimed as MIT")


    def test_an_unreadable_repo_license_is_not_assumed_to_be_mit(self):
        # The default speaks for 192 skills, so where IT comes from is the same
        # question one level up: a repo whose own LICENSE cannot be read has no
        # default to give, and the answer is a usage error, not a constant.
        fake_brain = self.tmp / "brain"
        fake_brain.mkdir()
        (fake_brain / "LICENSE").write_text(self._FOREIGN_TERMS, encoding="utf-8")
        self.assertIsNone(gen.repo_default_license(fake_brain))
        real, gen.BRAIN = gen.BRAIN, fake_brain
        self.addCleanup(setattr, gen, "BRAIN", real)
        self._skill("nu", "---\nname: nu\ndescription: d\n---\n")
        rc, _ = self._gen()
        self.assertEqual(rc, 2)
        self.assertFalse((self.root / "nu" / "skill.json").exists())


class TestTheRecognizerRefusesMitLookalikes(unittest.TestCase):
    """MIT recognized end to end, or not at all.

    The prefix recognizer this replaces anchored the grant through "obtaining a copy"
    and matched the as-is clause by prefix, so text could be spliced into the grant and
    appended after the disclaimer and the document still came back MIT. Each case here
    is one edit away from `MIT_FILE_TEXT`, which must stay MIT: a refusal that also
    refuses the real thing is not a fix.
    """

    def test_the_benign_counterpart_is_still_mit(self):
        self.assertEqual(gen.license_terms(MIT_FILE_TEXT), ("MIT", ""))

    def test_a_proprietary_evaluation_eula_is_not_mit(self):
        # Opens with MIT's exact first words, grants thirty days of evaluation and
        # forbids redistribution, then carries MIT's notice and disclaimer verbatim.
        # The old recognizer wrote this out as MIT end to end.
        eula = ("Copyright (c) 2026 Vendor Inc. All rights reserved.\n\n"
                "Permission is hereby granted, free of charge, to any person obtaining "
                "a copy of this software to EVALUATE the Software for thirty (30) days. "
                "No other right is granted. Redistribution is prohibited.\n\n"
                + cut_after(MIT_BODY_TEXT, "subject to the following conditions:").lstrip())
        ident, why = gen.license_terms(eula)
        self.assertIsNone(ident, "a proprietary EULA was recognized as MIT")
        # The cause is the word that differs, quoted with the line it sits on.
        self.assertIn("differs from the license text", why)

    def test_a_commons_clause_after_mit_is_not_mit(self):
        text = MIT_FILE_TEXT + ("\nCommons Clause: the Licensor grants no right to Sell "
                                "the Software.\n")
        ident, why = gen.license_terms(text)
        self.assertIsNone(ident, "MIT plus a no-sale rider was recognized as MIT")
        self.assertIn("plus terms MIT does not carry", why)

    def test_a_non_commercial_restriction_spliced_into_the_grant_is_not_mit(self):
        text = mutate(MIT_FILE_TEXT, "without restriction,",
                      "without restriction for non-commercial purposes only,")
        self.assertIsNone(gen.license_terms(text)[0])

    def test_an_indemnity_appended_to_the_disclaimer_is_not_mit(self):
        text = MIT_FILE_TEXT.rstrip() + (" LICENSEE SHALL INDEMNIFY THE AUTHORS AGAINST "
                                         "ALL CLAIMS ARISING FROM ITS USE.\n")
        self.assertIsNone(gen.license_terms(text)[0])

    def test_additional_terms_appended_are_not_mit(self):
        text = MIT_FILE_TEXT + "\nADDITIONAL TERMS: Licensee may not redistribute.\n"
        self.assertIsNone(gen.license_terms(text)[0])

    # --- the same document, dressed differently: these ARE MIT ----------------
    def test_a_markdown_heading_over_mit_is_still_mit(self):
        self.assertEqual(gen.license_terms("# MIT License\n\n" + MIT_BODY_TEXT)[0], "MIT")

    def test_an_spdx_tag_line_over_mit_is_still_mit(self):
        text = "SPDX-License-Identifier: MIT\n\nCopyright (c) 2026 X\n\n" + MIT_BODY_TEXT
        self.assertEqual(gen.license_terms(text)[0], "MIT")

    def test_a_byte_order_mark_does_not_change_the_terms(self):
        self.assertEqual(gen.license_terms("﻿" + MIT_FILE_TEXT)[0], "MIT")

    def test_an_unexplained_preamble_is_refused_by_its_own_reason(self):
        # Still refused, and that is right: nobody can vouch for a sentence sitting
        # above a grant. What changed is the SENTENCE. Reporting "carries terms this
        # generator does not recognize" about verbatim MIT sends the reader to the
        # wrong place, which is the same wrong-cause defect as calling an undecodable
        # file unrecognized.
        ident, why = gen.license_terms("Skill bundle terms\n\n" + MIT_BODY_TEXT)
        self.assertIsNone(ident)
        self.assertIn("above it", why)
        self.assertNotIn("does not recognize", why)


class TestTheRecognizerReadsLicenseTextNotMentions(unittest.TestCase):
    """`search` for a license title answers about any sentence that names it."""

    def test_a_denial_of_apache_is_not_apache(self):
        text = "This software is NOT licensed under the Apache License, Version 2.0.\n"
        self.assertIsNone(gen.license_terms(text)[0],
                          "a sentence denying Apache was read as granting it")

    def test_the_full_apache_text_resolves(self):
        self.assertEqual(gen.license_terms(APACHE_FULL_TEXT)[0], "Apache-2.0")

    def test_an_apache_header_alone_is_not_the_apache_license(self):
        # Eight lines of a two-hundred-line license. Recognizing it named a package
        # after a document that was never read past its first section heading.
        ident, why = gen.license_terms(APACHE_HEAD_TEXT)
        self.assertIsNone(ident)
        self.assertIn("Apache-2.0", why)

    def test_a_dual_license_expression_is_refused_not_halved(self):
        ident, why = gen.license_terms("SPDX-License-Identifier: Apache-2.0 OR MIT\n")
        self.assertIsNone(ident, "one side of a dual license was picked, dropping the other")
        self.assertIn("ONE identifier", why)

    def test_a_grant_notice_naming_gpl_is_not_the_gpl_text(self):
        text = ("GNU GENERAL PUBLIC LICENSE Version 3 or any later version applies to "
                "this work.\n")
        self.assertIsNone(gen.license_terms(text)[0],
                          "a notice granting 'or later' was flattened to GPL-3.0-only")

    def test_an_spdx_tag_that_contradicts_the_text_is_refused(self):
        text = "SPDX-License-Identifier: Apache-2.0\n\n" + MIT_BODY_TEXT
        ident, why = gen.license_terms(text)
        self.assertIsNone(ident)
        self.assertIn("while its text is MIT", why)


class TestLicenseFileBlindSpots(unittest.TestCase):
    """A name that says LICENSE and holds no readable terms is a question, not a default.

    Every case here USED to write a manifest claiming the repo default, silently,
    because the lookup filtered on is_file() and on an exact three-name list.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-lic-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _dir(self, name):
        d = self.tmp / name
        d.mkdir()
        return d

    def test_a_directory_named_license_is_reported(self):
        d = self._dir("isdir")
        (d / "LICENSE").mkdir()
        ident, why = gen.resolve_license(d)
        self.assertIsNone(ident)
        self.assertIn("is a directory", why)

    def test_a_dangling_symlink_named_license_is_reported(self):
        d = self._dir("dangling")
        os.symlink(str(d / "gone.txt"), d / "LICENSE")
        ident, why = gen.resolve_license(d)
        self.assertIsNone(ident)
        self.assertIn("dangling symlink", why)

    def test_copying_is_read_like_a_license(self):
        d = self._dir("copying")
        (d / "COPYING").write_text(MIT_FILE_TEXT, encoding="utf-8")
        self.assertEqual(gen.resolve_license(d), ("MIT", ""))

    def test_a_license_with_a_suffix_is_read_like_a_license(self):
        d = self._dir("suffixed")
        (d / "LICENSE-MIT").write_text(MIT_FILE_TEXT, encoding="utf-8")
        self.assertEqual(gen.resolve_license(d), ("MIT", ""))

    def test_a_second_license_file_is_opened_too(self):
        # MIT first by preference order, foreign terms in the file the old lookup
        # never opened. Preference order decided the answer; now both are read.
        d = self._dir("second")
        (d / "LICENSE").write_text(MIT_FILE_TEXT, encoding="utf-8")
        (d / "LICENSE.md").write_text("Vendor Developer Terms govern this material.\n",
                                      encoding="utf-8")
        ident, why = gen.resolve_license(d)
        self.assertIsNone(ident, "the second license file was never opened")
        self.assertIn("LICENSE.md", why)

    def test_two_recognized_licenses_that_disagree_say_so(self):
        d = self._dir("disagree")
        (d / "LICENSE").write_text(MIT_FILE_TEXT, encoding="utf-8")
        (d / "LICENSE-APACHE").write_text(APACHE_FULL_TEXT, encoding="utf-8")
        ident, why = gen.resolve_license(d)
        self.assertIsNone(ident)
        self.assertIn("disagree", why)
        self.assertIn("MIT", why)
        self.assertIn("Apache-2.0", why)

    def test_a_utf16_license_reports_the_decoding_not_the_terms(self):
        # The wrong-cause class: "does not recognize the terms" about a file nobody
        # could decode sends whoever fixes it to read a document that is not text.
        d = self._dir("utf16")
        (d / "LICENSE").write_bytes(MIT_FILE_TEXT.encode("utf-16"))
        ident, why = gen.resolve_license(d)
        self.assertIsNone(ident)
        self.assertIn("not readable text", why)
        self.assertNotIn("does not recognize", why)

    def test_a_latin1_license_reports_the_decoding_not_the_terms(self):
        d = self._dir("latin1")
        (d / "LICENSE").write_bytes("Copyright © 2026\n".encode("latin-1")
                                    + MIT_BODY_TEXT.encode("utf-8"))
        ident, why = gen.resolve_license(d)
        self.assertIsNone(ident)
        self.assertIn("not valid UTF-8", why)

    def test_a_crlf_license_is_the_same_document(self):
        """The end-to-end shape, and it anchors NOTHING on its own.

        `read_license` normalizes CRLF, and `_Doc` splits with `str.splitlines`, which
        already treats \r\n, \r and \n alike. Reverting the normalization leaves this
        assertion GREEN because the second mechanism covers for the first, so the
        contract is asserted at the function boundary below, where only one mechanism
        can answer.
        """
        d = self._dir("crlf")
        (d / "LICENSE").write_bytes(mutate(MIT_FILE_TEXT, "\n", "\r\n").encode("utf-8"))
        self.assertEqual(gen.resolve_license(d), ("MIT", ""))

    def test_read_license_strips_a_utf8_bom(self):
        # The same shape as the CRLF defect: `utf-8-sig` is belt-and-braces because
        # U+FEFF is in `_TRANSLATE` and the recognizer answers MIT either way, so an
        # end-to-end test cannot see it. Measured: decoding the same bytes as plain
        # utf-8 also yields MIT. The contract is asserted where only one mechanism can
        # answer, exactly as for CRLF.
        d = self._dir("bom")
        (d / "LICENSE").write_bytes(b"\xef\xbb\xbf" + MIT_FILE_TEXT.encode("utf-8"))
        text = gen.read_license(d / "LICENSE")
        self.assertFalse(text.startswith("\ufeff"), "read_license leaked a BOM")
        self.assertTrue(text.startswith("MIT License"))

    def test_the_nul_check_names_utf16_rather_than_unrecognized_terms(self):
        # UTF-16LE with no BOM decodes as neither utf-8 nor text, and the CAUSE has to
        # say so: "does not recognize the terms" would send a reader to study a document
        # nobody could decode. Reverting the NUL check leaves a refusal, so the refusal
        # is not what this anchors; the sentence is.
        d = self._dir("utf16")
        (d / "LICENSE").write_bytes(MIT_FILE_TEXT.encode("utf-16-le"))
        with self.assertRaises(gen.LicenseUndecodable) as caught:
            gen.read_license(d / "LICENSE")
        self.assertIn("NUL", str(caught.exception))
        self.assertIn("UTF-16", str(caught.exception))

    def test_read_license_returns_lf_only(self):
        # The contract `read_license` actually promises: bytes in, LF-normalized text
        # out. Every consumer downstream is free to assume it, and a future one that
        # does not go through splitlines (a regex with a `$` anchor, a byte offset in a
        # refusal message) would be the first to notice it was gone.
        d = self._dir("crlf-contract")
        for name, raw in (("LICENSE", b"a\r\nb\r\nc"), ("LICENSE.txt", b"a\rb\rc")):
            (d / name).write_bytes(raw)
            text = gen.read_license(d / name)
            self.assertNotIn("\r", text, f"{name}: read_license leaked a CR")
            self.assertEqual(text, "a\nb\nc")

    def test_no_license_file_at_all_is_the_only_road_to_a_default(self):
        self.assertEqual(gen.resolve_license(self._dir("bare")), (None, ""))


class TestEveryFixtureEditGoesThroughMutate(unittest.TestCase):
    """`mutate()` exists because three fixture edits in this module matched nothing and
    the tests then asserted that verbatim MIT is MIT, passing against the code they were
    written to catch. Vacuity is invisible by construction, a no-op edit leaves a valid
    license and a valid license passes, so the guard cannot be another assertion about
    behaviour: it reads the source.

    THE POLARITY IS THE POINT. The first version listed the bad routes (a bare
    `.replace`, a chained one) and a reviewer immediately named ten more it missed: an
    alias, `str.replace(FIXTURE, ...)`, `re.sub`, a helper, a slice, an f-string, a
    split/join, `mod.FIXTURE`, a walrus, `getattr`. Enumerating evasions is the exact
    failure this whole module is a repair for. So it is an ALLOW-LIST now: a license
    fixture may be passed to a sanctioned transform, concatenated, or handed to the code
    under test, and ANY other use of it is flagged. A route nobody thought of fails
    CLOSED, which is a test author reading one sentence, not a silent no-op.
    """

    FIXTURES = {"MIT_FILE_TEXT", "MIT_BODY_TEXT", "APACHE_FULL_TEXT", "APACHE_HEAD_TEXT",
                "GPL3_TEXT", "MPL2_TEXT", "AGPL3_TEXT", "BSD3_TEXT"}
    # Transforms that either refuse a no-op or cannot silently produce one.
    SANCTIONED = {"mutate", "cut_before", "cut_after", "one_line"}
    # Methods that READ a fixture rather than edit it. A no-op is not expressible here:
    # `.encode()` changes the type, `.splitlines()` and `.rstrip()` cannot quietly
    # return an unedited document where an edited one was meant, because no marker is
    # being matched. `replace`, `sub`, `format`, `join` and slicing are NOT here, and
    # neither is `split`, which is the vacuous cut that `cut_before`/`cut_after` exist
    # to refuse.
    READ_ONLY_METHODS = {"encode", "splitlines", "rstrip", "lstrip", "strip", "count",
                         "startswith", "endswith", "find", "index", "upper", "lower"}

    def test_a_license_fixture_is_only_ever_edited_through_a_sanctioned_transform(self):
        import ast
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        parent = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[child] = node
        # An alias is the fixture. `ALIAS = MIT_FILE_TEXT` then `ALIAS.replace(...)` was
        # the first route past this guard, so a name bound directly to a fixture becomes
        # one, to a fixpoint.
        tainted = set(self.FIXTURES)
        for _ in range(8):
            grew = False
            for node in ast.walk(tree):
                if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Name)
                        and node.value.id in tainted):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id not in tainted:
                            tainted.add(tgt.id)
                            grew = True
            if not grew:
                break
        offenders = []
        for node in ast.walk(tree):
            # `mod.MIT_FILE_TEXT` reaches the same string through an attribute, so the
            # attribute name counts as much as the bare name.
            if (isinstance(node, ast.Attribute) and node.attr in tainted
                    and isinstance(node.ctx, ast.Load)):
                up_attr = parent.get(node)
                if isinstance(up_attr, ast.Attribute) and up_attr.attr not in self.READ_ONLY_METHODS:
                    offenders.append(f"line {node.lineno}: reached through "
                                     f"an attribute, then .{up_attr.attr}(...)")
                continue
            if not (isinstance(node, ast.Name) and node.id in tainted
                    and isinstance(node.ctx, ast.Load)):
                continue
            up = parent.get(node)
            if isinstance(up, ast.Call) and up.func is node:
                continue                                   # not a string use
            if isinstance(up, ast.Call) and node in up.args:
                fn = up.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else fn.attr if isinstance(fn, ast.Attribute) else "")
                # A sanctioned transform, an assertion, or the code under test.
                # A helper ON THIS CLASS is not an escape: it lives in the file this
                # test parses, so whatever it does to the fixture is flagged at its own
                # line. Listing helper names one by one was the enumeration treadmill in
                # miniature, and `_ok` was the member that proved it.
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) \
                        and fn.value.id == "self":
                    continue
                if name in self.SANCTIONED or name.startswith("assert") or name in {
                        "license_terms", "mit_diagnosis", "is_verbatim_mit", "spdx_of",
                        "read_license", "write_text", "write_bytes", "encode", "len",
                        "describe", "resolve_license", "dumps"}:
                    continue
                offenders.append(f"line {node.lineno}: passed to {name or '?'}()")
                continue
            if isinstance(up, ast.Attribute):
                if up.attr in self.READ_ONLY_METHODS:
                    continue
                offenders.append(f"line {node.lineno}: {node.id}.{up.attr}(...)")
                continue
            if isinstance(up, ast.Subscript):
                offenders.append(f"line {node.lineno}: {node.id}[...] slice")
                continue
            if isinstance(up, (ast.JoinedStr, ast.FormattedValue)):
                continue                                   # embedding, same as `+`
            if isinstance(up, (ast.BinOp, ast.keyword, ast.Assign, ast.Compare,
                               ast.Tuple, ast.List, ast.Dict, ast.Return, ast.Expr,
                               ast.Starred, ast.IfExp)):
                continue                                   # concatenation and plumbing
            offenders.append(f"line {node.lineno}: used as {type(up).__name__}")
        # STILL EVADABLE, and said so rather than implied: this reads the source, so
        # `globals()["MIT_FILE_TEXT"]` or a string built at runtime reaches the fixture
        # without a name the parser can follow. It raises the cost of an accidental
        # no-op, which is the failure that actually happened here, not of a determined
        # one, which has not.
        self.assertEqual(offenders, [], "a license fixture reached a transform that can "
                                        "silently produce a no-op; route it through "
                                        "mutate() or cut_before(): " + "; ".join(offenders))


class TestPartialOutput(unittest.TestCase):
    """A run that exits 1 must leave the tree agreeing with the exit code."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-partial-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "skills"
        self.root.mkdir()

    def _skill(self, name, body):
        d = self.root / name
        d.mkdir()
        (d / "SKILL.md").write_text(body, encoding="utf-8")
        return d

    def test_a_failing_run_writes_none_of_the_manifests_it_could_have_written(self):
        # `aaa` sorts before `zzz`, so the loop reached it first and wrote it before
        # ever seeing the skill it could not describe. The report then said the run
        # exited non-zero and nothing was written, while `aaa/skill.json` was on disk.
        ok = self._skill("aaa", "---\nname: aaa\ndescription: fine\n---\n")
        bad = self._skill("zzz", "no front matter, no heading\n")
        rc = gen.main(["--root", str(self.root), "--write", "--default-license", "MIT"])
        self.assertEqual(rc, 1)
        self.assertFalse((bad / "skill.json").exists())
        self.assertFalse((ok / "skill.json").exists(),
                         "a failing run left a manifest on disk for the skills it "
                         "happened to reach first")

    def test_a_clean_run_still_writes_every_manifest(self):
        a = self._skill("aaa", "---\nname: aaa\ndescription: fine\n---\n")
        b = self._skill("zzz", "---\nname: zzz\ndescription: also fine\n---\n")
        rc = gen.main(["--root", str(self.root), "--write", "--default-license", "MIT"])
        self.assertEqual(rc, 0)
        self.assertTrue((a / "skill.json").exists())
        self.assertTrue((b / "skill.json").exists())


class TestUpstreamWithoutLicenseIsVisible(unittest.TestCase):
    """A skill that names an upstream source and ships no license file takes the repo
    default, and the corpus check has no license file to compare against, so it cannot
    see it. Report, never refuse: which of them may carry this repo's terms is a
    human's call, and this only stops the class from being invisible."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-upstream-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "skills"
        self.root.mkdir()

    def _skill(self, name, body):
        d = self.root / name
        d.mkdir()
        (d / "SKILL.md").write_text(body, encoding="utf-8")
        return d

    def test_a_front_matter_source_with_no_license_is_named_in_the_report(self):
        self._skill("borrowed", "---\nname: borrowed\ndescription: d\n"
                                "metadata:\n  source: \"Adapted from upstream/project\"\n---\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gen.main(["--root", str(self.root), "--write", "--default-license", "MIT"])
        out = buf.getvalue()
        self.assertEqual(rc, 0, "the report is a report, not a refusal")
        self.assertIn("[upstream, no LICENSE] borrowed", out)
        self.assertIn("Adapted from upstream/project", out)
        self.assertEqual(json.loads((self.root / "borrowed" / "skill.json")
                                    .read_text(encoding="utf-8"))["license"], "MIT")

    def test_a_prose_adapted_from_line_counts_too(self):
        self._skill("prose", "---\nname: prose\ndescription: d\n---\n"
                             "# Prose\n\nAdapted from upstream/other (see notes).\n")
        self.assertIsNotNone(gen.upstream_source(self.root / "prose"))

    def test_a_skill_that_ships_its_own_license_is_not_in_the_report(self):
        d = self._skill("owned", "---\nname: owned\ndescription: d\n"
                                 "metadata:\n  source: \"upstream/project\"\n---\n")
        (d / "LICENSE").write_text(MIT_FILE_TEXT, encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gen.main(["--root", str(self.root), "--write", "--default-license", "MIT"])
        self.assertNotIn("[upstream, no LICENSE] owned", buf.getvalue())


class TestInRepoManifestLicenses(unittest.TestCase):
    """The corpus itself, not a sandbox: no shipped manifest may claim the repo's own
    license over a third party's terms."""

    def test_the_repo_default_exists(self):
        # Without this the corpus test below passes vacuously: if the default were
        # None, `declared == default` is false for every manifest and the loop
        # certifies a corpus it never compared against anything.
        self.assertIsNotNone(gen.repo_default_license(BRAIN),
                             "the repo's own license could not be established, so every "
                             "comparison below is against nothing")

    def test_no_manifest_claims_the_repo_default_over_foreign_terms(self):
        default = gen.repo_default_license(BRAIN)
        self.assertIsNotNone(default)
        offenders = []
        for manifest in sorted((BRAIN / "skills").glob("*/skill.json")):
            derived, problem = gen.resolve_license(manifest.parent)
            declared = json.loads(manifest.read_text(encoding="utf-8"))["license"]
            if problem:
                # Present and unanswerable. Only a hand-written value may stand here,
                # and the repo default is exactly what may not.
                if declared == default:
                    offenders.append(f"{manifest.parent.name} claims {declared} while "
                                     f"{problem}")
            elif derived is None:
                # No license file. The skill's own front matter may still declare one,
                # and a declaration is a claim to honour rather than to overwrite: a
                # skill saying `license: Apache-2.0` handed the repo default in silence
                # is the exact defect this cycle closed.
                own = gen.declared_license(manifest.parent)[0]
                if declared != (own or default):
                    offenders.append(f"{manifest.parent.name} declares {declared} with "
                                     f"no license file, so it should carry "
                                     f"{own or default}")
            elif declared != derived:
                offenders.append(f"{manifest.parent.name} declares {declared}, its "
                                 f"license file says {derived}")
        self.assertEqual(offenders, [])

    def test_the_upstream_report_over_the_real_corpus_is_self_consistent(self):
        # Not a verdict on any skill. Every name it prints must really carry an
        # upstream marker and really have no license file, and the report must not be
        # empty on a corpus that has both: an empty report would be the invisibility
        # this exists to end.
        listed = [d.name for d in sorted((BRAIN / "skills").iterdir())
                  if d.is_dir() and (d / "SKILL.md").is_file()
                  and gen.upstream_source(d) and not gen.license_entries(d)]
        self.assertTrue(listed, "no skill declares an upstream source without a license "
                                "file; if that is true the report is correct, but check "
                                "the detector before believing it")
        for name in listed:
            d = BRAIN / "skills" / name
            self.assertIsNotNone(gen.upstream_source(d))
            self.assertEqual(gen.license_entries(d), [])



# --- QA cycle 3: the recognizer half -------------------------------------------
SAMPLES = BRAIN / "scripts" / "tests" / "license-samples"
GPL3_TEXT = (SAMPLES / "GPL-3.0.txt").read_text(encoding="utf-8")
MPL2_TEXT = (SAMPLES / "MPL-2.0.txt").read_text(encoding="utf-8")
AGPL3_TEXT = (SAMPLES / "AGPL-3.0.txt").read_text(encoding="utf-8")
BSD3_TEXT = """Copyright (c) 2026 Example Holder
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
COMMONS_CLAUSE = """

"Commons Clause" License Condition v1.0

Without limiting other conditions in the License, the grant of rights under the
License will not include, and the License does not grant to you, the right to
Sell the Software.
"""


class TestTypographyIsNotTerms(unittest.TestCase):
    """A quote glyph is not a term, and a refusal that says otherwise is wrong twice.

    Comparing raw text refused real MIT files over a glyph and told them a cause that
    was not the difference: a family of packages that writes 'Software' with apostrophes
    was told its "grant sentence is not MIT's". Each case below is a real shape found on
    a developer disk, and each one is its own control: the fixture is verbatim MIT with
    one typographic edit, so a case that fails says the edit changed the terms.
    Deliberately no corpus percentage: the denominator is a live disk, it moved between
    runs of the same selection, and a number nobody can re-derive is not evidence.
    Every count that survives anywhere in this repo is either a property of the code
    (template shapes, memo hits) or a git fact (a commit, a date, a file list at a
    ref), which are the two kinds a reader can check.
    """

    def _mit(self, body):
        ident, why = gen.license_terms(body)
        self.assertEqual(ident, "MIT", f"refused real MIT: {why}")

    def test_single_quoted_software_is_the_jshttp_family(self):
        self._mit(mutate(mutate(MIT_FILE_TEXT, '"Software"', "'Software'"),
                         '"AS IS"', "'AS IS'"))

    def test_emphasis_markers_around_as_is(self):
        self._mit(mutate(MIT_FILE_TEXT, '"AS IS"', "*AS IS*"))

    def test_curly_quotes(self):
        self._mit(mutate(mutate(MIT_FILE_TEXT, '"Software"', "\u201cSoftware\u201d"),
                         '"AS IS"', "\u201cAS IS\u201d"))

    def test_noninfringement_spelled_with_the_hyphen(self):
        self._mit(mutate(MIT_FILE_TEXT, "NONINFRINGEMENT", "NON-INFRINGEMENT"))

    def test_the_holder_named_inside_the_disclaimer(self):
        # The SPDX MIT template marks the holder as a variable exactly here.
        self._mit(mutate(one_line(MIT_FILE_TEXT),
                         "THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE",
                         "ACME CORPORATION BE LIABLE"))

    def test_wrapped_onto_the_word_copyright(self):
        # "COPYRIGHT HOLDERS BE LIABLE ..." opens a line with the same word a notice
        # does. Treating it as a preamble deleted a clause out of the disclaimer and
        # then refused the file for not carrying the clause that had been deleted.
        wrapped = mutate(one_line(MIT_FILE_TEXT),
                         "IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE",
                         "IN NO EVENT SHALL THE AUTHORS OR\nCOPYRIGHT HOLDERS BE LIABLE")
        self._mit(wrapped)

    def test_the_whole_license_inside_a_c_comment(self):
        body = "/*\n" + "\n".join(" * " + ln for ln in MIT_FILE_TEXT.splitlines()) + "\n */\n"
        self._mit(body)

    def test_a_hash_comment_wrapper(self):
        self._mit("\n".join("# " + ln for ln in MIT_FILE_TEXT.splitlines()))

    def test_a_markdown_license_heading(self):
        self._mit("# License\n\n" + MIT_FILE_TEXT)

    def test_the_parenthesised_title(self):
        self._mit("(The MIT License)\n\n" + MIT_FILE_TEXT)

    def test_the_expat_title(self):
        self._mit("Expat License\n\n" + MIT_FILE_TEXT)

    def test_an_rst_underline_under_the_title(self):
        self._mit("License\n=======\n\n" + MIT_FILE_TEXT)

    def test_a_copyright_sign_with_no_keyword(self):
        self._mit("\u00a9 2024 Example Holder\n\n" + MIT_FILE_TEXT)

    def test_a_parenthesised_c_with_no_keyword(self):
        self._mit("(c) 2024 Example Holder\n\n" + MIT_FILE_TEXT)

    def test_a_copyright_line_with_no_year(self):
        self._mit("Copyright Steven Loria and contributors\n\n" + MIT_FILE_TEXT)

    def test_a_copyright_keyword_inside_a_sentence(self):
        self._mit("Shellfloat is copyright (c) 2020 by Michael Wood.\n\n" + MIT_FILE_TEXT)

    def test_a_holder_continuation_line(self):
        self._mit("Copyright (c) 1998-2000 Thai Open Source Software Center Ltd\n"
                  "and Clark Cooper\n\n" + MIT_FILE_TEXT)

    def test_an_indented_holder_list(self):
        self._mit("Copyright (c) 2011-2014\n"
                  "    Alice Smith <alice@example.com>\n"
                  "    Bob Jones <bob@example.com>\n\n" + MIT_FILE_TEXT)

    def test_an_spdx_footer(self):
        self._mit(MIT_FILE_TEXT + "\n\nSPDX-License-Identifier: MIT\n")

    def test_a_signature_block(self):
        self._mit(MIT_FILE_TEXT + "\n\nAlice Smith <alice@example.com>\n")

    def test_a_trailing_horizontal_rule(self):
        self._mit(MIT_FILE_TEXT + "\n\n---\n")

    def test_a_bare_url_line(self):
        self._mit(MIT_FILE_TEXT + "\n\nhttps://example.com/license\n")


class TestARefusalNamesTheActualDifference(unittest.TestCase):
    """"Carries its cause" was this cycle's promise, and a misdiagnosis breaks it.

    The refusal quotes the word the license has, the word the file has, and the line
    they sit on, so whoever fixes it reads the sentence that differs rather than the
    whole file.
    """

    def _why(self, body):
        ident, why = gen.license_terms(body)
        self.assertIsNone(ident)
        return why

    def test_a_changed_verb_is_named_word_for_word(self):
        # "to deal WITH the Software" is a real MIT-lookalike family on disk.
        why = self._why(mutate(one_line(MIT_FILE_TEXT), "to deal in the Software",
                              "to deal with the Software"))
        self.assertIn("'in'", why)
        self.assertIn("'with'", why)

    def test_a_dropped_sublicense_right_is_named(self):
        # The openssh/ISC-style variant grants no sublicense right. That IS a different
        # grant, and the refusal has to say which word carries the difference.
        why = self._why(mutate(one_line(MIT_FILE_TEXT),
                        "distribute, sublicense, and/or sell", "distribute, and/or sell"))
        self.assertIn("'sublicense'", why)

    def test_the_refusal_quotes_the_line_it_found(self):
        why = self._why(mutate(MIT_FILE_TEXT, "MERCHANTABILITY", "SALEABILITY"))
        self.assertIn("'merchantability'", why)
        self.assertIn("'saleability'", why)

    def test_a_slot_does_not_swallow_a_later_difference(self):
        # The holder slot used to answer "names no copyright holder" for any failure
        # downstream of it, which is what 400 verbatim-MIT files were told. The
        # DEEPEST failure is the true one.
        why = self._why(mutate(one_line(MIT_FILE_TEXT),
                        "OTHER DEALINGS IN THE SOFTWARE", "OTHER DEALINGS IN THE PRODUCT"))
        self.assertNotIn("names no copyright holder", why)
        self.assertIn("'product'", why)

    def test_a_slot_may_not_carry_terms(self):
        # A variable-width hole in a template is a way to smuggle a restriction into
        # the middle of a license, so a slot admits names and numbering, never terms.
        why = self._why(mutate(one_line(MIT_FILE_TEXT), "IN NO EVENT SHALL THE AUTHORS",
                        "IN NO EVENT SHALL, EXCEPT WHERE COMMERCIAL USE IS PROHIBITED, "
                        "THE AUTHORS"))
        self.assertTrue(why)


class TestEveryRecognizerIsWholeDocument(unittest.TestCase):
    """"A license is recognized whole, or it is not recognized" was true for MIT only.

    The other five keyed on markers found anywhere in the file, so a Commons Clause
    appended to Apache-2.0, a negation written above it, an advertising clause added to
    BSD-3-Clause and a notices file holding several licenses at once all came back with
    one clean SPDX id. Each case below is one edit from a control that must still pass.
    """

    def _refused(self, body, must_mention=""):
        ident, why = gen.license_terms(body)
        self.assertIsNone(ident, f"recognized as {ident}")
        if must_mention:
            self.assertIn(must_mention, why)
        return why

    def test_the_controls_still_resolve(self):
        self.assertEqual(gen.license_terms(APACHE_FULL_TEXT)[0], "Apache-2.0")
        self.assertEqual(gen.license_terms(GPL3_TEXT)[0], "GPL-3.0-only")
        self.assertEqual(gen.license_terms(AGPL3_TEXT)[0], "AGPL-3.0-only")
        self.assertEqual(gen.license_terms(MPL2_TEXT)[0], "MPL-2.0")
        self.assertEqual(gen.license_terms(BSD3_TEXT)[0], "BSD-3-Clause")
        self.assertEqual(gen.license_terms(MIT_FILE_TEXT)[0], "MIT")

    def test_apache_with_a_commons_clause_appended(self):
        self._refused(APACHE_FULL_TEXT + COMMONS_CLAUSE, "Apache-2.0")

    def test_apache_with_additional_terms_appended(self):
        self._refused(APACHE_FULL_TEXT + "\n\nADDITIONAL TERMS: redistribution prohibited.\n")

    def test_a_negation_written_above_apache(self):
        self._refused("This software is NOT licensed under the terms below.\n\n"
                      + APACHE_FULL_TEXT)

    def test_gpl_with_an_appended_commercial_restriction(self):
        self._refused(GPL3_TEXT + "\n\nCommercial use requires a paid license from "
                                  "the author.\n")

    def test_mpl_with_an_appended_restriction(self):
        self._refused(MPL2_TEXT + "\n\nYou may not redistribute this file.\n")

    def test_agpl_with_an_appended_restriction(self):
        # AGPL-3.0 was the sixth recognizer and the only one with no fixture: the
        # sentence "all six read a license whole" was proven for five and asserted for
        # the sixth. Five closed members do not close a class of six.
        self._refused(AGPL3_TEXT + "\n\nADDITIONAL TERMS: no commercial use.\n")

    def test_a_negation_written_above_agpl(self):
        self._refused("This program is NOT under the license below.\n\n" + AGPL3_TEXT)

    def test_agpl_missing_one_of_its_sections_is_not_agpl(self):
        cut = mutate(AGPL3_TEXT, "  2. Basic Permissions.", "  2x. Basic Permissions.")
        self._refused(cut)

    def test_bsd_four_clause_is_not_bsd_three_clause(self):
        bsd4 = mutate(
            BSD3_TEXT,
            "3. Neither the name",
            "3. All advertising materials mentioning features or use of this software\n"
            "   must display the following acknowledgement: This product includes\n"
            "   software developed by the copyright holder.\n\n"
            "4. Neither the name")
        self._refused(bsd4)

    def test_bsd_three_clause_clear_is_not_bsd_three_clause(self):
        clear = mutate(
            BSD3_TEXT,
            "THIS SOFTWARE IS PROVIDED BY",
            "NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE GRANTED\n"
            "BY THIS LICENSE.\n\nTHIS SOFTWARE IS PROVIDED BY")
        self._refused(clear)

    def test_mit_followed_by_apache_is_neither(self):
        self._refused(MIT_FILE_TEXT + "\n\n" + APACHE_FULL_TEXT)

    def test_a_multi_license_notices_file_is_not_one_license(self):
        self._refused("libjpeg-turbo Licenses\n\n" + MIT_FILE_TEXT + "\n\n" + BSD3_TEXT)

    def test_a_friendly_lead_in_is_refused_too_and_that_is_the_price(self):
        # Real files on this machine: archy says "This software is released under the
        # MIT license:", Node.js says "Node.js is licensed for use as follows:", LLVM
        # says "The LLVM Project is under the Apache License v2.0 with LLVM Exceptions".
        # Two of those three are harmless and the third changes the terms, and the text
        # does not say which. Admitting lead-in sentences to stop refusing the first two
        # is the same edit that lets "This software is NOT licensed under the terms
        # below" through, so the refusal stands and a human reads it.
        for lead in ("This software is released under the MIT license:",
                     "Node.js is licensed for use as follows:"):
            self._refused(f"{lead}\n\n{MIT_FILE_TEXT}")
        self._refused("The LLVM Project is under the Apache License v2.0 with LLVM "
                      "Exceptions\n\n" + APACHE_FULL_TEXT)

    def test_apache_that_stops_at_clause_nine_is_still_apache(self):
        # requests, and everything that vendored it, ships this form: no
        # "END OF TERMS AND CONDITIONS" and no appendix. It is a whole license.
        cut = cut_before(APACHE_FULL_TEXT, "END OF TERMS AND CONDITIONS")
        self.assertEqual(gen.license_terms(cut)[0], "Apache-2.0")


class TestTheFilenameEnumerationDecidesAbsent(unittest.TestCase):
    """The list of names IS the definition of "this skill has no license".

    A name that is not on it is not "no license here", it is "not looked for", and both
    used to be written into the manifest as this repo's own terms.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-licnames-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_names_that_hold_terms_are_read(self):
        for name in ("UNLICENSE", "COPYRIGHT", "LICENSE.Apache", "LICENSE.APACHE2",
                     "LICENSE.BSD", "LICENSE.GPL", "LICENSE_APACHE", "APACHE-LICENSE",
                     "GPL-LICENSE.txt", "COPYING.LESSER", "LICENSE.html",
                     "LICENSE.markdown", "LICENSE.adoc"):
            self.assertTrue(gen._is_license_name(name), f"{name} would be read as absent")

    def test_a_notices_file_is_not_this_package_s_license(self):
        # The mirror of the bug above: a file that lists what OTHER people's code is
        # under, read as the skill's own terms.
        for name in ("LICENSE-3RD-PARTY.txt", "THIRD-PARTY-LICENSES",
                     "LICENSE-THIRD-PARTY.txt", "NOTICES-THIRD-PARTY.md"):
            self.assertFalse(gen._is_license_name(name), f"{name} read as own terms")

    def test_a_file_that_is_not_a_license_document_is_left_alone(self):
        for name in ("license.py", "LICENSE.png", "licenses.json", "readme.md"):
            self.assertFalse(gen._is_license_name(name))

    def test_a_spdx_suffixed_license_is_opened_not_defaulted(self):
        # sniffio ships exactly LICENSE.APACHE2. It used to be absent, and absent is
        # the repo default.
        (self.tmp / "LICENSE.APACHE2").write_text(APACHE_FULL_TEXT, encoding="utf-8")
        self.assertEqual(gen.resolve_license(self.tmp), ("Apache-2.0", ""))

    def test_the_reuse_licenses_directory_is_read(self):
        d = self.tmp / "LICENSES"
        d.mkdir()
        (d / "Apache-2.0.txt").write_text(APACHE_FULL_TEXT, encoding="utf-8")
        self.assertEqual(gen.resolve_license(self.tmp), ("Apache-2.0", ""))

    def test_a_notices_file_beside_a_license_does_not_decide(self):
        (self.tmp / "LICENSE").write_text(MIT_FILE_TEXT, encoding="utf-8")
        (self.tmp / "LICENSE-3RD-PARTY.txt").write_text(APACHE_FULL_TEXT, encoding="utf-8")
        self.assertEqual(gen.resolve_license(self.tmp), ("MIT", ""))

    def test_the_gnu_and_plural_shapes_the_extension_allow_list_missed(self):
        # Measured on a developer's disk (`find $HOME /usr/lib/python3 /usr/share/doc
        # -xdev`): COPYING.LIB is 195 copies, four times the COPYING.LESSER the
        # previous revision did cover. Closing one member of a class and calling the
        # class closed leaves the COMMONER member open, every time.
        for name in ("COPYING.LIB", "COPYINGv2", "COPYINGv3", "COPYING3",
                     "COPYING.LESSERv2", "COPYING.LESSERv3", "COPYING.LGPLv2.1",
                     "LICENSES-en.txt", "license.terms", "License.rtf",
                     "LicenseRef-KDE-Accepted-LGPL.txt"):
            self.assertTrue(gen._is_license_name(name),
                            f"{name} would be read as absent, and absent is the default")

    def test_the_extension_test_only_excludes_it_never_admits(self):
        # The polarity IS the fix. An extension nobody enumerated has to fail toward
        # being READ (and then recognized or refused), because failing toward absent is
        # a silent legal claim while failing toward read is a human being asked.
        self.assertTrue(gen._is_license_name("LICENSE.zzz"))
        self.assertTrue(gen._is_license_name("COPYING.some-new-convention"))
        self.assertFalse(gen._is_license_name("license.py"))
        self.assertFalse(gen._is_license_name("LICENSE.woff2"))

    def test_a_gnu_copying_lib_holding_terms_is_opened_not_defaulted(self):
        (self.tmp / "COPYING.LIB").write_text(APACHE_FULL_TEXT, encoding="utf-8")
        self.assertEqual(gen.resolve_license(self.tmp), ("Apache-2.0", ""))

    def test_the_reuse_directory_itself_is_not_a_document(self):
        # `LICENSES` became a recognizable NAME when the plural stem was added, and a
        # directory holds no terms, so the whole REUSE layout answered with the refusal
        # meant for a `LICENSE` that is a directory. The container is not the document.
        d = self.tmp / "LICENSES"
        d.mkdir()
        (d / "Apache-2.0.txt").write_text(APACHE_FULL_TEXT, encoding="utf-8")
        self.assertEqual(gen.resolve_license(self.tmp), ("Apache-2.0", ""))

    def test_a_license_that_is_a_directory_is_still_a_refusal(self):
        # The other side of the same edit: `LICENSE` singular promises one document.
        (self.tmp / "LICENSE").mkdir()
        ident, problem = gen.resolve_license(self.tmp)
        self.assertIsNone(ident)
        self.assertIn("directory", problem)


COMMONS_CLAUSE_BODY = (
    "The Software is provided to you by the Licensor under the License, as defined "
    "below, subject to the following condition. Without limiting other conditions in "
    "the License, the grant of rights under the License will not include, and the "
    "License does not grant to you, the right to Sell the Software.")


class TestAShapeIsNotALicenceToSkipTheContent(unittest.TestCase):
    """`_LINK_DEF_LINE`, `_SPDX_LINE` and `_BARE_URL_LINE` dropped a line on its SHAPE,
    and `_Doc` drops an ornament line before any recognizer runs, so their content was
    never read by anything. A whole Commons Clause pasted into a link label or after an
    `SPDX-FileCopyrightText:` key was invisible to all six recognizers while the SAME
    TEXT unwrapped was refused. The control is what makes it a finding.
    """

    def _refused(self, body):
        ident, why = gen.license_terms(body)
        self.assertIsNone(ident, f"recognized as {ident}")

    def _ok(self, body, want):
        self.assertEqual(gen.license_terms(body)[0], want)

    def test_the_control_the_same_text_unwrapped(self):
        self._refused(MIT_FILE_TEXT + "\n" + COMMONS_CLAUSE_BODY + "\n")

    def test_terms_hidden_in_a_markdown_link_label(self):
        self._refused(MIT_FILE_TEXT + f"\n[{COMMONS_CLAUSE_BODY}]: https://acme.example/cc\n")
        self._refused(APACHE_FULL_TEXT + f"\n[{COMMONS_CLAUSE_BODY}]: https://acme.example/cc\n")

    def test_terms_hidden_after_an_spdx_key(self):
        self._refused(MIT_FILE_TEXT + f"\nSPDX-FileCopyrightText: {COMMONS_CLAUSE_BODY}\n")

    def test_the_legitimate_forms_still_pass(self):
        self._ok("SPDX-License-Identifier: MIT\n\n" + MIT_FILE_TEXT, "MIT")
        self._ok("SPDX-FileCopyrightText: Copyright 2020 Acme\n\n" + MIT_FILE_TEXT, "MIT")
        self._ok(MIT_FILE_TEXT + "\n[others]: https://example.com/contributors\n", "MIT")
        self._ok(APACHE_FULL_TEXT, "Apache-2.0")   # ships its own bare URL line

    def test_a_url_line_is_read_like_every_other_line(self):
        """This hole shipped on an UNMEASURED sentence: that vetoing a URL line
        "would refuse the `http://www.apache.org/licenses/` line Apache-2.0 itself
        ships". The plural `licenses` is not in the vocabulary, so it scores nothing,
        and all six licenses resolve with the veto on. A residual justified by a
        sentence nobody checked is this module's own failure mode, applied to itself.
        """
        for path in ("no-commercial-use-permitted",
                     "license-terms/non-commercial-only-expires-2026",
                     "terms/redistribution-prohibited"):
            ident, _ = gen.license_terms(f"{MIT_FILE_TEXT}\nhttps://acme.example/{path}\n")
            self.assertIsNone(ident, f"terms spelled into a URL path resolved: {path}")

    def test_the_url_lines_real_licenses_ship(self):
        # A path is read against a NARROW vocabulary, not the full one: segmenting
        # `gnu.org/licenses/why-not-lgpl.html` yields "not", which is a terms word,
        # and the full vocabulary refused the GPL's own trailing link.
        for url in ("http://www.apache.org/licenses/", "https://www.gnu.org/licenses/",
                    "https://opensource.org/licenses/MIT",
                    "https://www.gnu.org/licenses/why-not-lgpl.html"):
            self._ok(f"{MIT_FILE_TEXT}\n{url}\n", "MIT")
        for text, want in ((APACHE_FULL_TEXT, "Apache-2.0"), (GPL3_TEXT, "GPL-3.0-only"),
                           (MPL2_TEXT, "MPL-2.0"), (AGPL3_TEXT, "AGPL-3.0-only"),
                           (BSD3_TEXT, "BSD-3-Clause")):
            self._ok(text, want)

    def test_what_actually_remains_is_following_the_link(self):
        # STATED: the module does not fetch, so terms living at the other end of an
        # ordinary-looking URL are outside what it can see.
        self._ok(f"{MIT_FILE_TEXT}\nhttps://acme.example/terms.html\n", "MIT")

    def test_a_line_in_letters_this_module_cannot_read(self):
        """`_WORD` is `[0-9]+|[a-z]+`, so a line in Greek, Cyrillic, Chinese,
        fullwidth or mathematical-bold letters contributed NO words, and
        `outside_is_ornament` walks the word stream, so it was unreachable by every
        check. A third ornament shape, and this one is a whole alphabet."""
        for line in ("\u0391\u03c0\u03b1\u03b3\u03bf\u03c1\u03b5\u03cd\u03b5\u03c4\u03b1\u03b9 \u03b7 "
                     "\u03b5\u03bc\u03c0\u03bf\u03c1\u03b9\u03ba\u03ae \u03c7\u03c1\u03ae\u03c3\u03b7.",
                     "\uff2e\uff2f\uff2e\uff0d\uff23\uff2f\uff2d\uff2d\uff25\uff32\uff23\uff29\uff21\uff2c",
                     "\u4ec5\u9650\u975e\u5546\u4e1a\u4f7f\u7528",
                     "\u0422\u043e\u043b\u044c\u043a\u043e \u043d\u0435\u043a\u043e\u043c\u043c\u0435\u0440\u0447\u0435\u0441\u043a\u043e\u0435"):
            ident, why = gen.license_terms(f"{MIT_FILE_TEXT}\n{line}\n")
            self.assertIsNone(ident, f"unreadable script resolved: {line[:20]}")
            self.assertIn("cannot read", why)

    def test_rules_and_blanks_are_still_ornament(self):
        self._ok(f"{MIT_FILE_TEXT}\n---\n\n===\n\n***\n", "MIT")


class TestUnfenceIsLinear(unittest.TestCase):
    """`_unfence` stripped ONE fence glyph per pass and re-scanned the whole line, so
    a line of `"* " * n` cost O(n^2): 4.9s at n=4000 and a 64 KB single-line LICENSE
    that did not finish in ten minutes. A list of bullets is not an attack, it is a
    markdown file, so that was unbounded work reachable from ordinary input.

    Two mechanisms answer and each is sufficient on its own, so this asserts BOTH
    directly rather than pretending a single revert can be caught by a timing test.
    """

    def test_the_head_pattern_consumes_a_whole_run_in_one_match(self):
        # Mechanism one, asserted as a property of the pattern rather than a clock.
        self.assertEqual(gen._FENCE_HEAD.match("* " * 50).end(), 100)
        self.assertEqual(gen._FENCE_HEAD.match("// " * 30).end(), 90)

    def test_the_loop_is_capped(self):
        # Mechanism two. A fixpoint loop over a shrinking string terminates, so the
        # cap is not about termination: it bounds the WORK when a future head pattern
        # stops matching runs.
        import inspect
        src = inspect.getsource(gen._unfence)
        self.assertIn("for _ in range(", src, "the unfence loop lost its cap")
        self.assertNotIn("while out != prev", src)

    def test_a_pathological_line_is_handled_in_bounded_time(self):
        # The end-to-end fact, which goes red only if BOTH mechanisms are reverted.
        started = time.monotonic()
        gen._unfence("* " * 8000)
        gen.license_terms("* " * 8000 + "\n" + MIT_FILE_TEXT)
        self.assertLess(time.monotonic() - started, 5.0,
                        "a 16k-glyph fence line took seconds; _unfence is quadratic again")

    def test_fences_are_still_stripped(self):
        self.assertEqual(gen._unfence(" * Copyright 2020 Acme"), "Copyright 2020 Acme")
        self.assertEqual(gen._unfence("/* MIT */"), "MIT")
        self.assertEqual(gen._unfence("// hello"), "hello")
        self.assertEqual(gen._unfence("<!-- x -->"), "x")


class TestATitleIsANameNotAWarning(unittest.TestCase):
    """`modified` was made conditional on `bsd` and its seven siblings were left alone,
    which is the same list-shaped failure one member in. Each of these resolved a
    verbatim MIT body to plain MIT."""

    def _refused(self, title):
        ident, _ = gen.license_terms(mutate(MIT_FILE_TEXT, "MIT License", title))
        self.assertIsNone(ident, f"{title!r} resolved to {ident}")

    def test_every_qualifier_that_only_names_a_bsd_variant(self):
        for title in ("Modified MIT License", "Revised MIT License", "New MIT License",
                      "Simplified MIT License", "Clear MIT License",
                      "MIT Licence (Revised)", "MIT License Version 2", "MIT License v3"):
            self._refused(title)

    def test_a_gnu_title_names_three_licenses_and_contradicts_the_rest(self):
        # `gnu` was REMOVED from the family map on the reasoning that it names three
        # licenses and so cannot contradict any of them. That let "GNU General Public
        # License" sit over a verbatim MIT body and resolve to MIT. It names three, so
        # it contradicts everything that is not one of the three.
        for title in ("GNU General Public License", "General Public License",
                      "GNU License", "Public License"):
            self._refused(title)
        self.assertEqual(gen.license_terms(GPL3_TEXT)[0], "GPL-3.0-only")
        self.assertEqual(gen.license_terms(AGPL3_TEXT)[0], "AGPL-3.0-only")

    def test_two_concrete_names_are_a_dual_license_claim(self):
        # The manifest carries ONE identifier, so a title offering a choice is not a
        # title: picking a side drops the option its author granted.
        self._refused("MIT or Apache License")

    def test_a_title_naming_another_license_contradicts_the_body(self):
        for title in ("Modified BSD License", "Apache License", "Mozilla Public License"):
            self._refused(title)

    def test_a_concrete_name_is_not_widened_by_the_set_valued_words(self):
        # The sibling test above closed ONE member: a title naming only the family of
        # families over a body outside it. The union direction stayed open, and it runs
        # the wrong way: naming a SPECIFIC license widened what the title would accept.
        # `affero` and `lesser` were dragged back up into the whole GNU set, and `public`
        # dragged that set into any title carrying the word, so an MPL or EPL title sat
        # over a GPL body with no problem raised. Measured against the real sample bodies,
        # all five silent:
        #     GNU Affero General Public License over GPL-3.0  -> GPL-3.0-only
        #     GNU Lesser General Public License over GPL-3.0  -> GPL-3.0-only
        #     GNU Lesser General Public License over AGPL-3.0 -> AGPL-3.0-only
        #     Mozilla Public License            over GPL-3.0  -> GPL-3.0-only
        #     Eclipse Public License            over GPL-3.0  -> GPL-3.0-only
        # An AGPL title over a GPL body is a materially different grant; the network
        # clause is the reason AGPL exists.
        for title, body, name in (
                ("GNU Affero General Public License", GPL3_TEXT, "agpl title, gpl body"),
                ("GNU Lesser General Public License", GPL3_TEXT, "lgpl title, gpl body"),
                ("GNU Lesser General Public License", AGPL3_TEXT, "lgpl title, agpl body"),
                ("Mozilla Public License", GPL3_TEXT, "mpl title, gpl body"),
                ("Eclipse Public License", GPL3_TEXT, "epl title, gpl body")):
            spdx, problem = gen.license_terms(f"{title}\n\n{body}")
            self.assertIsNone(spdx, f"{name} resolved to {spdx} instead of refusing")
            self.assertTrue(problem, f"{name} refused with no stated problem")
        # and the legitimate resolves the narrowing could have broken
        self.assertEqual(gen.license_terms(f"GNU General Public License\n\n{GPL3_TEXT}")[0],
                         "GPL-3.0-only")
        self.assertEqual(gen.license_terms(f"GNU General Public License\n\n{AGPL3_TEXT}")[0],
                         "AGPL-3.0-only")
        self.assertEqual(gen.license_terms(f"Mozilla Public License Version 2.0\n\n{MPL2_TEXT}")[0],
                         "MPL-2.0")

    def test_the_published_bsd_names_still_resolve(self):
        for title in ("BSD 3-Clause License", "Modified BSD License", "New BSD License",
                      "Revised BSD License"):
            self.assertEqual(gen.license_terms(f"{title}\n\n{BSD3_TEXT}")[0],
                             "BSD-3-Clause", title)

    def test_the_other_five_still_resolve_under_their_own_titles(self):
        self.assertEqual(gen.license_terms(MIT_FILE_TEXT)[0], "MIT")
        self.assertEqual(gen.license_terms(APACHE_FULL_TEXT)[0], "Apache-2.0")
        self.assertEqual(gen.license_terms(GPL3_TEXT)[0], "GPL-3.0-only")
        self.assertEqual(gen.license_terms(AGPL3_TEXT)[0], "AGPL-3.0-only")
        self.assertEqual(gen.license_terms(MPL2_TEXT)[0], "MPL-2.0")


class TestADeclarationThatExistsIsNotAnAbsentOne(unittest.TestCase):
    """YAML types the value. `license: [MIT]` is a list, `license: 2.0` a float, and
    `license: no` the boolean False because YAML 1.1 reads `no` as a bool. Each was
    measured as "declared nothing", which took the repo default over a field the author
    had filled in: the silent-default class this module closes for files, one level up.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-decl-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _skill(self, decl):
        d = self.tmp / f"s{len(list(self.tmp.iterdir()))}"
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\nname: probe\ndescription: d\n{decl}\n---\n# P\n",
                                    encoding="utf-8")
        return d

    def test_a_typed_declaration_is_refused_not_defaulted(self):
        for decl in ("license: [MIT]", "license: no", "license: 2.0", "license: {}",
                     'license: ""'):
            manifest, problem = gen.describe(self._skill(decl), "MIT")
            self.assertIsNone(manifest, f"{decl!r} took the repo default")
            self.assertIn("not a bare SPDX identifier", problem)

    def test_the_sibling_spelling_in_the_same_holder_is_compared(self):
        # The loop broke at the first spelling, so `license: MIT` beside
        # `licence: Apache-2.0` published MIT and never compared them. Same class as
        # two holders, one level in.
        manifest, problem = gen.describe(
            self._skill("license: MIT\nlicence: Apache-2.0"), "MIT")
        self.assertIsNone(manifest)
        self.assertIn("two different license declarations", problem)

    def test_a_capitalised_key_is_not_an_absent_declaration(self):
        self.assertEqual(
            gen.describe(self._skill("License: Apache-2.0"), "MIT")[0]["license"],
            "Apache-2.0")

    def test_an_identifier_this_generator_cannot_place_is_refused(self):
        # `license: foo-bar` matched the bare-token shape, so it was written into a
        # public manifest as a license and the schema called it valid, because the
        # schema only checks the string is short.
        for decl in ("license: foo-bar", "license: MMIT", "license: Apache-9.9"):
            manifest, problem = gen.describe(self._skill(decl), "MIT")
            self.assertIsNone(manifest, f"{decl!r} was written into a manifest")
            self.assertIn("not an SPDX identifier", problem)
        for decl, want in (("license: NOASSERTION", "NOASSERTION"),
                           ("license: proprietary", "proprietary"),
                           ("license: GPL-3.0", "GPL-3.0-only")):
            self.assertEqual(gen.describe(self._skill(decl), "MIT")[0]["license"], want)

    def test_two_holders_that_disagree_are_compared(self):
        manifest, problem = gen.describe(
            self._skill("license: MIT\nmetadata:\n  license: Apache-2.0"), "MIT")
        self.assertIsNone(manifest)
        self.assertIn("two different license declarations", problem)

    def test_the_controls(self):
        self.assertEqual(gen.describe(self._skill("license: Apache-2.0"), "MIT")[0]["license"],
                         "Apache-2.0")
        self.assertEqual(gen.describe(self._skill("license: MIT\nmetadata:\n  license: MIT"),
                                      "MIT")[0]["license"], "MIT")
        self.assertEqual(gen.describe(self._skill("# nothing"), "MIT")[0]["license"], "MIT")


class TestEveryExclusionIsARoadBackToTheDefault(unittest.TestCase):
    """Whatever the name test declines, `resolve_license` used to answer for with the
    same `(None, "")` it uses for an empty directory, and `(None, "")` is the only road
    to the repo default. Five shapes reached MIT in silence that way, each measured.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-setaside-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _skill(self, files, dirs=()):
        d = self.tmp / f"s{len(list(self.tmp.iterdir()))}"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: probe\ndescription: d\n---\n# P\n",
                                    encoding="utf-8")
        for x in dirs:
            (d / x).mkdir(parents=True, exist_ok=True)
        for n, c in files.items():
            f = d / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(c, encoding="utf-8")
        return d

    def _refuses(self, files, dirs=()):
        manifest, problem = gen.describe(self._skill(files, dirs), "MIT")
        self.assertIsNone(manifest, "took the repo default over unread license material")
        return problem

    def test_an_empty_reuse_directory_is_not_an_absent_license(self):
        self.assertIn("LICENSES/", self._refuses({}, dirs=["LICENSES"]))

    def test_a_reuse_directory_holding_only_notices(self):
        self.assertIn("LICENSES/", self._refuses({"LICENSES/THIRD-PARTY.txt": APACHE_FULL_TEXT}))

    def test_a_notices_file_as_the_ONLY_license_named_entry(self):
        # Excluding a notices file BESIDE a real license is right. Excluding the only
        # one in the directory answers the question by not asking it.
        for name in ("LICENSE-EXCEPTIONS", "LICENSE.vendor", "THIRD-PARTY-LICENSE"):
            self.assertIn(name, self._refuses({name: APACHE_FULL_TEXT}))

    def test_a_license_under_a_denied_extension(self):
        for name in ("LICENSE.json", "LICENSE.xml", "license.yml"):
            self.assertIn(name, self._refuses({name: APACHE_FULL_TEXT}))

    def test_a_license_one_directory_down(self):
        self.assertIn("docs/LICENSE.txt", self._refuses({"docs/LICENSE.txt": APACHE_FULL_TEXT}))

    def test_a_backup_copy_is_never_adopted_as_the_terms(self):
        # Worse than a silent default, which is what these used to be measured doing:
        # an editor or patch backup holds what the terms USED to be, and adopting one
        # publishes a superseded license as the current claim.
        for name in ("LICENSE.txt~", "LICENSE.orig", "LICENSE.txt.bak", "LICENSE.old",
                     "LICENSE.rej", "LICENSE.txt.tmp"):
            self.assertIn(name, self._refuses({name: APACHE_FULL_TEXT}))

    def test_a_package_manifest_that_declares_terms_nothing_reads(self):
        for name, body in (("package.json", '{"name":"x","license":"AGPL-3.0"}'),
                           ("pyproject.toml", '[project]\nlicense = "MIT"\n')):
            self.assertIn(name, self._refuses({name: body}))

    def test_a_lone_notice_file(self):
        self.assertIn("NOTICE.txt", self._refuses({"NOTICE.txt": APACHE_FULL_TEXT}))

    def test_provenance_files_are_a_report_and_not_a_refusal(self):
        # `UPSTREAM.md` was measured reaching the default with nothing even reporting
        # it, because only SKILL.md and README.md were read. It is read now, and it is
        # a REPORT: refusing on provenance would turn every attributed skill into a
        # hand-written manifest.
        d = self._skill({"UPSTREAM.md": "Vendored from https://github.com/foo/bar (AGPL-3.0)\n"})
        self.assertEqual(gen.describe(d, "MIT")[0]["license"], "MIT")
        self.assertIn("github.com/foo/bar", gen.upstream_source(d))

    def test_a_backup_beside_a_real_license_does_not_disturb_it(self):
        d = self._skill({"LICENSE": MIT_FILE_TEXT, "LICENSE.orig": APACHE_FULL_TEXT})
        self.assertEqual(gen.describe(d, "MIT")[0]["license"], "MIT")

    def test_the_controls_still_reach_the_default_or_their_own_terms(self):
        d = self._skill({"notes.md": "nothing license-shaped here"})
        self.assertEqual(gen.describe(d, "MIT")[0]["license"], "MIT")
        d = self._skill({"LICENSE": MIT_FILE_TEXT, "LICENSE-3RD-PARTY.txt": APACHE_FULL_TEXT})
        self.assertEqual(gen.describe(d, "MIT")[0]["license"], "MIT")
        d = self._skill({"LICENSE": MIT_FILE_TEXT, "references/LICENSE.txt": APACHE_FULL_TEXT})
        self.assertEqual(gen.describe(d, "MIT")[0]["license"], "MIT")
        d = self._skill({"LICENSES/Apache-2.0.txt": APACHE_FULL_TEXT})
        self.assertEqual(gen.describe(d, "MIT")[0]["license"], "Apache-2.0")


class TestATimeLimitIsTerms(unittest.TestCase):
    """`_name_like` and `_is_copyright_notice` veto a line by VOCABULARY, and a
    vocabulary is an allow-list: a year is an attribution signal, so any short line
    carrying one and no listed word came through as a holder. Every case here was
    measured resolving its document to plain MIT.
    """

    def _refused(self, body):
        ident, why = gen.license_terms(body)
        self.assertIsNone(ident, f"recognized as {ident}")
        return why

    def _mit(self, body):
        ident, why = gen.license_terms(body)
        self.assertEqual(ident, "MIT", f"refused a real holder: {why}")

    def test_a_dated_restriction_floating_over_the_license(self):
        for line in ("Valid until 2026", "Trial ends 2026", "Void After 2026",
                     "Academic Purposes 2024"):
            self._refused(f"{line}\n\n{MIT_FILE_TEXT}")
        self._refused(MIT_FILE_TEXT + "\nExpires 2027-01-01\n")

    def test_the_scope_and_term_phrasings_measured_in_cycle_six(self):
        for holder in ("Copyright 2020 Foo, solely for Acme Inc.",
                       "Copyright 2020 Foo; Expiring 2027",
                       "Copyright 2020 Foo, limited to Acme Inc.",
                       "Copyright 2020 Foo; Ceasing 2027",
                       "Copyright 2020 Foo; Resale Banned",
                       "Copyright 2020 Foo; Resale Barred",
                       "Copyright 2020 Foo; Unsellable",
                       "Copyright 2020 Foo; Unlicensed"):
            self._refused(mutate(MIT_FILE_TEXT, "Copyright (c) 2026 Someone Else, Inc.",
                                 holder))

    def test_a_contact_does_not_buy_a_scoping_line_its_way_in(self):
        # ANY capitalised line of ten words or fewer plus a contact was ornament
        # anywhere, so a restriction bought admission with an address.
        self._refused("Resale Banned <legal@acme.example>\n\n" + MIT_FILE_TEXT)
        self._refused("Enterprise Customers Of Acme <legal@acme.example>\n\n"
                      + MIT_FILE_TEXT)
        self._mit(MIT_FILE_TEXT + "\n\nAlice Smith <alice@example.com>\n")

    def test_a_contact_line_is_read_by_its_PATH_and_not_only_its_words(self):
        """Isolates the contact-path veto, which the tests above cannot see.

        `words()` fuses intra-word hyphens, so `eula-restricted-build` becomes one
        token and the ordinary vocabulary check on a contact-bearing line is
        unreachable for exactly the text a URL can carry. "eula" is the one word in
        `_URL_TERMS` and NOT in `_TERMS_VOCAB`, so only the path split can answer
        here: reverting it leaves every other test green and flips this one.
        """
        self._refused(MIT_FILE_TEXT +
                      "\nDocs <https://acme.example/eula-restricted-build>\n")
        # And the control: the same shape with nothing restrictive in the path.
        self._mit(MIT_FILE_TEXT + "\nDocs <https://acme.example/getting-started>\n")

    def test_a_second_sentence_on_the_copyright_line(self):
        for holder in ("Copyright 2020 Foo. Educational purposes.",
                       "Copyright 2020 Foo. Revoked 2026.",
                       "Copyright 2020 Foo, exclusively for Acme Inc."):
            self._refused(mutate(MIT_FILE_TEXT, "Copyright (c) 2026 Someone Else, Inc.",
                                 holder))

    def test_a_title_that_says_the_terms_were_changed(self):
        # "Modified BSD License" is a published NAME. "Modified MIT License" is a
        # warning, and it sat over verbatim MIT text resolving to plain MIT.
        self._refused(mutate(MIT_FILE_TEXT, "MIT License", "Modified MIT License"))

    def test_real_holders_that_this_must_not_refuse(self):
        # Each was measured being refused by a stricter draft of the same rule (one that
        # required every lower-case word in the notice to be a particle or a corporate
        # form). It refused a large fraction of a disk sweep, a proportion of one
        # machine's $HOME that does not reproduce, and was dropped for these.
        for holder in ("Copyright (c) 2017-present, Jon Schlinkert.",
                       "Copyright (c) 2014, Nathan LaFreniere and other contributors",
                       "Copyright (c) 2012-2018 Aseem Kishore, and [others].",
                       "Copyright 2007, 2008 The Python Markdown Project (v. 1.7 and later)",
                       "Copyright (c) 2026 Alice Smith <alice@example.com>",
                       "Copyright (c) 2026 Alice B. Smith",
                       "Copyright (c) 2026 Acme Inc. and Beta Ltd.",
                       "Copyright (c) 1998-2000 Thai Open Source Software Center Ltd "
                       "and Clark Cooper"):
            self._mit(mutate(MIT_FILE_TEXT, "Copyright (c) 2026 Someone Else, Inc.", holder))

    def test_a_holder_list_under_its_notice_is_still_a_holder_list(self):
        self._mit(mutate(MIT_FILE_TEXT, "Copyright (c) 2026 Someone Else, Inc.",
                         "Copyright (c) 2026 Someone Else, Inc.\n    Acme Inc.\n    Beta Ltd."))

    def test_a_markdown_link_definition_is_a_link_not_terms(self):
        self._mit(MIT_FILE_TEXT + "\n[others]: https://example.com/contributors\n")

    # The two tests below use words that are DELIBERATELY absent from _TERMS_VOCAB
    # ("superseded", "lapses"), because the vocabulary is the mechanism they are not
    # testing. Reverting the vocabulary leaves them green and reverting the structural
    # rule turns them red, which is the only way to tell the two apart: with a listed
    # word, either mechanism answers and neither is proven.

    def test_an_UNLISTED_restriction_floating_over_the_license(self):
        # What the adjacency rule is FOR. Short, capitalised, carrying a year, using a
        # word nobody put in the vocabulary: a holder to every test except "does this
        # line continue a copyright notice".
        for line in ("Lapses 2027", "Superseded 2026"):
            self._refused(f"{line}\n\n{MIT_FILE_TEXT}")

    def test_an_UNLISTED_second_sentence_on_the_copyright_line(self):
        # What the sentence-break rule is FOR, for the same reason.
        self._refused(mutate(MIT_FILE_TEXT, "Copyright (c) 2026 Someone Else, Inc.",
                             "Copyright 2020 Foo. Superseded by v2."))


class TestSpdxTagsCarryWhatOnlyTheyCanCarry(unittest.TestCase):
    """GPL-3.0-or-later and GPL-3.0-only sit over IDENTICAL text. The tag is the only
    carrier of the difference, and refusing it for "contradicting" the body threw away
    the one fact the file had to give."""

    def test_or_later_over_gpl3_text_is_kept(self):
        self.assertEqual(
            gen.license_terms("SPDX-License-Identifier: GPL-3.0-or-later\n" + GPL3_TEXT),
            ("GPL-3.0-or-later", ""))

    def test_a_deprecated_id_is_answered_with_its_replacement(self):
        self.assertEqual(
            gen.license_terms("SPDX-License-Identifier: GPL-3.0\n" + GPL3_TEXT)[0],
            "GPL-3.0-only")

    def test_spdx_ids_are_case_insensitive(self):
        self.assertEqual(
            gen.license_terms("SPDX-License-Identifier: mit\n" + MIT_FILE_TEXT)[0], "MIT")

    def test_a_tag_from_another_family_is_still_refused(self):
        ident, why = gen.license_terms("SPDX-License-Identifier: MIT\n" + APACHE_FULL_TEXT)
        self.assertIsNone(ident)
        self.assertIn("Apache-2.0", why)


class TestFrontMatterLicenseIsRead(unittest.TestCase):
    """Eight skills WROTE `license:` and nothing READ it, so a skill declaring
    Apache-2.0 with no license file was handed the repo default, MIT, in silence."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-fmlic-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "skills"
        self.root.mkdir()

    def _skill(self, name, fm_extra="", license_text=None):
        d = self.root / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n{fm_extra}---\n",
                                    encoding="utf-8")
        if license_text is not None:
            (d / "LICENSE").write_text(license_text, encoding="utf-8")
        return d

    def _run(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gen.main(["--root", str(self.root), "--write", "--default-license", "MIT"])
        return rc, buf.getvalue()

    def test_a_declared_license_with_no_file_is_honoured_not_overwritten(self):
        self._skill("borrowed", "license: Apache-2.0\n")
        rc, out = self._run()
        self.assertEqual(rc, 0, out)
        got = json.loads((self.root / "borrowed" / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(got["license"], "Apache-2.0",
                         "the declaration was overwritten with the repo default")

    def test_a_declaration_that_contradicts_the_license_file_is_refused(self):
        self._skill("liar", "license: Apache-2.0\n", MIT_FILE_TEXT)
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("declares Apache-2.0 while its license file says MIT", out)
        self.assertFalse((self.root / "liar" / "skill.json").exists())

    def test_a_declaration_that_agrees_is_written(self):
        self._skill("honest", "license: Apache-2.0\n", APACHE_FULL_TEXT)
        rc, out = self._run()
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads((self.root / "honest" / "skill.json")
                                    .read_text(encoding="utf-8"))["license"], "Apache-2.0")

    def test_a_declaration_that_is_a_sentence_is_a_question_not_a_parse(self):
        self._skill("prose", 'license: "MIT (author: A. N. Other, preserve attribution)"\n')
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("not a bare SPDX identifier", out)

    def test_metadata_license_counts_too(self):
        self._skill("nested", "metadata:\n  license: Apache-2.0\n")
        self.assertEqual(gen.declared_license(self.root / "nested")[0], "Apache-2.0")

    def test_no_declaration_and_no_file_is_the_only_road_to_the_default(self):
        self._skill("ours")
        rc, out = self._run()
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads((self.root / "ours" / "skill.json")
                                    .read_text(encoding="utf-8"))["license"], "MIT")

    def test_noassertion_is_reported_on_every_run(self):
        self._skill("unresolved", "license: NOASSERTION\n")
        rc, out = self._run()
        self.assertEqual(rc, 0, out)
        self.assertIn("[NOASSERTION] unresolved", out)
        self.assertEqual(json.loads((self.root / "unresolved" / "skill.json")
                                    .read_text(encoding="utf-8"))["license"], "NOASSERTION")


class TestProvenanceMarkersAreWide(unittest.TestCase):
    """Eight manifests claiming this repo's MIT over Cloudflare-authored material were
    invisible to the report whose whole job was to see them, because every one of them
    says where it came from under a `## Retrieval Sources` heading and the detector
    looked for a `Source:` line."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-prov-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _skill(self, body, readme=None):
        d = self.tmp / "s"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()
        (d / "SKILL.md").write_text(body, encoding="utf-8")
        if readme:
            (d / "README.md").write_text(readme, encoding="utf-8")
        return d

    def _found(self, body, readme=None):
        return gen.upstream_source(self._skill(body, readme))

    def test_the_prose_conventions_that_were_missed(self):
        for line in ("Ported from upstream/project.", "Forked from upstream/project.",
                     "Inspired by upstream/project.", "Vendored from upstream/project.",
                     "Original: upstream/project", "Credits: upstream/project",
                     "Sources: upstream/project", "Adapted from upstream/project",
                     "Based on upstream/project"):
            self.assertIsNotNone(self._found(f"---\nname: s\ndescription: d\n---\n\n{line}\n"),
                                 f"missed: {line}")

    def test_a_retrieval_sources_heading_with_a_url(self):
        body = ("---\nname: s\ndescription: d\n---\n\n# S\n\n## Retrieval Sources\n\n"
                "| Source | How to retrieve |\n|---|---|\n"
                "| Docs | https://developers.example.com/agents/ |\n")
        found = self._found(body)
        self.assertIsNotNone(found, "the eight Cloudflare skills say it exactly this way")
        self.assertIn("https://developers.example.com/agents/", found)

    def test_a_source_column_under_an_unrelated_heading_is_not_provenance(self):
        # A skill that triages an inbox tabulates its RUNTIME sources. Reporting those
        # as upstream material buries the report that has to stay readable to be read.
        body = ("---\nname: s\ndescription: d\n---\n\n# S\n\n## Pipeline\n\n"
                "| Source | Fetch endpoint |\n|---|---|\n| Gmail | messages.list |\n")
        self.assertIsNone(self._found(body))

    def test_provenance_in_a_sibling_readme(self):
        self.assertIsNotNone(self._found(
            "---\nname: s\ndescription: d\n---\n\n# S\n",
            readme="# S\n\nAdapted from upstream/project.\n"))

    def test_an_author_line_plus_a_third_party_copyright(self):
        self.assertIsNotNone(self._found(
            "---\nname: s\ndescription: d\n---\n\n# S\n\n"
            "Author: A. N. Other\n\nCopyright (c) 2026 Other Corp\n"))

    def test_a_block_scalar_origin_is_parsed_not_grepped(self):
        # The prose regex ran over raw YAML, so `origin: >-` would hand back ">-" as the
        # source and a list "- https://...". The 48 skills that declare one of these keys
        # all write a plain scalar, so the regex was right by luck, not by reading.
        found = self._found("---\nname: s\ndescription: d\nmetadata:\n"
                            "  origin: >-\n    https://example.com/upstream\n---\n")
        self.assertEqual(found, "https://example.com/upstream")

    def test_a_list_origin_is_parsed(self):
        found = self._found("---\nname: s\ndescription: d\nmetadata:\n"
                            "  origin:\n    - https://example.com/a\n"
                            "    - https://example.com/b\n---\n")
        self.assertIn("https://example.com/a", found)
        self.assertNotIn("- https", found)

    def test_a_source_line_inside_a_code_fence_is_a_template_not_a_claim(self):
        body = ("---\nname: s\ndescription: d\n---\n\n# S\n\n```bash\n"
                "# Source: /etc/profile\nsource /etc/profile\n```\n")
        self.assertIsNone(self._found(body))

    def test_a_cross_reference_is_not_a_source(self):
        body = ("---\nname: s\ndescription: d\n---\n\n# S\n\n"
                "Based on Section 2.7.2 (445 active SPs observed in 1 hour):\n")
        self.assertIsNone(self._found(body))

    def test_a_repo_key_line_is_the_header_a_tool_skill_writes(self):
        # Three skills in this repo carry this and nothing else: a `**Repo**:` line
        # under the title with that tool's own license beside it. `agent-browser` says
        # Apache 2.0 in its prose while its manifest says MIT, and nothing saw it.
        for line in ("**Repo**: https://github.com/upstream/project",
                     "Repo: https://github.com/upstream/project · MIT",
                     "Repository: https://github.com/upstream/project"):
            found = self._found(f"---\nname: s\ndescription: d\n---\n\n# S\n\n{line}\n")
            self.assertIsNotNone(found, f"missed: {line}")
            self.assertIn("upstream/project", found)

    def test_a_repo_line_with_no_external_url_is_not_a_claim(self):
        # Without the URL this marker matches every example command and every local
        # path that happens to say "repo", and it buries the report.
        for line in ("Repo: the arm's own checkout", "**Repo**: ./vendor/thing"):
            self.assertIsNone(self._found(
                f"---\nname: s\ndescription: d\n---\n\n# S\n\n{line}\n"), f"fired on: {line}")


class TestTheShippedManifestsMatchWhatTheGeneratorDerives(unittest.TestCase):
    """The corpus itself. Every shipped manifest must be the one the generator would
    write today, and where the generator refuses, the value standing there may be
    anything a human decided EXCEPT the repo default."""

    def test_every_manifest_agrees_with_the_generator(self):
        default = gen.repo_default_license(BRAIN)
        self.assertIsNotNone(default, "the repo's own license could not be established, "
                                      "so every comparison below is against nothing")
        offenders = []
        for manifest in sorted((BRAIN / "skills").glob("*/skill.json")):
            shipped = json.loads(manifest.read_text(encoding="utf-8"))["license"]
            derived, problem = gen.describe(manifest.parent, default)
            if derived is None:
                if shipped == default:
                    offenders.append(f"{manifest.parent.name} claims the repo default "
                                     f"{shipped} while {problem}")
            elif derived["license"] != shipped:
                offenders.append(f"{manifest.parent.name} ships {shipped}, the generator "
                                 f"derives {derived['license']}")
        self.assertEqual(offenders, [])

    def test_the_third_party_skills_this_repo_decided_no_longer_claim_its_terms(self):
        # The thirteen this cycle answered, plus the seven gsap skills. Each carries
        # its upstream's own license id, and where the upstream ships a license file
        # that file travels with the material as that license requires.
        expected = {
            **{n: "Apache-2.0" for n in ("agents-sdk", "cloudflare",
                                         "cloudflare-email-service", "durable-objects",
                                         "sandbox-sdk", "web-perf",
                                         "workers-best-practices", "wrangler")},
            **{n: "MIT" for n in ("gsap-core", "gsap-frameworks", "gsap-performance",
                                  "gsap-plugins", "gsap-scrolltrigger", "gsap-timeline",
                                  "gsap-utils")},
            **{n: "proprietary" for n in ("figma", "figma-implement-design",
                                          "figma-use")},
            # `sandbox-sdk` was NOASSERTION here on the sentence "this name is NOT
            # present in cloudflare/skills". It is absent from the CURRENT listing
            # because upstream dropped that name on 2026-08-07 (f96bff75), months after
            # the 2026-05-23 bundle. The tree at 60147cbb, the last upstream commit
            # before that bundle, carries skills/sandbox-sdk/SKILL.md, and our copy
            # differs from it only by a locally appended "## See also". Provenance is a
            # question about a date; a listing only ever answers about today.
            **{n: "NOASSERTION" for n in ("orchestrated-planning",
                                          "progressive-code-exploration",
                                          "knowledge-corpus", "project-timeline-report",
                                          "session-memory-search")},
        }
        wrong = []
        for name, want in sorted(expected.items()):
            mf = BRAIN / "skills" / name / "skill.json"
            got = json.loads(mf.read_text(encoding="utf-8"))["license"]
            if got != want:
                wrong.append(f"{name} ships {got}, should ship {want}")
        self.assertEqual(wrong, [])

    def test_the_licenses_those_skills_must_carry_are_actually_there(self):
        # Apache-2.0 and MIT both condition the grant on the license text travelling
        # with the material. A manifest field saying "Apache-2.0" with no license file
        # beside it is a claim, not compliance.
        missing = []
        for name in ("agents-sdk", "cloudflare", "cloudflare-email-service", "sandbox-sdk",
                     "durable-objects", "web-perf", "workers-best-practices", "wrangler",
                     "gsap-core", "gsap-frameworks", "gsap-performance", "gsap-plugins",
                     "gsap-scrolltrigger", "gsap-timeline", "gsap-utils"):
            d = BRAIN / "skills" / name
            derived, problem = gen.resolve_license(d)
            shipped = json.loads((d / "skill.json").read_text(encoding="utf-8"))["license"]
            if derived != shipped:
                missing.append(f"{name}: manifest says {shipped}, its own license file "
                               f"says {derived or problem}")
            if not gen.upstream_source(d):
                missing.append(f"{name}: no provenance line names where it came from")
        self.assertEqual(missing, [])

    def test_every_skill_that_names_an_external_upstream_is_visible_in_the_report(self):
        # Not a verdict on any of them. The generator prints this class on every run
        # precisely because whether this repo's terms may speak for someone else's
        # material is a human's call; what may NOT happen is the question going unasked.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gen.main(["--root", str(BRAIN / "skills")])
        out = buf.getvalue()
        unlisted = []
        for d in sorted((BRAIN / "skills").iterdir()):
            if not d.is_dir() or not (d / "SKILL.md").is_file():
                continue
            src = gen.upstream_source(d)
            if not src or gen.license_entries(d):
                continue
            if not re.search(r"https?://", src):
                continue
            if f"] {d.name}:" not in out:
                unlisted.append(d.name)
        self.assertEqual(unlisted, [], "an external upstream that no report names is "
                                       "the invisibility this exists to end")


if __name__ == "__main__":
    unittest.main()

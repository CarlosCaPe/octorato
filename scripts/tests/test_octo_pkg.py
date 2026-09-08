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
import shutil
import subprocess
import sys
import tempfile
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
# Enough of the Apache 2.0 header that only its real text carries: the title LINE, the
# version LINE and the terms LINE. The fixture this replaces was the single phrase
# "Apache License, Version 2.0", which is also what a sentence DENYING the license says.
APACHE_HEAD_TEXT = """\
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.
"""
MIT_FILE_TEXT = "MIT License\n\nCopyright (c) 2026 Someone Else, Inc.\n\n" + MIT_BODY_TEXT

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
        (d / "LICENSE.txt").write_text(APACHE_HEAD_TEXT, encoding="utf-8")
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
                + MIT_BODY_TEXT.split("subject to the following conditions:", 1)[1].lstrip())
        ident, why = gen.license_terms(eula)
        self.assertIsNone(ident, "a proprietary EULA was recognized as MIT")
        self.assertIn("grant sentence is not MIT's", why)

    def test_a_commons_clause_after_mit_is_not_mit(self):
        text = MIT_FILE_TEXT + ("\nCommons Clause: the Licensor grants no right to Sell "
                                "the Software.\n")
        ident, why = gen.license_terms(text)
        self.assertIsNone(ident, "MIT plus a no-sale rider was recognized as MIT")
        self.assertIn("continues past the end of the MIT text", why)

    def test_a_non_commercial_restriction_spliced_into_the_grant_is_not_mit(self):
        text = MIT_FILE_TEXT.replace("without restriction,",
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
        self.assertIn("above the MIT grant", why)
        self.assertNotIn("does not recognize", why)


class TestTheRecognizerReadsLicenseTextNotMentions(unittest.TestCase):
    """`search` for a license title answers about any sentence that names it."""

    def test_a_denial_of_apache_is_not_apache(self):
        text = "This software is NOT licensed under the Apache License, Version 2.0.\n"
        self.assertIsNone(gen.license_terms(text)[0],
                          "a sentence denying Apache was read as granting it")

    def test_the_real_apache_header_still_resolves(self):
        self.assertEqual(gen.license_terms(APACHE_HEAD_TEXT)[0], "Apache-2.0")

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
        (d / "LICENSE-APACHE").write_text(APACHE_HEAD_TEXT, encoding="utf-8")
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
        d = self._dir("crlf")
        (d / "LICENSE").write_bytes(MIT_FILE_TEXT.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(gen.resolve_license(d), ("MIT", ""))

    def test_no_license_file_at_all_is_the_only_road_to_a_default(self):
        self.assertEqual(gen.resolve_license(self._dir("bare")), (None, ""))


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
                if declared != default:
                    offenders.append(f"{manifest.parent.name} declares {declared} with "
                                     f"no license file, so it should carry {default}")
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


if __name__ == "__main__":
    unittest.main()

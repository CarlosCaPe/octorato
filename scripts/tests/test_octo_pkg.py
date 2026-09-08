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

import importlib.util
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


octo_pkg = _load("octo_pkg_under_test", SCRIPTS / "octo_pkg.py")
gen = _load("gen_skill_manifests_under_test", SCRIPTS / "gen_skill_manifests.py")


def _ssh_ok() -> bool:
    return shutil.which("ssh-keygen") is not None and octo_pkg.ssh_keygen_y_supported()


def _fcntl_ok() -> bool:
    """Whether lock_held takes its POSIX branch here. The Windows branch already
    honoured its timeout; the test below is about the one that was ignoring it."""
    try:
        import fcntl  # noqa: F401
    except ImportError:
        return False
    return True


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


class TestQaCycle3(SandboxCase):
    """Regressions found in QA cycle 3, one test per finding.

    F1 the lock's unsigned `kind` field decided whether the signed ladder ran at all
    F2 verify was lock-driven only, so a vendored tree with no lock entry was invisible
    F3 the tree hash covered paths and bytes, so `chmod +x` on a shipped file was free
    """

    def _install_signed(self) -> Path:
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(pkg)]), 0)
        return self.brain.vendor_path("sample-package")

    def _set_lock_kind(self, name: str, kind: str) -> None:
        """Edit ONE field of packages.lock.json, the way a pull from a remote would.

        The lock is tracked and unsigned, which is the whole premise of F1: this edit
        needs no key, no signature and no write to the package itself.
        """
        lock = json.loads(self.brain.lock_path.read_text(encoding="utf-8"))
        for entry in lock["packages"]:
            if entry["name"] == name:
                entry["kind"] = kind
        self.brain.lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    def _verify_json(self) -> dict:
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            octo_pkg.main(["--brain", str(self.root), "verify", "--all", "--json"])
        return json.loads(buf.getvalue())

    # -- F1 ---------------------------------------------------------------
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f1_kind_flipped_to_arm_over_a_tampered_tree_is_fail(self):
        """The finding, verbatim: one edited field in an unsigned tracked file used to
        turn the whole ladder off for a present, tampered, vendored tree."""
        dest = self._install_signed()
        self._set_lock_kind("sample-package", "arm")
        (dest / "reference.txt").write_text("tampered by whoever pushed the lock\n",
                                            encoding="utf-8")
        data = self._verify_json()
        self.assertFalse(data["ok"], data)
        self.assertEqual(data["pass"], 0, data)
        self.assertEqual(len(data["fail"]), 1, data)
        self.assertIn("tree changed since install", data["fail"][0],
                      "the ladder must RUN on a present tree, whatever the lock's kind says")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 1)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f1_kind_disagreeing_with_the_installed_manifest_is_fail_naming_both(self):
        """Untampered tree, only the lock's kind edited. Still a FAIL, and the message
        carries both values because either side could be the edited one."""
        self._install_signed()
        self._set_lock_kind("sample-package", "arm")
        status, msg = octo_pkg.verify_entry(
            self.brain, self.brain.load_lock()["packages"][0])
        self.assertEqual(status, octo_pkg.FAIL, msg)
        self.assertIn("'skill'", msg)
        self.assertIn("'arm'", msg)
        self.assertIn("installed manifest", msg)

    def test_f1_installed_kind_comes_from_the_manifest_not_the_filename(self):
        d = self.tmp / "kinds"
        shutil.copytree(FIXTURE / "signed", d)
        self.assertEqual(octo_pkg.installed_kind(d), "skill")
        man = json.loads((d / "skill.json").read_text(encoding="utf-8"))
        man["kind"] = "arm"
        (d / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(octo_pkg.installed_kind(d), "arm",
                         "what the manifest declares wins over the file it lives in")
        del man["kind"]
        (d / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(octo_pkg.installed_kind(d), "skill",
                         "the schema says an absent kind means skill")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f1_a_real_arm_entry_with_no_vendor_tree_still_passes(self):
        """Arm isolation is why verify does not reach into the arm's own repo, and that
        behaviour is unchanged: it is presence on disk, not the declared kind, that
        selects the skill ladder.

        The fixture now REGISTERS the arm, because the word "registered" in that
        message became a fact this reads rather than one it asserts (QA cycle 12). The
        thing this test protects is untouched: no vendor tree, no ladder, still PASS.
        """
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('{"some-arm": "Documents/github/some-arm"}\n', encoding="utf-8")
        lock = self.brain.load_lock()
        lock["packages"].append({"name": "some-arm", "kind": "arm", "version": "1.0.0",
                                 "tree_sha256": None, "signer": None,
                                 "source": "git@example.test:o/some-arm.git",
                                 "installed_at": "2026-01-01T00:00:00Z"})
        self.brain.save_lock(lock)
        status, msg = octo_pkg.verify_entry(self.brain, lock["packages"][0])
        self.assertEqual(status, octo_pkg.PASS, msg)
        self.assertIn("(validated, not signed)", msg)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f1_an_arm_entry_that_also_has_a_vendor_tree_is_a_contradiction(self):
        self._install_signed()
        self._set_lock_kind("sample-package", "arm")
        status, msg = octo_pkg.verify_entry(
            self.brain, self.brain.load_lock()["packages"][0])
        self.assertEqual(status, octo_pkg.FAIL, msg)
        self.assertIn("an arm is never vendored into the brain", msg)

    # -- F2 ---------------------------------------------------------------
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f2_an_unlocked_vendor_tree_is_reported_by_verify_all(self):
        """Delete the lock entry, keep the tree and the symlink: both paths are
        gitignored and the link is in .git/info/exclude, so nothing else would ever
        mention this tree again while it kept loading on every prompt."""
        dest = self._install_signed()
        self.brain.lock_path.write_text(
            json.dumps({"version": 1, "packages": []}, indent=2) + "\n", encoding="utf-8")
        data = self._verify_json()
        self.assertFalse(data["ok"], data)
        self.assertEqual(len(data["fail"]), 1, data)
        self.assertIn("no packages.lock.json entry", data["fail"][0])
        self.assertIn(str(dest), data["fail"][0], "the message must name the path")
        self.assertEqual(data["total"], 1,
                         "an unlocked tree counts toward the total, or the ratio lies")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 1)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f2_a_dangling_stray_symlink_is_warn_not_fail(self):
        """Decision, stated in scan_unlocked: a link with no tree resolves to nothing,
        so it loads no code. It is litter from a half-removed install, and failing a
        push over litter trains the operator to bypass the gate. Reported, not fatal."""
        dest = self._install_signed()
        shutil.rmtree(dest)
        self.brain.lock_path.write_text(
            json.dumps({"version": 1, "packages": []}, indent=2) + "\n", encoding="utf-8")
        data = self._verify_json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["fail"], [], data)
        self.assertEqual(len(data["warn"]), 1, data)
        self.assertIn("stray link", data["warn"][0])
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0)
        # and the unlock the message names actually clears it
        self.assertEqual(
            octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-package"]), 0)
        self.assertEqual(self._verify_json()["warn"], [])

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f2_a_symlink_to_somewhere_else_entirely_is_not_ours_to_report(self):
        """skills/<name> pointing outside skills/vendor is the operator's own link."""
        outside = self.tmp / "his-own-skill"
        outside.mkdir()
        os.symlink(str(outside), self.brain.link_path("his-thing"), target_is_directory=True)
        data = self._verify_json()
        self.assertEqual((data["fail"], data["warn"]), ([], []), data)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f2_a_targeted_verify_does_not_sweep_the_disk(self):
        """`verify <name>` answers about that name. The sweep belongs to --all."""
        self._install_signed()
        self.brain.lock_path.write_text(
            json.dumps({"version": 1, "packages": []}, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 1)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "other-name"]), 1,
                         "a name that is in no lock is still its own FAIL")

    # -- F3 ---------------------------------------------------------------
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f3_chmod_x_changes_the_tree_hash_and_turns_verify_fail(self):
        """A shipped script silently becoming executable is a material change to code
        that sits in the always-on discovery path."""
        dest = self._install_signed()
        before = octo_pkg.tree_sha256(dest, "skill")
        target = dest / "reference.txt"
        os.chmod(target, 0o755)
        self.assertNotEqual(before, octo_pkg.tree_sha256(dest, "skill"))
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 1)
        os.chmod(target, 0o644)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0,
                         "and dropping the bit again restores the original hash")

    def test_f3_only_the_owner_execute_bit_moves_the_hash(self):
        """Group and other bits are properties of the copy and of the publisher's
        umask, not of the package. Hashing them would make the same bytes hash
        differently on two machines for no security gain."""
        d = self.tmp / "modes"
        shutil.copytree(FIXTURE / "signed", d)
        f = d / "reference.txt"
        os.chmod(f, 0o644)
        base = octo_pkg.tree_sha256(d, "skill")
        for benign in (0o600, 0o666, 0o444, 0o640):
            os.chmod(f, benign)
            self.assertEqual(base, octo_pkg.tree_sha256(d, "skill"), oct(benign))
        os.chmod(f, 0o744)
        self.assertNotEqual(base, octo_pkg.tree_sha256(d, "skill"))
        os.chmod(f, 0o644)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no mkfifo on this platform")
    def test_f3_a_fifo_in_a_package_is_refused_the_way_a_symlink_is(self):
        """It used to fall through `if not p.is_file(): continue`, so it was invisible
        to the hash and still shipped inside the package."""
        d = self.tmp / "fifo-pkg"
        shutil.copytree(FIXTURE / "signed", d)
        os.mkfifo(d / "pipe")
        with self.assertRaises(octo_pkg.PkgError) as cm:
            octo_pkg.tree_sha256(d, "skill")
        self.assertIn("non-regular file", str(cm.exception))

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_f3_a_package_carrying_a_fifo_is_refused_in_staging(self):
        """It was already refused before the fix, but by accident and far too late:
        the hash ignored the FIFO, so the tree check passed, the SIGNATURE was checked,
        and only copytree then choked on the special file and rolled back. Now it dies
        in the staging area like a tampered tree, with no key involved at all."""
        key = self.mint_key()
        d = self.tmp / "fifo-install"
        shutil.copytree(FIXTURE / "signed", d)
        if not hasattr(os, "mkfifo"):
            self.skipTest("no mkfifo on this platform")
        os.mkfifo(d / "pipe")
        self.sign(key, d)
        octo_pkg.SIG_VERIFY_CALLS = 0
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(d)]), 1)
        self.assertEqual(octo_pkg.SIG_VERIFY_CALLS, 0,
                         "a tree this primitive cannot hash is refused before any key is used")
        self.assertFalse(self.brain.vendor_path("sample-package").exists())

    def test_f3_an_empty_directory_is_documented_as_not_covered(self):
        """Pinned deliberately, because the docstring claims it. An empty directory
        carries no bytes and nothing the runtime can load; a non-empty one is covered
        through the paths of the files inside it."""
        d = self.tmp / "empty-dir"
        shutil.copytree(FIXTURE / "signed", d)
        before = octo_pkg.tree_sha256(d, "skill")
        (d / "hollow").mkdir()
        self.assertEqual(before, octo_pkg.tree_sha256(d, "skill"),
                         "an empty dir is invisible: this is the documented limit")
        (d / "hollow" / "payload.md").write_text("no longer empty\n", encoding="utf-8")
        self.assertNotEqual(before, octo_pkg.tree_sha256(d, "skill"),
                            "the moment it carries a file, it is covered")

    # -- fixtures ---------------------------------------------------------
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_the_violation_fixture_is_the_benign_one_one_edit_away(self):
        """`tampered/` is `signed/` with its tree_sha256 zeroed. Correcting that ONE
        field and signing makes it INSTALLABLE again, which is what keeps the fixture
        pair an honest violation/benign pair after a re-hash.

        Asserting that the field now equals the hash we just wrote into it would be a
        tautology (QA cycle 3 said so). The claim is about installability, so the test
        installs and verifies.
        """
        d = self.tmp / "one-edit"
        shutil.copytree(FIXTURE / "tampered", d)
        man = json.loads((d / "skill.json").read_text(encoding="utf-8"))
        self.assertNotEqual(man["tree_sha256"], octo_pkg.tree_sha256(d, "skill"),
                            "the violation fixture must start out mismatched")
        # the ONE edit
        man["tree_sha256"] = octo_pkg.tree_sha256(d, "skill")
        (d / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        key = self.mint_key()
        self.sign(key, d)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(d)]), 0,
                         "one corrected field must be enough to make it install")
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0)


class TestQaCycle4(SandboxCase):
    """QA cycle 3 found that the cycle-3 fix itself could be turned into a traceback.

    verify_entry promises it never raises, and the whole sweep depends on that: an
    exception aborts the loop, so the other packages and the unlocked-tree scan never
    report, and the failure that does surface names no package. Fail-closed is not the
    same as reporting correctly.
    """

    def _install_signed(self, tag: str = "pkg") -> tuple[str, Path]:
        """Install one freshly signed package under its own name.

        A per-tag name and staging dir, and one key minted for the whole test: the
        shared helpers write to fixed paths, and both ssh-keygen and copytree refuse
        to overwrite, so a loop that reuses them dies on its second turn.
        """
        if not getattr(self, "_key", None):
            self._key = self.mint_key()
        name = "sample-" + tag
        pkg = self.tmp / ("src-" + tag)
        shutil.copytree(FIXTURE / "signed", pkg)
        man = json.loads((pkg / "skill.json").read_text(encoding="utf-8"))
        man["name"] = name
        (pkg / "SKILL.md").write_text("---\nname: " + name + "\n---\n# " + name + "\n",
                                      encoding="utf-8")
        man["tree_sha256"] = octo_pkg.tree_sha256(pkg, "skill")
        (pkg / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        self.sign(self._key, pkg)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(pkg)]), 0)
        return name, self.brain.vendor_path(name)

    def _verify_json(self) -> dict:
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            octo_pkg.main(["--brain", str(self.root), "verify", "--all", "--json"])
        return json.loads(buf.getvalue())

    def _rewrite_manifest(self, dest: Path, raw: str) -> None:
        (dest / "skill.json").write_text(raw, encoding="utf-8")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_crafted_kind_value_does_not_raise(self):
        """`kind` as a list or dict used to hit `declared in MANIFEST_NAME`, and `in`
        on a dict hashes its operand, so an unhashable value raised TypeError."""
        for i, value in enumerate((["skill"], {}, 42, True)):
            with self.subTest(kind=value):
                name, dest = self._install_signed("kind%d" % i)
                try:
                    man = json.loads((dest / "skill.json").read_text(encoding="utf-8"))
                    man["kind"] = value
                    self._rewrite_manifest(dest, json.dumps(man))
                    out = self._verify_json()
                    self.assertFalse(out["ok"])
                    hit = [f for f in out["fail"] if f.startswith(name)]
                    self.assertEqual(len(hit), 1, out["fail"])
                    self.assertIn("no readable kind", hit[0])
                finally:
                    # in a finally, so one failing subtest does not leave its package
                    # installed and make the NEXT subtest fail for a borrowed reason.
                    # QA cycle 4 caught exactly that: `42` and `True` never crashed on
                    # the old tip, they only errored there by inheriting subtest 0's
                    # wreckage. A subtest has to fail for its own input or it is noise.
                    octo_pkg.main(["--brain", str(self.root), "uninstall", name])

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_manifest_that_is_not_an_object_does_not_raise(self):
        """`[]`, `"skill"`, `42` and `null` all parse as JSON. `.get` raises on all of
        them, so the manifest has to be shape-checked before it is read."""
        for i, raw in enumerate(("[]", '"skill"', "42", "null")):
            with self.subTest(manifest=raw):
                name, dest = self._install_signed("shape%d" % i)
                try:
                    self._rewrite_manifest(dest, raw)
                    out = self._verify_json()
                    self.assertFalse(out["ok"])
                    hit = [f for f in out["fail"] if f.startswith(name)]
                    self.assertEqual(len(hit), 1, out["fail"])
                finally:
                    octo_pkg.main(["--brain", str(self.root), "uninstall", name])

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_no_byte_sequence_in_a_manifest_reaches_a_traceback(self):
        """QA cycle 4, findings 1 and 2. Three cycles in a row found another input
        class escaping as an exception, so the fix is one seam (`read_json`) rather
        than another except clause, and this test walks the classes that broke it:
        bytes that are not UTF-8, and syntax deep enough to exhaust the parser's
        recursion. Both are ValueError-or-worse on the way from a path to an object.
        """
        deep = "[" * 200000 + "]" * 200000
        for i, raw in enumerate((b"\xff", b"\xfe\xff{}", deep.encode(), b"")):
            with self.subTest(payload=raw[:12]):
                name, dest = self._install_signed("bytes%d" % i)
                try:
                    (dest / "skill.json").write_bytes(raw)
                    out = self._verify_json()          # must not raise
                    self.assertFalse(out["ok"])
                    hit = [f for f in out["fail"] if f.startswith(name)]
                    self.assertEqual(len(hit), 1, out["fail"])
                finally:
                    octo_pkg.main(["--brain", str(self.root), "uninstall", name])

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_an_unreadable_package_directory_does_not_raise(self):
        """QA cycle 4, finding 3. `Path.is_file` swallows ENOENT and ENOTDIR, not
        EACCES, so a mode-000 package DIRECTORY raised from the stat itself, outside
        every try. This is the unreadable-file finding one level up."""
        name, dest = self._install_signed("dir000")
        os.chmod(dest, 0o000)
        self.addCleanup(lambda: os.chmod(dest, 0o755))
        out = self._verify_json()                      # must not raise
        self.assertFalse(out["ok"])
        self.assertEqual(len(out["fail"]), 1, out["fail"])
        self.assertIn(name, out["fail"][0])

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_lock_field_of_the_wrong_type_is_refused_by_the_reader(self):
        """QA cycle 4, findings 4 and 6. The lock is tracked and unsigned, so its
        fields arrive from a remote like any other file. A list-valued `signer`
        reached a set membership test and raised TypeError; a list-valued `source`
        reached .startswith inside sync, which `ai-pull` runs. Both are type-checked
        at the ONE place the file is read, not at each use.

        `installed_at` was added in cycle 14, and what found it was a control rather
        than a re-read of the list: a list `source` was refused here while a dict, a
        list or an int `installed_at` was accepted, because the field gained a
        consumer (entry_identity) without gaining a check. Each shape is its own
        subTest, so removing one field from the reader's tuple fails on that field
        and not on a neighbour's."""
        self._install_signed("locktype")
        for field, value in (("signer", ["octorato-release"]), ("signer", {"a": 1}),
                             ("source", ["x"]), ("tree_sha256", 7),
                             ("installed_at", {"a": 1}), ("installed_at", ["x"]),
                             ("installed_at", 7)):
            with self.subTest(field=field, value=value):
                lock = json.loads(self.brain.lock_path.read_text(encoding="utf-8"))
                good = json.dumps(lock, indent=2) + "\n"
                lock["packages"][0][field] = value
                self.brain.lock_path.write_text(json.dumps(lock, indent=2) + "\n",
                                                encoding="utf-8")
                try:
                    with self.assertRaises(octo_pkg.PkgError) as caught:
                        self.brain.load_lock()
                    self.assertIn(field, str(caught.exception))
                finally:
                    self.brain.lock_path.write_text(good, encoding="utf-8")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_lockfile_of_unreadable_bytes_is_refused_not_a_traceback(self):
        """QA cycle 4, finding 5. Same seam, the other tracked file."""
        self._install_signed("lockbytes")
        good = self.brain.lock_path.read_bytes()
        self.addCleanup(lambda: self.brain.lock_path.write_bytes(good))
        for raw in (b"\xff", ("[" * 200000 + "]" * 200000).encode()):
            with self.subTest(payload=raw[:8]):
                self.brain.lock_path.write_bytes(raw)
                with self.assertRaises(octo_pkg.PkgError):
                    self.brain.load_lock()

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_an_unreadable_file_in_the_tree_does_not_raise(self):
        """tree_sha256 reads every file; a mode-000 one raises PermissionError, which
        is an OSError and was not caught next to PkgError."""
        name, dest = self._install_signed("unreadable")
        victim = dest / "reference.txt"
        os.chmod(victim, 0o000)
        self.addCleanup(lambda: os.chmod(victim, 0o644))
        out = self._verify_json()
        self.assertFalse(out["ok"])
        self.assertEqual(len(out["fail"]), 1)
        self.assertIn(name, out["fail"][0])

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_the_control_a_clean_install_still_passes(self):
        """The guards must refuse crafted input without refusing a real package."""
        self._install_signed("clean")
        out = self._verify_json()
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["pass"], 1)
        self.assertEqual(out["fail"], [])


class TestQaCycle5(SandboxCase):
    """QA cycle 5 enumerated the boundary instead of guessing at it, and found the
    seam one file short of what it claimed. Two classes, both the same shape as the
    seven before them: bytes that never become JSON, and a stat one directory above
    the one that was guarded."""

    def _install_signed(self, tag: str = "pkg") -> tuple[str, Path]:
        if not getattr(self, "_key", None):
            self._key = self.mint_key()
        name = "sample-" + tag
        pkg = self.tmp / ("src-" + tag)
        shutil.copytree(FIXTURE / "signed", pkg)
        man = json.loads((pkg / "skill.json").read_text(encoding="utf-8"))
        man["name"] = name
        (pkg / "SKILL.md").write_text("---\nname: " + name + "\n---\n# " + name + "\n",
                                      encoding="utf-8")
        man["tree_sha256"] = octo_pkg.tree_sha256(pkg, "skill")
        (pkg / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        self.sign(self._key, pkg)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(pkg)]), 0)
        return name, self.brain.vendor_path(name)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_stray_byte_in_the_allowed_signers_file_does_not_kill_the_sweep(self):
        """The eighth, and the one that proved the seam was misnamed. The tracked
        registry/pkg-signers.pub never becomes JSON, so naming the seam after JSON
        left the only other read outside it, with the same `except OSError` and no
        ValueError. One latin-1 byte in a comment line raised UnicodeDecodeError out
        of the whole sweep: no JSON printed, no package named, every entry after the
        first unchecked. Skipping an unreadable signers file is fail-closed, since
        dropping principals can only refuse packages, never accept them."""
        name, _ = self._install_signed("signers")
        pub = self.root / "registry" / "pkg-signers.pub"
        pub.write_bytes(pub.read_bytes() + b"# note from the maintainer: caf\xe9\n")
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "verify", "--all"])
        self.assertEqual(rc, 1)
        self.assertIn(name, buf.getvalue(), "the failure has to name the package")
        self.assertIn("allowed-signers", buf.getvalue())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_an_unreadable_vendor_container_does_not_abort_any_verb(self):
        """The EACCES guard went onto `is_file` inside load_manifest, but the same
        stat happens one frame earlier whenever skills/vendor ITSELF is unreadable,
        and there it aborted every entry rather than one. uninstall refuses outright:
        it deletes, and a stat it cannot make means it does not know what it would be
        deleting."""
        self._install_signed("container")
        import contextlib, io
        vendor = self.brain.vendor_dir
        os.chmod(vendor, 0o000)
        self.addCleanup(lambda: os.chmod(vendor, 0o755))
        for argv in (["verify", "--all"], ["list"], ["sync"], ["lock"]):
            with self.subTest(verb=argv[0]):
                with contextlib.redirect_stdout(io.StringIO()):
                    octo_pkg.main(["--brain", str(self.root)] + argv)   # must not raise
        # main() turns PkgError into rc 1 plus a printed reason, so the assertion is
        # on the boundary a caller actually sees, not on the exception type.
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-container"])
        self.assertEqual(rc, 1, "uninstall must refuse what it cannot inspect")
        self.assertIn("cannot be read", buf.getvalue() or "")
        self.assertTrue((vendor / "sample-container").is_dir() if os.access(vendor, os.R_OK)
                        else True, "nothing may be removed on a refusal")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_an_unreadable_file_makes_the_hash_refuse_not_raise(self):
        """tree_sha256 already speaks PkgError for a symlink and a FIFO, so a file it
        cannot read belongs in the same vocabulary. Three callers catch only PkgError
        (hash, lock, install), and each turned an unreadable file into a traceback."""
        name, dest = self._install_signed("hashfail")
        victim = dest / "reference.txt"
        os.chmod(victim, 0o000)
        self.addCleanup(lambda: os.chmod(victim, 0o644))
        if os.access(victim, os.R_OK):
            self.skipTest("running as root, EACCES is not enforceable")
        with self.assertRaises(octo_pkg.PkgError) as caught:
            octo_pkg.tree_sha256(dest, "skill")
        self.assertIn("cannot be read", str(caught.exception))

    def test_a_name_that_is_not_utf8_is_refused_by_the_digest(self):
        """The fix that closed the fourth crossing family shipped with NO test, in a
        commit whose message says the family closes. Nothing in this file built a
        filename from bytes, so the refusal was unreachable from the suite by
        construction and a mutation disabling it survived (QA cycle 10). That is the
        third time in this session my intent and my diff diverged."""
        d = self.tmp / "badname"
        shutil.copytree(FIXTURE / "signed", d)
        clean = octo_pkg.tree_sha256(d, "skill")
        bad = os.path.join(bytes(d), b"evil\xff.md")
        with open(bad, "wb") as fh:
            fh.write(b"payload\n")
        self.assertTrue(any(b"\xff" in n for n in os.listdir(bytes(d))),
                        "the fixture must really carry a non-UTF-8 name")
        with self.assertRaises(octo_pkg.PkgError) as caught:
            octo_pkg.tree_sha256(d, "skill")
        self.assertIn("not valid UTF-8", str(caught.exception))
        os.unlink(bad)
        self.assertEqual(octo_pkg.tree_sha256(d, "skill"), clean,
                         "removing it restores the original digest")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_one_unnameable_file_does_not_take_the_whole_sweep_down(self):
        """The security half. `verify --all` used to abort with empty stdout, so
        anyone able to tamper with a vendored tree could suppress detection of that
        tamper by planting a badly named file beside it. Two packages here, and the
        healthy one must still get its verdict."""
        import contextlib, io
        bad_name, bad_dest = self._install_signed("aaa")
        good_name, _ = self._install_signed("zzz")
        with open(os.path.join(bytes(bad_dest), b"evil\xff.md"), "wb") as fh:
            fh.write(b"payload\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "verify", "--all"])
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn(bad_name, out, "the offending package is named")
        self.assertIn("not valid UTF-8", out)
        self.assertIn(good_name, out, "the OTHER package still gets its verdict")
        self.assertIn("1 verified", out, "the sweep finished")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_stray_with_an_unnameable_name_is_still_reported(self):
        """The SECOND encode crossing, which the digest refusal never sees: a vendor
        directory whose own name is not UTF-8 reaches the stray-scan print directly.
        What carries it is `errors="replace"` on stdout, a line whose comment talked
        only about Windows glyphs. Dropping that flag made the FAIL line and the
        summary vanish (QA cycle 10), so the invariant is pinned here."""
        self._install_signed("witness")
        os.mkdir(os.path.join(bytes(self.brain.vendor_dir), b"stray\xff"))
        # A SUBPROCESS, not redirect_stdout: a StringIO accepts surrogates happily,
        # so an in-process capture cannot see this at all and the first version of
        # this test survived the mutation that breaks the guard. The invariant lives
        # on the real stdout, so the test has to use one.
        cp = subprocess.run([sys.executable, str(SCRIPTS / "octo_pkg.py"),
                             "--brain", str(self.root), "verify", "--all"],
                            capture_output=True, text=True, timeout=90)
        self.assertEqual(cp.returncode, 1, cp.stderr)
        self.assertNotIn("Traceback", cp.stderr, "the sweep must not die on a name")
        self.assertIn("no packages.lock.json entry", cp.stdout,
                      "the stray is reported rather than taking the sweep down")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_failed_arm_install_leaves_nothing_behind(self):
        """install_skill learned to unwind across three cycles and install_arm never
        did, which a cross-function symmetry audit found: take the invariant a fix
        established and ask which siblings should hold it. Measured before the fix
        with an ordinary corrupt lockfile, the command reported failure and left the
        clone on disk AND the arm registered with no lock entry, so every
        arm-iterating script would write into a repo the brain does not consider
        installed, and the retry was permanently blocked (QA cycle 10)."""
        import contextlib, io
        src = self.tmp / "arm-src"
        src.mkdir()
        # `license` is required by the schema, and leaving it out is how the first
        # version of this test passed for the wrong reason: validation failed BEFORE
        # the arms-paths write, so the pre-existing handler cleaned up and the new
        # unwind was never reached. My own revert control caught it, which is the
        # fourth time today a test of mine proved something other than its name.
        (src / "arm.json").write_text(json.dumps(
            {"name": "sample-arm", "version": "1.0.0", "license": "MIT",
             "kind": "arm"}), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                     ["config", "user.name", "t"], ["add", "-A"],
                     ["commit", "-q", "-m", "arm"]):
            subprocess.run(["git", "-C", str(src)] + args, check=True,
                           capture_output=True, env=env)
        self.brain.lock_path.write_text("{ not json", encoding="utf-8")
        dest = self.tmp / "armdest"
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind", "arm",
                                "--dest", str(dest), str(src)])
        self.assertEqual(rc, 1)
        self.assertFalse(dest.exists(), "a failed arm install leaves no clone")
        self.assertFalse(cfg.exists(),
                         "nor an arm registered for a repo that is not installed")

    def test_an_unlistable_directory_is_not_a_hole_in_the_digest(self):
        """The most serious finding of any cycle, and the one a call-site
        enumeration structurally cannot reach: `Path.rglob` catches the OSError
        INSIDE pathlib, so a directory the process cannot list contributes nothing
        and never raises. `chmod 111` leaves every file in it readable by exact
        path, so a planted script was outside the digest, inside the package,
        loadable, and verify printed PASS over it."""
        d = self.tmp / "unlistable"
        shutil.copytree(FIXTURE / "signed", d)
        clean = octo_pkg.tree_sha256(d, "skill")
        evil = d / "evil"
        evil.mkdir()
        (evil / "payload.sh").write_text("payload\n", encoding="utf-8")
        self.assertNotEqual(octo_pkg.tree_sha256(d, "skill"), clean,
                            "a readable planted directory must change the hash")
        os.chmod(evil, 0o111)
        self.addCleanup(lambda: os.chmod(evil, 0o755))
        if os.access(evil, os.R_OK):
            self.skipTest("running as root, EACCES is not enforceable")
        self.assertTrue((evil / "payload.sh").is_file(),
                        "the planted file is still readable by exact path, "
                        "which is what makes the blind spot dangerous")
        with self.assertRaises(octo_pkg.PkgError) as caught:
            octo_pkg.tree_sha256(d, "skill")
        self.assertIn("cannot be listed", str(caught.exception))

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_verify_refuses_a_package_hiding_an_unlistable_directory(self):
        """The same hole end to end, because the unit test above proves the digest
        and this proves the verdict a reader actually sees."""
        import contextlib, io
        name, dest = self._install_signed("hidden")
        evil = dest / "evil"
        evil.mkdir()
        (evil / "payload.sh").write_text("payload\n", encoding="utf-8")
        os.chmod(evil, 0o111)
        self.addCleanup(lambda: os.chmod(evil, 0o755))
        if os.access(evil, os.R_OK):
            self.skipTest("running as root, EACCES is not enforceable")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "verify", "--all"])
        self.assertEqual(rc, 1, "PASS over an unhashed file is the guarantee failing")
        self.assertIn("cannot be listed", buf.getvalue())

    def test_every_resolve_site_refuses_a_symlink_loop(self):
        """QA cycle 7 found this at one call site, the fix named that site, and cycle
        8 found the identical bug one verb over in `hash`. That is the losing move
        this file has made six times, so .resolve() is a seam now and the test walks
        the family rather than the instance."""
        import contextlib, io
        loop = self.tmp / "loopdir"
        os.symlink(loop, loop)
        for argv in (["--brain", str(loop), "verify", "--all"],
                     ["--brain", str(self.root), "hash", str(loop)],
                     ["--brain", str(self.root), "install", "--kind", "arm",
                      "--dest", str(loop), "owner/repo"]):
            verb = next(a for a in argv if a in ("verify", "hash", "install"))
            with self.subTest(verb=verb):
                buf = io.StringIO()
                with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(io.StringIO()):
                    rc = octo_pkg.main(argv)          # must not raise
                self.assertEqual(rc, 1)
                self.assertIn("cannot be resolved", buf.getvalue())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_unwinds_a_restore_it_cannot_finish(self):
        """G2 shipped without a test. sync's rollback caught only OSError while its
        comment claimed it matched install's, so when exclude_add started raising
        PkgError through the seam, sync reported a package skipped that it had in
        fact restored whole, tree and symlink live."""
        import contextlib, io
        name, dest = self._install_signed("syncroll")
        link = self.brain.link_path(name)
        shutil.rmtree(dest)
        link.unlink()
        exclude = self.root / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_bytes(b"# ruta con acento: caf\xe9/\n")
        with contextlib.redirect_stdout(io.StringIO()):
            octo_pkg.main(["--brain", str(self.root), "sync"])
        self.assertFalse(dest.exists(), "a skipped restore must leave no tree behind")
        self.assertFalse(link.is_symlink())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_failing_cleanup_does_not_lose_the_original_cause(self):
        """G3 shipped without a test. The unwind wrapped only the exclude call, so a
        bare stat inside it could skip the rollback AND drop the reason, leaving the
        tree-plus-link-no-lock state the whole cycle exists to prevent."""
        import contextlib, io
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        # The failure goes into exclude_add (the PRIMARY path, which is what makes
        # the install fail) AND into the cleanup's own rmtree, which is the thing
        # G3 was about. The first version injected only into the primary path, so
        # it passed with the narrow pre-G3 wrapper still in place: it was testing
        # the BaseException width, not the cleanup wrapper (QA cycle 9 proved that
        # by mutation, and it is the third test in this session found passing for
        # a reason other than its name).
        real_add = octo_pkg.Brain.exclude_add
        real_rmtree = octo_pkg.shutil.rmtree
        def boom(self_, rel):
            raise PermissionError("ORIGINAL CAUSE")
        def boom_cleanup(path, *a, **kw):
            raise PermissionError("CLEANUP FAILED")
        octo_pkg.Brain.exclude_add = boom
        octo_pkg.shutil.rmtree = boom_cleanup
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "exclude_add", real_add))
        self.addCleanup(lambda: setattr(octo_pkg.shutil, "rmtree", real_rmtree))
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "install", str(pkg)])
        self.assertEqual(rc, 1)
        self.assertIn("ORIGINAL CAUSE", buf.getvalue(),
                      "the cause must survive a cleanup that fails on its way out")
        self.assertNotIn("CLEANUP FAILED", buf.getvalue(),
                         "the cleanup's own failure must not replace the cause")
        self.assertIn("rolled back", buf.getvalue())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_an_entry_with_no_kind_is_restored_not_prescribed_forever(self):
        """The schema says absent means skill, and three readers disagreed: verify
        applied the default, sync and lock compared to "skill" directly. So verify
        printed `absent on disk, fix: sync` and sync skipped that entry forever, a
        prescription that does nothing (QA cycle 8)."""
        import contextlib, io
        name, dest = self._install_signed("nokind")
        link = self.brain.link_path(name)
        lock = json.loads(self.brain.lock_path.read_text(encoding="utf-8"))
        for entry in lock["packages"]:
            entry.pop("kind", None)
            entry["source"] = str(self.tmp / "src-nokind")
        self.brain.lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(dest)
        link.unlink()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            octo_pkg.main(["--brain", str(self.root), "sync"])
        self.assertIn("1 restored", buf.getvalue(),
                      "`0 restored` also contains the word, so count it")
        self.assertTrue(dest.is_dir(), "the entry verify prescribes sync for must be "
                                       "the entry sync restores")

    def test_the_brain_argument_survives_a_symlink_loop(self):
        """pathlib turns ELOOP into RuntimeError, not OSError, so this call sitting
        outside the backstop meant a traceback for a bad argument."""
        import contextlib, io
        loop = self.tmp / "loop"
        os.symlink(loop, loop)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = octo_pkg.main(["--brain", str(loop), "verify", "--all"])
        self.assertEqual(rc, 1)
        self.assertIn("cannot be resolved", buf.getvalue())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_cp1252_byte_in_the_git_exclude_unwinds_the_install(self):
        """The severest of the ten, and the one that broke a stated invariant rather
        than a report. .git/info/exclude is plain text written by hand and by other
        tools, so a cp1252 comment in it is ordinary on Windows. It raised
        UnicodeDecodeError, which is a ValueError, straight past an unwind that
        caught only (OSError, PkgError), leaving a vendored tree and a live symlink
        in the always-on discovery path with no lock entry."""
        import contextlib, io
        key = self.mint_key()
        pkg = self.stage("signed")
        self.sign(key, pkg)
        exclude = self.root / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_bytes(b"# ruta con acento: caf\xe9/\n")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "install", str(pkg)])
        self.assertEqual(rc, 1)
        self.assertIn("rolled back", buf.getvalue())
        self.assertFalse(self.brain.vendor_path("sample-package").exists(),
                         "an unwound install leaves no tree in the discovery path")
        self.assertFalse(self.brain.link_path("sample-package").is_symlink())
        self.assertEqual(self.brain.load_lock()["packages"], [])

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_an_unreadable_skills_dir_is_reported_not_raised(self):
        """The guard went onto the vendor loop and stopped there, so the second loop
        over skills/ kept the shape the first one had just lost."""
        import contextlib, io
        self._install_signed("skillsdir")
        skills = self.root / "skills"
        os.chmod(skills, 0o000)
        self.addCleanup(lambda: os.chmod(skills, 0o755))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "verify", "--all"])
        self.assertEqual(rc, 1)
        self.assertIn("cannot be listed", buf.getvalue())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_uninstall_reports_a_tree_it_cannot_remove(self):
        """The ordering comment names an unreadable subdirectory as its motivating
        case, and that case still left as a traceback. A test that only asserts the
        happy-path order is why it survived (QA cycle 6 said so)."""
        import contextlib, io
        name, dest = self._install_signed("stuck")
        sub = dest / "sub"
        sub.mkdir()
        (sub / "x.txt").write_text("x", encoding="utf-8")
        os.chmod(sub, 0o000)
        self.addCleanup(lambda: os.chmod(sub, 0o755))
        if os.access(sub, os.R_OK):
            self.skipTest("running as root, EACCES is not enforceable")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", name])
        self.assertEqual(rc, 1)
        self.assertIn("could not be removed", buf.getvalue())
        self.assertTrue(self.brain.link_path(name).is_symlink(),
                        "the link stays, so nothing became an unlocked tree")
        self.assertEqual([p["name"] for p in self.brain.load_lock()["packages"]], [name],
                         "the lock still says installed, which is the reportable direction")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_uninstall_removes_the_tree_before_the_link(self):
        """Order is the correctness part, not the reporting part. Unlinking first and
        then removing left a half-removed install when the rmtree could not finish:
        tree present, symlink gone, lock entry still there. The tree carries the code,
        so the tree goes first and a failure leaves the install whole."""
        name, dest = self._install_signed("order")
        link = self.brain.link_path(name)
        self.assertTrue(dest.is_dir() and link.is_symlink())
        calls = []
        real_rmtree = octo_pkg.shutil.rmtree
        def watched(path, *a, **kw):
            calls.append(("rmtree", link.is_symlink()))
            return real_rmtree(path, *a, **kw)
        octo_pkg.shutil.rmtree = watched
        self.addCleanup(lambda: setattr(octo_pkg.shutil, "rmtree", real_rmtree))
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            octo_pkg.main(["--brain", str(self.root), "uninstall", name])
        self.assertEqual(calls[0], ("rmtree", True),
                         "the symlink must still be there when the tree is removed")
        self.assertFalse(dest.exists())
        self.assertFalse(link.is_symlink())


class ArmFixture(SandboxCase):
    """A real arm repo and an installed arm, shared by the two arm cycles. No tests."""

    def _arm_src(self, name: str = "sample-arm", manifest: dict | None = None) -> Path:
        src = self.tmp / f"arm-src-{name}"
        src.mkdir()
        man = manifest if manifest is not None else {
            "name": name, "version": "1.0.0", "license": "MIT", "kind": "arm"}
        (src / "arm.json").write_text(json.dumps(man), encoding="utf-8")
        # GIT_* scrubbed: a test launched from inside a git hook inherits GIT_DIR and
        # every `git -C <tmp>` below would commit into the LIVE repo instead.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                     ["config", "user.name", "t"], ["add", "-A"],
                     ["commit", "-q", "-m", "arm"]):
            subprocess.run(["git", "-C", str(src)] + args, check=True,
                           capture_output=True, env=env, timeout=120)
        return src

    def arm_dest(self, name: str = "sample-arm") -> Path:
        """Where an arm goes in the SHIPPED configuration: under $HOME, so what lands
        in arms-paths.json is the relative `Documents/github/<name>`.

        This is not decoration. A --dest outside $HOME makes install_arm fall back to
        an absolute `rel`, and one receipt test was green only because of that: it
        asserted the printed line contained the absolute dest, which the shipped shape
        never puts there (QA cycle 12).
        """
        return Path(os.environ["HOME"]) / "Documents" / "github" / name

    def _install_arm(self, name: str = "sample-arm",
                     dest: Path | None = None) -> tuple[Path, Path]:
        import contextlib, io
        src = self._arm_src(name)
        dest = dest if dest is not None else self.arm_dest(name)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind", "arm",
                                "--dest", str(dest), str(src)])
        self.assertEqual(rc, 0)
        return src, dest


class TestQaCycle11(ArmFixture):
    """The arm path, which had one test and therefore one covered line of it.

    Cycle 10 fixed install_arm's unwind and shipped three holes: the read the unwind
    depends on sat above the try, the lock every other writer takes was still not
    taken here, and uninstall manufactured the very orphan the unwind prevents while
    printing that it had removed four things. Cycle 11 also found the older guard
    (`except PkgError` around the clone validation) uncovered, because cycle 10's test
    was strengthened past it: correcting a weak test un-covered a real guard, so both
    ends of that flow are pinned here.
    """

    def test_install_arm_waits_for_the_lock_every_other_writer_takes(self):
        """B1: the one lock writer that never took the lock.

        install_skill, uninstall and lock all wrap their read-modify-write in
        lock_held; install_arm computed its write from an unprotected snapshot and
        reported success. Measured with two processes: the skill install waited 2.11s,
        the arm install went through in 0.19s and its own entry was gone from the
        lock afterwards. The state is the one lock_held's docstring names, reached on
        the SUCCESS path, so no unwind ever runs over it.

        Deterministic rather than racy: the lock is HELD here, and the child must
        block. `dest.exists()` while it is blocked is the discriminator that says it
        got past the clone and is waiting on the lock rather than still cloning.
        """
        src = self._arm_src()
        dest = self.tmp / "armdest"
        argv = [sys.executable, str(SCRIPTS / "octo_pkg.py"), "--brain", str(self.root),
                "install", "--kind", "arm", "--dest", str(dest), str(src)]
        # See the concurrent-install test: a CHILD re-derives user site-packages from
        # HOME and would lose jsonschema. The brain is pinned by --brain.
        env = {**os.environ, "HOME": self._home or os.environ["HOME"]}
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env)
        try:
            with self.brain.lock_held():
                try:
                    proc.communicate(timeout=6)
                    blocked = False
                except subprocess.TimeoutExpired:
                    blocked = True
                cloned = dest.exists()
                mid = [p.get("name") for p in
                       json.loads(self.brain.lock_path.read_text(encoding="utf-8"))["packages"]]
            out, err = proc.communicate(timeout=180)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=60)
        self.assertTrue(blocked,
                        "install_arm finished while another process held the lock: "
                        "its lock write is computed from an unprotected snapshot")
        self.assertTrue(cloned, "it must have been waiting on the LOCK, not on the clone")
        self.assertEqual(mid, [],
                         "nothing may be written to the lock while it is held elsewhere")
        self.assertEqual(proc.returncode, 0, err.decode("utf-8", "replace"))
        self.assertEqual([p["name"] for p in self.brain.load_lock()["packages"]],
                         ["sample-arm"], "and the entry lands once the lock is free")

    def test_an_unparseable_arms_paths_unwinds_the_way_an_empty_one_does(self):
        """B2: the read the unwind depends on sat ABOVE the try.

        Measured before the fix: `[]` unwound (rc=1, no clone) and `{ oops` did not
        (rc=1, clone left). The unparseable case is the commoner corruption and it
        reproduces the original symptom exactly: a clone on disk with the retry
        blocked forever by "destination already exists".
        """
        import contextlib, io
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        for shape in ('{ oops', '[]', '"a string"'):
            with self.subTest(arms_paths=shape):
                src = self._arm_src()
                dest = self.tmp / f"armdest-{abs(hash(shape))}"
                cfg.parent.mkdir(parents=True, exist_ok=True)
                cfg.write_text(shape, encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()), \
                        contextlib.redirect_stdout(io.StringIO()):
                    rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind",
                                        "arm", "--dest", str(dest), str(src)])
                self.assertEqual(rc, 1)
                self.assertFalse(dest.exists(),
                                 f"arms-paths.json = {shape!r} left the clone behind, "
                                 f"which blocks every retry")
                self.assertEqual(cfg.read_text(encoding="utf-8"), shape,
                                 "and the operator's file is not rewritten under him")
                shutil.rmtree(src)

    def test_uninstalling_an_arm_deregisters_it_instead_of_orphaning_it(self):
        """B3: uninstall manufactured the orphan install's unwind exists to prevent,
        and printed four removals to cover it.

        Measured before the fix: rc=0, "vendor tree, symlink, exclude entry and lock
        entry removed", clone still on disk, still in arms-paths.json, lock entry
        gone, and `verify --all` saw 0/0 because a lock-less arm has no row and the
        stray scan only walks skills/vendor.
        """
        import contextlib, io
        src, dest = self._install_arm()
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        # The fixture is now the SHIPPED shape, and this line is why. The receipt
        # assertion below used to pass because --dest sat outside $HOME, where
        # install_arm falls back to an absolute `rel`; with the registry holding the
        # relative string it shows what the operator would really be handed, and an
        # openable absolute path is what a location line is for (QA cycle 12).
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8"))["sample-arm"],
                         "Documents/github/sample-arm",
                         "the registered value is relative to $HOME")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-arm"])
        self.assertEqual(rc, 0)
        said = buf.getvalue()
        self.assertNotIn("sample-arm", json.loads(cfg.read_text(encoding="utf-8")),
                         "registered with no lock entry is the orphan itself")
        self.assertEqual(self.brain.load_lock()["packages"], [])
        self.assertTrue(dest.exists(),
                        "the clone is the operator's own repo and is never deleted")
        self.assertIn(octo_pkg.ARMS_PATHS_REL, said)
        self.assertIn(str(dest), said,
                      "and it says where the repo was left, as a path that can be "
                      "opened: printing the registry's $HOME-relative string as if it "
                      "were a location sends the operator to the wrong directory")
        for lie in ("vendor tree", "symlink", "exclude entry"):
            self.assertNotIn(lie, said,
                             f"an arm has no {lie}; claiming it is a false receipt")
        self.assertIn("lock entry", said)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0)

    def test_a_validation_failure_after_the_clone_leaves_nothing_behind(self):
        """The older guard, `except PkgError: rmtree(target); raise`, which cycle 10
        left with ZERO coverage without touching it. Its only test was the weak
        license-less arm, and fixing that test to reach the NEW unwind moved the flow
        past validation, so the older guard ended up held by nothing. Correcting a
        weak test silently un-covers whatever it was accidentally exercising.
        """
        import contextlib, io
        cases = {
            "no-license": {"name": "sample-arm", "version": "1.0.0", "kind": "arm"},
            "wrong-kind": {"name": "sample-arm", "version": "1.0.0", "license": "MIT",
                           "kind": "skill"},
        }
        for tag, man in cases.items():
            with self.subTest(manifest=tag):
                src = self._arm_src(f"bad-{tag}", manifest=man)
                dest = self.tmp / f"armdest-{tag}"
                with contextlib.redirect_stderr(io.StringIO()), \
                        contextlib.redirect_stdout(io.StringIO()):
                    rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind",
                                        "arm", "--dest", str(dest), str(src)])
                self.assertEqual(rc, 1)
                self.assertFalse(dest.exists(),
                                 "a refused arm.json leaves no clone to block the retry")
                self.assertFalse((self.root / octo_pkg.ARMS_PATHS_REL).exists())

    def test_an_existing_arms_paths_is_restored_byte_for_byte(self):
        """The `cfg.write_text(cfg_before)` half of the unwind. Only the
        `cfg_before is None` path had a test, so a rollback over an arms-paths.json
        that already had arms in it was never once executed."""
        import contextlib, io
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        cfg.parent.mkdir(parents=True, exist_ok=True)
        before = '{\n  "other-arm": "Documents/github/other-arm"\n}\n'
        cfg.write_text(before, encoding="utf-8")
        src = self._arm_src()
        dest = self.tmp / "armdest"
        self.brain.lock_path.write_text("{ not json", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind", "arm",
                                "--dest", str(dest), str(src)])
        self.assertEqual(rc, 1)
        self.assertFalse(dest.exists())
        self.assertEqual(cfg.read_text(encoding="utf-8"), before,
                         "the other arm's registration must survive, byte for byte")

    def test_a_non_exception_is_re_raised_after_the_unwind(self):
        """`if not isinstance(e, Exception): raise`. A Ctrl-C mid-install must still
        stop the program, and it must not stop it half-installed."""
        import contextlib, io
        src = self._arm_src()
        dest = self.tmp / "armdest"
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        real_save = octo_pkg.Brain.save_lock

        def interrupted(self_, lock):
            raise KeyboardInterrupt()

        octo_pkg.Brain.save_lock = interrupted
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "save_lock", real_save))
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                octo_pkg.main(["--brain", str(self.root), "install", "--kind", "arm",
                               "--dest", str(dest), str(src)])
        self.assertFalse(dest.exists(), "the unwind runs first, then the re-raise")
        self.assertFalse(cfg.exists(), "and the registration it wrote is taken back")

    def test_an_unreadable_arms_paths_is_never_deleted_by_the_unwind(self):
        """The read moved inside the protected region, so it can now fail there, and
        `cfg_before is None` no longer means "the file did not exist". Without a
        separate `cfg_known` flag the unwind reaches its unlink branch and answers
        "I could not read your arms-paths.json" by deleting it."""
        import contextlib, io
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('{"other-arm": "elsewhere"}\n', encoding="utf-8")
        os.chmod(cfg, 0o000)
        self.addCleanup(lambda: os.chmod(cfg, 0o644))
        if os.access(cfg, os.R_OK):
            self.skipTest("running as root, EACCES is not enforceable")
        src = self._arm_src()
        dest = self.tmp / "armdest"
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind", "arm",
                                "--dest", str(dest), str(src)])
        self.assertEqual(rc, 1)
        self.assertFalse(dest.exists())
        self.assertTrue(cfg.exists(),
                        "a file this could not READ is a file it must not delete")

    def test_verify_json_carries_a_non_utf8_name_through_a_real_stdout(self):
        """The test gap, and it is the same sin twice in one diff: the ensure_ascii
        fix shipped with no test, and none was possible on the surface it was written
        against. Every --json test went through redirect_stdout(StringIO) plus
        json.loads, and a StringIO never ENCODES, so the shipped form and the mutant
        round-trip identically through it. The invariant lives on a real stdout, so
        the test needs a subprocess, which is the treatment the stray test already
        got one finding earlier.
        """
        vendor = self.brain.vendor_dir
        vendor.mkdir(parents=True, exist_ok=True)
        os.mkdir(os.path.join(bytes(vendor), b"stray\xff"))
        cp = subprocess.run([sys.executable, str(SCRIPTS / "octo_pkg.py"),
                             "--brain", str(self.root), "verify", "--all", "--json"],
                            capture_output=True, text=True, timeout=180,
                            env={**os.environ, "HOME": self._home or os.environ["HOME"]})
        self.assertNotIn("Traceback", cp.stderr)
        payload = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertIn(os.fsdecode(b"stray\xff"), " ".join(payload["fail"]),
                      "the consumer must get the name back byte for byte; "
                      "ensure_ascii=False sends the surrogate into the "
                      "errors='replace' stream and the name it reads is a "
                      "different string")


class TestQaCycle12(ArmFixture):
    """Cycle 11 protected install_arm and left its neighbours unprotected.

    The shape repeats: an invariant is established in one function, the comment
    defending it CLAIMS its siblings already hold it, and nobody checked. `lock` was
    named in that claim and was the one unprotected read-modify-write left. uninstall
    got the deregistration and not the unwind. verify printed the word "registered"
    without reading the registry. And two guards shipped with no test at all, which
    is the state that tells the next reader to stop looking.
    """

    def _race(self, mutate):
        """Run `mutate(brain)` at the moment lock_held is taken, then take it.

        The window these bugs live in is between an unprotected READ and the write
        that lands under the lock, so a second process has to land inside it. Driving
        that from lock_held itself is deterministic where a real race is not, and it
        puts the concurrent write exactly where the measured one arrived.
        """
        real = octo_pkg.Brain.lock_held

        def racing(self_, timeout=30.0):
            mutate(self_)
            return real(self_, timeout)

        octo_pkg.Brain.lock_held = racing
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "lock_held", real))

    # -- A: the unprotected read-modify-write the comment said did not exist ------
    def test_lock_writes_against_the_file_it_is_about_to_overwrite(self):
        """cmd_lock read the lock, hashed every tree and shelled out to ssh-keygen,
        then wrote that stale snapshot back inside lock_held. os.replace makes the
        loss total and silent: QA measured a concurrent install of `newcomer-b`
        vanishing while `lock` printed success at rc 0.
        """
        import contextlib, io
        lock = self.brain.load_lock()
        lock["packages"].append({"name": "already-here", "kind": "arm",
                                 "version": "1.0.0", "source": "git@example.test:o/a"})
        self.brain.save_lock(lock)

        def other_process_installs(brain):
            cur = json.loads(brain.lock_path.read_text(encoding="utf-8"))
            cur["packages"].append({"name": "newcomer-b", "kind": "arm",
                                    "version": "2.0.0", "source": "git@example.test:o/b"})
            brain.lock_path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")

        self._race(other_process_installs)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "lock"])
        self.assertEqual(rc, 0)
        names = [p["name"] for p in self.brain.load_lock()["packages"]]
        self.assertIn("newcomer-b", names,
                      "an install that landed while lock was hashing was overwritten "
                      "by a snapshot taken before it, at rc 0, with no message")
        self.assertIn("already-here", names, "and the entry it was re-locking survives")

    # -- B: the unwind uninstall never got, and the word verify never checked -----
    def test_uninstall_puts_arms_paths_back_when_the_lock_write_fails(self):
        """_deregister_arm WRITES, and save_lock can fail after it. Without an unwind
        that leaves deregistered-but-still-locked: the mirror image of the orphan
        install_arm's unwind exists to prevent, and just as invisible.
        """
        import contextlib, io
        self._install_arm()
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        before = cfg.read_text(encoding="utf-8")
        real_save = octo_pkg.Brain.save_lock

        def boom(self_, lock):
            raise PermissionError(13, "Permission denied")

        octo_pkg.Brain.save_lock = boom
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "save_lock", real_save))
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-arm"])
        self.assertEqual(rc, 1)
        self.assertEqual(cfg.read_text(encoding="utf-8"), before,
                         "the registration is written back byte for byte, or the arm "
                         "is deregistered with its lock entry still standing")
        self.assertEqual([p["name"] for p in self.brain.load_lock()["packages"]],
                         ["sample-arm"], "and the lock is what it was, so a retry works")

    def test_verify_does_not_say_registered_over_an_arm_that_is_not(self):
        """`arm registered (validated, not signed)` was printed without ever opening
        arms-paths.json. WARN and not FAIL on purpose: a second machine after
        ai-pull has the tracked lock and not the gitignored registry, and a push must
        not break there. It carries its own `fix:` because sync skips non-skill
        entries, so prescribing sync would prescribe a no-op.
        """
        import contextlib, io
        lock = self.brain.load_lock()
        entry = {"name": "some-arm", "kind": "arm", "version": "1.0.0",
                 "tree_sha256": None, "signer": None,
                 "source": "git@example.test:o/some-arm.git"}
        lock["packages"].append(entry)
        self.brain.save_lock(lock)

        status, msg = octo_pkg.verify_entry(self.brain, entry)
        self.assertEqual(status, octo_pkg.WARN, msg)
        self.assertIn("does not register it", msg)
        self.assertIn("fix:", msg, "or cmd_verify prints 'run sync' under a WARN sync "
                                   "cannot fix")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(
                octo_pkg.main(["--brain", str(self.root), "verify", "--all"]), 0,
                "an unregistered arm is not a push-blocking failure")
        self.assertNotIn("fix: python3", buf.getvalue())

        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('{"some-arm": "Documents/github/some-arm"}\n', encoding="utf-8")
        status, msg = octo_pkg.verify_entry(self.brain, entry)
        self.assertEqual(status, octo_pkg.PASS, msg)
        self.assertIn(str(Path(os.environ["HOME"]) / "Documents" / "github" / "some-arm"),
                      msg, "and when it does say registered, it says where")

    # -- C: the unwind is the inverse of the write, symlinks included -------------
    def test_the_unwind_over_a_symlinked_registry_deletes_what_the_write_created(self):
        """With arms-paths.json a DANGLING symlink, exists() reads absent and
        write_text creates the file at the far end. `cfg.unlink()` then deleted the
        operator's SYMLINK and left that stray file: both halves backwards, and
        "restores byte for byte" false for the one shape where the write and the
        delete disagree about what the path means.
        """
        import contextlib, io
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        cfg.parent.mkdir(parents=True, exist_ok=True)
        far = self.tmp / "elsewhere" / "arms-paths.json"
        far.parent.mkdir(parents=True)
        cfg.symlink_to(far)
        self.assertFalse(cfg.exists(), "the fixture is a DANGLING link, the shape that "
                                       "makes the write and the unwind disagree")
        src = self._arm_src()
        dest = self.arm_dest()
        self.brain.lock_path.write_text("{ not json", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind", "arm",
                                "--dest", str(dest), str(src)])
        self.assertEqual(rc, 1)
        self.assertFalse(dest.exists())
        self.assertTrue(cfg.is_symlink(),
                        "the symlink is the operator's, not something the write made")
        self.assertFalse(far.exists(),
                         "and the file the write DID make, at the far end, is gone")

    # -- E: two guards that shipped with no test ---------------------------------
    def test_a_lock_row_that_vanished_mid_uninstall_is_not_claimed_as_removed(self):
        """The `any(p.get("name") == name ...)` guard. `entry` is read before the
        lock, so a concurrent uninstall of the same name can take the row away before
        this one writes; appending "lock entry" unconditionally would put a removal
        this process did not perform on the receipt. Unreachable in one process, which
        is why the writer that reaches it is driven from lock_held.
        """
        import contextlib, io
        lock = self.brain.load_lock()
        lock["packages"].append({"name": "ghost", "kind": "skill", "version": "1.0.0",
                                 "signer": "octorato-release", "tree_sha256": "d0",
                                 "source": "git@example.test:o/ghost.git"})
        self.brain.save_lock(lock)

        def other_process_uninstalls(brain):
            cur = json.loads(brain.lock_path.read_text(encoding="utf-8"))
            cur["packages"] = [p for p in cur["packages"] if p["name"] != "ghost"]
            brain.lock_path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")

        self._race(other_process_uninstalls)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "ghost"])
        self.assertEqual(rc, 0)
        self.assertIn("nothing was there to remove", buf.getvalue())
        self.assertNotIn("lock entry", buf.getvalue(),
                         "the row was gone before this process wrote; claiming it is "
                         "a receipt for work someone else did")

    def test_a_registry_that_stopped_being_an_object_refuses_the_deregistration(self):
        """_deregister_arm's non-dict `raise PkgError`. Replacing it with a `return`
        was invisible to the whole suite, though the docstring argues at length that
        skipping leaves registered-and-unlocked, the orphan this branch exists to stop
        making. Reachable the same way as the guard above: the file is a dict when
        uninstall reads it and a list by the time the lock is held.
        """
        import contextlib, io
        self._install_arm()
        cfg = self.root / octo_pkg.ARMS_PATHS_REL

        def other_process_corrupts_it(brain):
            (brain.root / octo_pkg.ARMS_PATHS_REL).write_text("[]\n", encoding="utf-8")

        self._race(other_process_corrupts_it)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-arm"])
        self.assertEqual(rc, 1)
        self.assertIn("is not an object", err.getvalue())
        self.assertEqual(cfg.read_text(encoding="utf-8"), "[]\n",
                         "a file it refuses to understand is a file it does not rewrite")
        self.assertEqual([p["name"] for p in self.brain.load_lock()["packages"]],
                         ["sample-arm"],
                         "refusing leaves registered-and-locked, which a retry can act "
                         "on; skipping leaves the orphan")

    # -- F: the seam its own sibling already used --------------------------------
    def test_an_unreadable_registry_is_named_by_the_seam_at_install(self):
        """`if cfg.exists():` was raw while _deregister_arm went through stat_ok, so
        an unsearchable company/config/ answered with a bare Errno 13 instead of the
        seam's sentence naming the file.
        """
        import contextlib, io
        cfgdir = self.root / "company" / "config"
        cfgdir.mkdir(parents=True)
        os.chmod(cfgdir, 0o000)
        self.addCleanup(lambda: os.chmod(cfgdir, 0o755))
        if os.access(cfgdir, os.X_OK):
            self.skipTest("running as root, EACCES is not enforceable")
        src = self._arm_src()
        dest = self.arm_dest()
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind", "arm",
                                "--dest", str(dest), str(src)])
        self.assertEqual(rc, 1)
        self.assertIn(f"{octo_pkg.ARMS_PATHS_REL} cannot be read", err.getvalue(),
                      "the raw stat says PermissionError over an absolute path and "
                      "never says which file the install could not read")
        self.assertFalse(dest.exists(), "and the clone still unwinds")

    # -- G: a value that is documented as a list ---------------------------------
    def test_a_candidate_array_is_rendered_as_a_path_not_as_a_python_list(self):
        """brain_doctor.resolve_home_relative and CLAUDE.md both say a value may be an
        array of candidates. `str(was)` printed `the clone at ['a/b', 'c/d']`. The
        first candidate that exists wins, the way the doctor resolves it.
        """
        import contextlib, io
        src, dest = self._install_arm()
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        cfg.write_text(json.dumps({"sample-arm": ["Documents/github/nowhere",
                                                  "Documents/github/sample-arm"]},
                                  indent=2) + "\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-arm"])
        said = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn(str(dest), said)
        self.assertNotIn("['", said, "a Python list repr is not a location")
        self.assertNotIn("nowhere", said,
                         "and the candidate that is not on disk is not the answer")

    # -- H and I: the orphan's exit, and the clone it never mentioned -------------
    def test_an_arm_registered_with_no_lock_entry_can_be_uninstalled(self):
        """The state this whole commit is about had no exit: `uninstall` answered rc 1
        "is not installed" and left the registration, so hand-editing arms-paths.json
        was the only way out, which is the habit the lock exists to remove.
        """
        import contextlib, io
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('{"orphan-arm": "Documents/github/orphan-arm"}\n',
                       encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "orphan-arm"])
        said = buf.getvalue()
        self.assertEqual(rc, 0, "an install that half-unwound has to be undoable")
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")), {})
        self.assertIn(octo_pkg.ARMS_PATHS_REL, said)
        self.assertIn("left in place", said)

    def test_the_clone_is_still_reported_when_the_registry_is_already_gone(self):
        """With no arms-paths.json the `arm_path is None` branch said nothing about
        the clone, so the operator was told it survives everywhere except where he is
        least likely to know: with the registry already inconsistent.
        """
        import contextlib, io
        self._install_arm()
        (self.root / octo_pkg.ARMS_PATHS_REL).unlink()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-arm"])
        said = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("lock entry", said)
        self.assertIn("left in place", said,
                      "the clone survives in BOTH branches; silence in one of them is "
                      "a receipt that hides a directory on disk")
        self.assertIn(octo_pkg.ARMS_PATHS_REL, said)

    # -- J: the claim and the code, saying the same thing ------------------------
    def test_an_os_error_after_the_registration_is_wrapped_not_re_raised(self):
        """The other half of `if not isinstance(e, Exception): raise`, and the half a
        commit message described backwards ("a non-PkgError is re-raised"). An OSError
        is NOT re-raised: it is wrapped into PkgError, a reported refusal at rc 1
        instead of a traceback, which is this module's stance everywhere. Only a
        BaseException that is not an Exception goes back out, and the KeyboardInterrupt
        test one class up pins that side.
        """
        import contextlib, io
        src = self._arm_src()
        dest = self.arm_dest()
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        real_save = octo_pkg.Brain.save_lock

        def boom(self_, lock):
            raise OSError(28, "No space left on device")

        octo_pkg.Brain.save_lock = boom
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "save_lock", real_save))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "install", "--kind", "arm",
                                "--dest", str(dest), str(src)])
        self.assertEqual(rc, 1)
        self.assertIn("install of arm sample-arm rolled back: OSError", err.getvalue(),
                      "re-raising here would reach main's generic backstop, which "
                      "cannot say what was rolled back")
        self.assertFalse(dest.exists())
        self.assertFalse(cfg.exists())


class TestQaCycle13(ArmFixture):
    """Cycle 12 moved the assertion one hop and left the new last hop unpinned.

    The named shape at eleven instances: `cmd_lock` learned to write under the lock
    and applied its result BY NAME, so the row it stamps can be a different package;
    `cmd_sync` was the same unprotected read-modify-write one function further on,
    with a network fetch for a window; `_render_arm_location` fixed the list it had
    been shown and left the family; `cmd_uninstall` re-read the registry inside the
    lock in the callee and decided the whole branch from a read outside it.

    The two helpers below are deliberate copies of TestQaCycle5._install_signed and
    TestQaCycle12._race rather than a move: three QA cycles are built on those two
    classes, and a shared-fixture refactor at this depth risks silently changing what
    an existing test covers, which is the sub-form of the same shape this class is
    about.
    """

    def _install_signed(self, tag: str = "pkg") -> tuple[str, Path]:
        if not getattr(self, "_key", None):
            self._key = self.mint_key()
        name = "sample-" + tag
        pkg = self.tmp / ("src-" + tag)
        shutil.copytree(FIXTURE / "signed", pkg)
        man = json.loads((pkg / "skill.json").read_text(encoding="utf-8"))
        man["name"] = name
        (pkg / "SKILL.md").write_text("---\nname: " + name + "\n---\n# " + name + "\n",
                                      encoding="utf-8")
        man["tree_sha256"] = octo_pkg.tree_sha256(pkg, "skill")
        (pkg / "skill.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        self.sign(self._key, pkg)
        self.assertEqual(octo_pkg.main(["--brain", str(self.root), "install", str(pkg)]), 0)
        return name, self.brain.vendor_path(name)

    def _race(self, mutate):
        """Run `mutate(brain)` at the moment lock_held is taken, then take it."""
        real = octo_pkg.Brain.lock_held

        def racing(self_, timeout=30.0):
            mutate(self_)
            return real(self_, timeout)

        octo_pkg.Brain.lock_held = racing
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "lock_held", real))

    def _read_lock(self) -> list:
        return json.loads(self.brain.lock_path.read_text(encoding="utf-8"))["packages"]

    def _row(self, name: str) -> dict:
        return next(p for p in self._read_lock() if p["name"] == name)

    def _stale_hash(self, name: str) -> None:
        """Make `lock` want to update this row: the lock's hash is not the tree's."""
        lock = json.loads(self.brain.lock_path.read_text(encoding="utf-8"))
        for entry in lock["packages"]:
            if entry["name"] == name:
                entry["tree_sha256"] = "0" * 64
        self.brain.lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    # -- A: a name is a key, not an identity -------------------------------------
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_lock_does_not_stamp_a_row_whose_kind_changed_under_it(self):
        """Cycle 12 made `lock` write under the lock and apply BY NAME, and the name
        can outlive the package. A row that was a skill when the hash was computed and
        an arm when it was applied got the skill's hash, signer and version stamped
        onto it at rc 0 under `re-locked: 1 entry(ies) updated`. Nothing catches it
        afterwards either: verify_entry's arm branch never reads those fields. Silent
        corruption of a tracked file.
        """
        import contextlib, io
        name, _ = self._install_signed("kindflip")
        self._stale_hash(name)

        def other_process_turns_it_into_an_arm(brain):
            cur = json.loads(brain.lock_path.read_text(encoding="utf-8"))
            for entry in cur["packages"]:
                if entry["name"] == name:
                    entry["kind"] = "arm"
                    entry["tree_sha256"] = None
                    entry["signer"] = None
            brain.lock_path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")

        self._race(other_process_turns_it_into_an_arm)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "lock"])
        row = self._row(name)
        self.assertEqual(row["kind"], "arm", "the racer's row is what survives")
        self.assertIsNone(row["tree_sha256"],
                          "a skill's tree hash stamped onto an arm row is corruption "
                          "no verify tier ever reads back")
        self.assertIsNone(row["signer"])
        self.assertIn("not updated", buf.getvalue())
        self.assertEqual(rc, 1, "a re-lock that skipped a row it was asked to re-lock "
                                "did not do what it was asked")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_lock_does_not_stamp_a_row_that_was_deleted_and_re_added(self):
        """The second shape of the same miss, and the one that stays plausible: the
        row is still a skill, so kind alone does not catch it. The old package's hash
        and signer land on the new row while `source` stays the new one, which
        surfaces later as a false `tree changed since install` blaming a package that
        was never installed from there.
        """
        import contextlib, io
        name, _ = self._install_signed("readd")
        self._stale_hash(name)

        def other_process_reinstalls_from_elsewhere(brain):
            cur = json.loads(brain.lock_path.read_text(encoding="utf-8"))
            cur["packages"] = [p for p in cur["packages"] if p["name"] != name]
            cur["packages"].append({
                "name": name, "kind": "skill", "version": "9.9.9",
                "tree_sha256": "b" * 64, "signer": "someone-else",
                "source": "git@example.test:other/repo",
                "installed_at": "2030-01-01T00:00:00Z"})
            brain.lock_path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")

        self._race(other_process_reinstalls_from_elsewhere)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "lock"])
        row = self._row(name)
        self.assertEqual(row["tree_sha256"], "b" * 64,
                         "the new install's hash, not the hash of the tree the old "
                         "row pointed at")
        self.assertEqual(row["signer"], "someone-else")
        self.assertEqual(row["version"], "9.9.9")
        self.assertEqual(rc, 1)
        self.assertIn("not updated", buf.getvalue())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_the_relock_receipt_names_only_the_rows_the_apply_loop_touched(self):
        """M-B: the commit's own headline claim, and it was invisible to the suite.

        The source and the commit message both say "`changed` is what was actually
        applied, not what was computed, so the receipt cannot name a row that is
        gone". Reverting `changed` to the computed names passed every test, because
        the only race test appends an ARM row: `updates` is empty there and the apply
        branch never runs. Two skills, one of them uninstalled inside the window, is
        the case the claim is about.
        """
        import contextlib, io
        kept, _ = self._install_signed("kept")
        vanishing, _ = self._install_signed("vanishing")
        self._stale_hash(kept)
        self._stale_hash(vanishing)

        def other_process_uninstalls_one(brain):
            cur = json.loads(brain.lock_path.read_text(encoding="utf-8"))
            cur["packages"] = [p for p in cur["packages"] if p["name"] != vanishing]
            brain.lock_path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")

        self._race(other_process_uninstalls_one)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "lock"])
        said = buf.getvalue()
        self.assertEqual(rc, 0, "a row that is simply gone is not a refusal")
        self.assertIn("re-locked: 1 entry(ies) updated", said,
                      "one row was applied, and the receipt counts applications")
        self.assertIn(kept, said)
        self.assertNotIn(vanishing, said,
                         "naming a row that is no longer in the lock tells the "
                         "operator a package was re-locked that does not exist")
        self.assertEqual([p["name"] for p in self._read_lock()], [kept])
        self.assertNotEqual(self._row(kept)["tree_sha256"], "0" * 64,
                            "and the row that did survive was really updated, so the "
                            "apply branch this test exists for actually ran")

    # -- B: the unfixed sibling, with a network fetch for a window ---------------
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_does_not_restore_a_package_whose_lock_row_was_removed(self):
        """cmd_sync was cycle 12's exact class one function on, and its window is a
        FETCH, wider than the ssh-keygen window that was closed. Measured with a real
        second process: while sync fetched, another pid ran `uninstall`, and sync then
        restored the vendor tree, the symlink and the exclude entry for a package with
        NO lock row. scan_unlocked calls that the most dangerous state there is, and
        it sits in the always-on discovery path. sync's trailing verify does exit 1
        and name it, so it was never silent; creating the state is the bug.
        """
        import contextlib, io
        name, dest = self._install_signed("syncrace")
        link = self.brain.link_path(name)
        lock = json.loads(self.brain.lock_path.read_text(encoding="utf-8"))
        for entry in lock["packages"]:
            entry["source"] = str(self.tmp / "src-syncrace")
        self.brain.lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(dest)
        link.unlink()
        self.brain.exclude_remove(f"skills/{name}")

        def other_process_uninstalls_it(brain):
            brain.lock_path.write_text(
                json.dumps({"version": 1, "packages": []}, indent=2) + "\n",
                encoding="utf-8")

        self._race(other_process_uninstalls_it)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            octo_pkg.main(["--brain", str(self.root), "sync"])
        self.assertFalse(dest.exists(),
                         "a tree restored for a package the lock no longer names is an "
                         "unlocked stray, gitignored and loading on every prompt")
        self.assertFalse(link.is_symlink())
        self.assertFalse(self.brain.exclude_has(f"skills/{name}"))
        self.assertIn("was removed while", buf.getvalue())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_a_restore_that_fails_after_the_exclude_leaves_no_line_behind(self):
        """sync's unwind undid the tree and the link and not the exclude entry, while
        install_skill's undoes all three. exclude_add is the LAST step, so a failure
        at or after it left a `skills/<name>` line in .git/info/exclude for a package
        that is not on disk: untracked, absent from git status, and it silently
        pre-excludes whatever the operator later puts at that path by hand.
        """
        import contextlib, io
        name, dest = self._install_signed("excroll")
        link = self.brain.link_path(name)
        lock = json.loads(self.brain.lock_path.read_text(encoding="utf-8"))
        for entry in lock["packages"]:
            entry["source"] = str(self.tmp / "src-excroll")
        self.brain.lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(dest)
        link.unlink()
        self.brain.exclude_remove(f"skills/{name}")
        self.assertFalse(self.brain.exclude_has(f"skills/{name}"), "the control")

        real_add = octo_pkg.Brain.exclude_add

        def add_then_fail(self_, rel):
            real_add(self_, rel)          # the write really happens, then the step fails
            raise PermissionError(13, "died after the exclude was written")

        octo_pkg.Brain.exclude_add = add_then_fail
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "exclude_add", real_add))
        with contextlib.redirect_stdout(io.StringIO()):
            octo_pkg.main(["--brain", str(self.root), "sync"])
        self.assertFalse(dest.exists())
        self.assertFalse(link.is_symlink())
        self.assertFalse(self.brain.exclude_has(f"skills/{name}"),
                         "the unwind has to be the inverse of every step it took, not "
                         "of the two that were easy to remember")

    # -- C: the family, not the instance -----------------------------------------
    def test_a_registry_value_that_is_not_a_path_is_named_not_rendered_as_one(self):
        """Cycle 12 taught _render_arm_location about a flat list of strings, which is
        the shape it had been shown, and left every other shape going through str():
        a nested list printed `/home/.../['a']`, a dict printed `/home/.../{'x': 1}`.
        arms-paths.json is gitignored and hand-edited, so these are typos, and the
        lock type-checks every field it reads for exactly this reason.
        """
        home = os.environ["HOME"]
        for value in ([["a"]], {"x": 1}, 7, None, [None]):
            with self.subTest(value=value):
                said = octo_pkg._render_arm_location(value)
                self.assertNotIn(home, said,
                                 f"{value!r} rendered as {said!r}: a value that is "
                                 f"not a path must never be joined onto $HOME and "
                                 f"handed over as a place to go")
                self.assertTrue(said.startswith("(no usable path"),
                                f"{value!r} rendered as {said!r}, which reads as a "
                                f"location; it has to read as a value that is not one")
                self.assertIn(octo_pkg.ARMS_PATHS_REL, said,
                              "and the line has to say where the bad value lives")

    def test_an_empty_registry_value_does_not_report_the_whole_home_directory(self):
        """The worst member of that family, end to end. `""` joined to $HOME resolves
        to $HOME itself, which exists, so uninstall printed `the clone at
        /home/<user> is your own repo and was left in place` over the operator's
        entire home directory: a receipt that is not merely ugly but false.
        """
        import contextlib, io
        self._install_arm()
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        cfg.write_text(json.dumps({"sample-arm": ""}, indent=2) + "\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-arm"])
        said = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertNotIn(f"the clone at {os.environ['HOME']} is", said,
                         "$HOME is not where the arm was cloned")
        self.assertIn("no usable path", said)

    # -- D: the caller that re-read nothing --------------------------------------
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_uninstall_decides_arm_from_the_rows_the_lock_holds(self):
        """`is_arm` selects a whole branch (deregister, or not) and was decided from
        reads taken before the lock, while _deregister_arm underneath it already
        re-read inside. Half a fix: a row that becomes an arm inside the window is
        uninstalled as a skill, so the registration survives with no lock entry, which
        is the orphan the rest of this commit exists to prevent.
        """
        import contextlib, io
        name, _ = self._install_signed("late")
        cfg = self.root / octo_pkg.ARMS_PATHS_REL

        def other_process_makes_it_an_arm(brain):
            cur = json.loads(brain.lock_path.read_text(encoding="utf-8"))
            for entry in cur["packages"]:
                if entry["name"] == name:
                    entry["kind"] = "arm"
            brain.lock_path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")
            c = brain.root / octo_pkg.ARMS_PATHS_REL
            c.parent.mkdir(parents=True, exist_ok=True)
            c.write_text(json.dumps({name: "Documents/github/" + name}) + "\n",
                         encoding="utf-8")

        self._race(other_process_makes_it_an_arm)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", name])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")), {},
                         "deregistered-with-no-lock-row is the orphan, and it is "
                         "invisible to verify because a lock-less arm has no row")
        self.assertIn(octo_pkg.ARMS_PATHS_REL, buf.getvalue())
        self.assertEqual(self._read_lock(), [])

    def test_a_registry_that_is_not_an_object_is_a_verify_failure_not_a_warn(self):
        """M-K: `_arm_registration`'s non-dict `raise`, whose docstring argues the
        point at length ("I could not read the registry" is not "the arm is not
        registered"), can become `return None` with the whole suite still green.
        _deregister_arm's identical guard IS pinned; the sibling this commit
        introduced was not. Through verify, which is the always-on reader: returning
        None turns a FAIL naming an unreadable file into a WARN saying the arm is
        simply not registered here, and rc 1 into rc 0.
        """
        import contextlib, io
        self._install_arm()
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        cfg.write_text("[]\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "verify", "--all"])
        said = buf.getvalue()
        self.assertEqual(rc, 1, "a registry it cannot read is a failure to report, "
                                "never 'the arm is not registered here'")
        self.assertIn("cannot be read for it", said)
        self.assertIn("is not an object", said)
        self.assertNotIn("does not register it", said)

    # -- E: the branch the fixture correction stopped covering -------------------
    def test_an_arm_installed_outside_home_is_registered_at_its_absolute_path(self):
        """M-A: install_arm's `except ValueError: rel = str(target)`, uncovered.

        Cycle 12 moved every arm test to the shipped $HOME-relative --dest, which was
        the right correction (a receipt test had been green only because of the
        absolute fallback). It also deleted the only assertion that reached this
        branch: tests still install outside $HOME, and none of them says what gets
        registered there. Correcting a weak test silently dropped coverage it was
        providing by accident, which is the sub-form of the shape this class is about.
        """
        import contextlib, io
        outside = self.tmp / "elsewhere" / "sample-arm"
        self.assertFalse(str(outside).startswith(os.environ["HOME"]), "the premise")
        src, dest = self._install_arm(dest=outside)
        cfg = self.root / octo_pkg.ARMS_PATHS_REL
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")),
                         {"sample-arm": str(outside)},
                         "a path relative_to($HOME) cannot express has to be stored "
                         "absolute; a raised ValueError here fails the whole install")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-arm"])
        self.assertIn(f"the clone at {outside} is your own repo", buf.getvalue(),
                      "and the absolute value renders as itself, not joined onto $HOME")

    # -- F: the message the run had the context to make true ---------------------
    def test_a_failed_lock_write_says_what_it_restored_not_that_it_may_have(self):
        """install wraps a post-registration failure into "rolled back"; uninstall let
        the raw OSError reach main's backstop, which says "the operation did not
        complete and may have left work half done". This run knows better: the
        registry was written back byte for byte and the lock never moved. A backstop
        guesses because it has no context.
        """
        import contextlib, io
        self._install_arm()
        real_save = octo_pkg.Brain.save_lock

        def boom(self_, lock):
            raise PermissionError(13, "Permission denied")

        octo_pkg.Brain.save_lock = boom
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "save_lock", real_save))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = octo_pkg.main(["--brain", str(self.root), "uninstall", "sample-arm"])
        said = err.getvalue()
        self.assertEqual(rc, 1)
        self.assertNotIn("may have left work half done", said,
                         "the generic backstop's guess, printed over a run that knows")
        self.assertIn("put back byte for byte", said)
        self.assertIn("PermissionError", said, "and the cause is not swallowed")
        self.assertNotIn("had already been removed", said,
                         "`gone` is a COPY of `removed` taken before the protected "
                         "region; aliasing it lets the deregistration this sentence "
                         "just said was put back appear in the same sentence as "
                         "something that is gone (cycle 14 mutation M16)")


class TestQaCycle14(ArmFixture):
    """Cycle 13 NARROWED the delete-and-re-add shape and its docstring said closed.

    `entry_identity` was (kind, source, installed_at), and the docstring credited
    installed_at with catching "a delete-and-re-add from the same source". No test
    varied one field on its own: the re-add test moved source, installed_at, version,
    signer and tree_sha256 at once, so dropping installed_at from the identity, or
    dropping source, each passed all 349 tests. Only `kind` was really pinned.

    And installed_at is `strftime("%Y-%m-%dT%H:%M:%SZ")`, one second wide, so a re-add
    from the SAME source inside one second is identity-identical to the row it
    replaced. QA measured the corruption still landing through that: the old package's
    hash and signer stamped onto the new row, rc 0, `re-locked: 1 entry(ies) updated`.

    So every identity field gets its own test that varies THAT field and nothing else.
    The point is not the count, it is that each mutant has exactly one test it can die
    to, and no test can borrow a neighbour's evidence.
    """

    # Bound, not copied and not inherited: cycle 13 copied cycle 12's helpers because
    # a shared-fixture refactor at that depth could silently change what an existing
    # test covers. Binding the same function objects has neither cost. Subclassing
    # TestQaCycle13 would re-run its whole suite a second time under this name.
    _install_signed = TestQaCycle13._install_signed
    _race = TestQaCycle13._race
    _read_lock = TestQaCycle13._read_lock
    _row = TestQaCycle13._row
    _stale_hash = TestQaCycle13._stale_hash

    def _pin(self, tag: str, field: str, value) -> str:
        """Install a skill, make `lock` want to rewrite its row, then change exactly
        ONE identity field under the lock.

        Everything else in the row is byte-identical, so the whole-row assertion below
        can only be carried by `field`. A stamp shows up as tree_sha256 going back to
        the tree's real hash, which is what `lock` would have written.
        """
        import contextlib, io
        name, _ = self._install_signed(tag)
        self._stale_hash(name)
        before = dict(self._row(name))

        def other_process_changes_one_field(brain):
            cur = json.loads(brain.lock_path.read_text(encoding="utf-8"))
            for entry in cur["packages"]:
                if entry["name"] == name:
                    entry[field] = value
            brain.lock_path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")

        self._race(other_process_changes_one_field)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "lock"])
        said = buf.getvalue()
        self.assertEqual(self._row(name), dict(before, **{field: value}),
                         f"{field} moved under the lock and the row was stamped "
                         f"anyway: an update computed against a row that no longer "
                         f"exists, written at rc 0 under a success receipt")
        self.assertEqual(rc, 1, "a re-lock the operator asked for and did not get")
        self.assertIn("not updated", said)
        self.assertIn(field, said, "the WARN has to name the field that moved; that "
                                   "is the whole content of the message")
        return said

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_identity_pins_kind_on_its_own(self):
        self._pin("pinkind", "kind", "arm")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_identity_pins_source_on_its_own(self):
        self._pin("pinsource", "source", "git@example.test:other/repo")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_identity_pins_installed_at_on_its_own(self):
        self._pin("pinwhen", "installed_at", "2030-01-01T00:00:00Z")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_identity_pins_tree_sha256_on_its_own(self):
        """The field `lock` overwrites, which is what makes it the right one to read:
        an update is computed against the hash a row HELD, so a row whose hash is no
        longer that is not the row that was hashed."""
        self._pin("pinhash", "tree_sha256", "b" * 64)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_identity_pins_signer_on_its_own(self):
        """The other field `lock` overwrites. Stamping a signer is worse than stamping
        a hash: it is the value the whole trust ladder reads back."""
        self._pin("pinsigner", "signer", "someone-else")

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_lock_does_not_stamp_a_re_add_from_the_same_source_in_one_second(self):
        """The hole cycle 13's docstring said installed_at had closed, measured.

        Not a single-field pin, on purpose: this is the reproduction. kind, source and
        installed_at are carried over from the old row byte for byte, which is exactly
        what an uninstall-plus-reinstall from the same source inside one second
        produces, and against the three-field identity it compared EQUAL. Measured on
        shipped HEAD: rc 0, the row left holding the old package's hash and the old
        package's signer, under `re-locked: 1 entry(ies) updated`.
        """
        import contextlib, io
        name, _ = self._install_signed("samesrc")
        self._stale_hash(name)
        old = dict(self._row(name))

        def other_process_re_adds_from_the_same_source(brain):
            cur = json.loads(brain.lock_path.read_text(encoding="utf-8"))
            cur["packages"] = [p for p in cur["packages"] if p["name"] != name]
            cur["packages"].append(dict(old, version="9.9.9", tree_sha256="c" * 64,
                                        signer="someone-else"))
            brain.lock_path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")

        self._race(other_process_re_adds_from_the_same_source)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "lock"])
        row = self._row(name)
        self.assertEqual(row["tree_sha256"], "c" * 64,
                         "the old package's hash on the new row surfaces later as a "
                         "false 'tree changed since install' blaming a package that "
                         "was never installed from there")
        self.assertEqual(row["signer"], "someone-else")
        self.assertEqual(row["version"], "9.9.9")
        self.assertEqual(rc, 1)
        self.assertIn("not updated", buf.getvalue())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_does_not_restore_over_a_row_whose_hash_alone_moved(self):
        """What the removed clause used to say, said by the identity instead.

        cmd_sync compared `row.tree_sha256 != entry.tree_sha256` beside its identity
        check. With tree_sha256 inside the identity that clause cannot fail on its
        own, so it reads as a second guard while being a copy of half the first: a
        mutant that survives by construction. It is gone, and this is the test that
        keeps what it was doing.
        """
        import contextlib, io
        name, dest = self._install_signed("synchash")
        link = self.brain.link_path(name)
        lock = json.loads(self.brain.lock_path.read_text(encoding="utf-8"))
        for entry in lock["packages"]:
            entry["source"] = str(self.tmp / "src-synchash")
        self.brain.lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(dest)
        link.unlink()
        self.brain.exclude_remove(f"skills/{name}")

        def other_process_moves_the_hash(brain):
            cur = json.loads(brain.lock_path.read_text(encoding="utf-8"))
            for entry in cur["packages"]:
                entry["tree_sha256"] = "d" * 64
            brain.lock_path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")

        self._race(other_process_moves_the_hash)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            octo_pkg.main(["--brain", str(self.root), "sync"])
        self.assertFalse(dest.exists(),
                         "the bytes fetched describe the hash the row held before it "
                         "moved; restoring them puts a tree on disk the CURRENT row "
                         "does not describe, and verify then blames the wrong source")
        self.assertFalse(link.is_symlink())
        self.assertFalse(self.brain.exclude_has(f"skills/{name}"))
        self.assertIn("entry changed while", buf.getvalue())

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_does_not_copy_over_an_install_that_landed_while_it_fetched(self):
        """The other race sync's critical section defends, and it deletes work.

        `if dest.exists() or dest.is_symlink(): continue` inside the lock reads like
        tidiness and is not: without it, sync reaches shutil.copytree over a tree that
        an install put there while sync was fetching, copytree raises FileExistsError,
        and sync's own unwind then rmtree's the OTHER run's freshly installed package
        and drops its exclude line. The row is untouched, so nothing downstream ever
        explains where the tree went. Untested until cycle 14.
        """
        import contextlib, io
        name, dest = self._install_signed("syncwin")
        link = self.brain.link_path(name)
        lock = json.loads(self.brain.lock_path.read_text(encoding="utf-8"))
        for entry in lock["packages"]:
            entry["source"] = str(self.tmp / "src-syncwin")
        self.brain.lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        kept = dest / "INSTALLED-BY-THE-OTHER-RUN.md"
        shutil.rmtree(dest)
        link.unlink()

        def other_process_finishes_installing_it(brain):
            # The lock row is left EXACTLY as it is: this is the same package from the
            # same source, so the identity check passes and the dest check is the only
            # thing between sync and the other run's tree.
            shutil.copytree(self.tmp / "src-syncwin", dest)
            kept.write_text("landed while sync was fetching\n", encoding="utf-8")
            os.symlink(os.path.relpath(dest, link.parent), link, target_is_directory=True)

        self._race(other_process_finishes_installing_it)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            octo_pkg.main(["--brain", str(self.root), "sync"])
        self.assertTrue(kept.exists(),
                        "sync copied over a tree another run had just installed, and "
                        "its unwind then deleted that run's package")
        self.assertTrue(link.is_symlink())
        self.assertTrue(self.brain.exclude_has(f"skills/{name}"))

    def test_an_unusable_registry_value_is_printed_bounded(self):
        """_short exists to bound what a receipt pastes back, and nothing measured it.

        arms-paths.json is hand-edited and gitignored, so an unusable value can be any
        size at all. A verify line that pastes a whole nested object back at the
        operator is not a receipt, it is the file (cycle 14 mutation M23).
        """
        said = octo_pkg._render_arm_location([["x" * 500]])
        self.assertIn("no usable path", said)
        self.assertNotIn("x" * 100, said, "the value is NAMED, not reproduced")
        self.assertLess(len(said), 200, said)

    @unittest.skipUnless(_fcntl_ok(), "no fcntl: the POSIX branch is not the one that runs here")
    def test_lock_held_refuses_within_the_timeout_it_advertises(self):
        """`timeout` was real on the Windows branch and ignored on the one that runs.

        POSIX called a BLOCKING flock(LOCK_EX): QA asked for 2s against a held lock
        and waited the full 11s the holder took. A parameter naming a bound it does
        not impose is this commit's own finding one layer down. The holder here is a
        second file descriptor, which conflicts with this one because flock is per
        open-file-description and not per process (measured, not assumed), and the
        attempt runs in a daemon thread so that a revert to the blocking call FAILS
        this test in ten seconds instead of hanging the suite: a hang is not a
        detection.
        """
        import fcntl, threading, time
        self.brain.lock_path.parent.mkdir(parents=True, exist_ok=True)
        guard = self.brain.lock_path.with_name(self.brain.lock_path.name + ".lock")
        holder = open(guard, "a+")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)

        outcome = {}

        def attempt():
            try:
                with self.brain.lock_held(timeout=0.5):
                    outcome["acquired"] = True
            except octo_pkg.PkgError as e:
                outcome["refused"] = str(e)

        started = time.monotonic()
        t = threading.Thread(target=attempt, daemon=True)
        t.start()
        t.join(10)
        waited = time.monotonic() - started
        self.assertFalse(t.is_alive(),
                         "lock_held(timeout=0.5) was still blocking after 10s: the "
                         "argument names a bound it does not impose")
        self.assertNotIn("acquired", outcome, "the lock was held by another fd")
        self.assertIn("refused", outcome)
        self.assertIn("0.5", outcome["refused"], "and it says what it waited for")
        self.assertLess(waited, 5, f"asked for 0.5s, waited {waited:.1f}s")

    @unittest.skipUnless(_fcntl_ok(), "no fcntl: the POSIX branch is not the one that runs here")
    def test_lock_held_measures_its_bound_on_a_clock_that_cannot_step_back(self):
        """A wall clock is not a stopwatch, and this waits with one.

        Both branches computed the deadline with `time.time()`. An NTP correction
        landing mid-wait steps it BACKWARDS, and then the poll compares against a
        deadline an hour away: the caller that asked for 0.5s waits until the holder
        lets go, and cmd_sync's whole-run budget is defeated by a clock rather than by
        contention. The shim here is the real time module with one method replaced, so
        the sleep and the monotonic clock under it are genuine, and the attempt runs in
        a daemon thread for the same reason as the test above: a revert FAILS in ten
        seconds instead of hanging the suite. Restoring the module in the cleanup is
        also what lets a leaked thread finish, because its next poll then reads a real
        clock that is already past a real deadline.
        """
        import fcntl, threading, time
        self.brain.lock_path.parent.mkdir(parents=True, exist_ok=True)
        guard = self.brain.lock_path.with_name(self.brain.lock_path.name + ".lock")
        holder = open(guard, "a+")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)

        class ClockStepsBack:
            """time, except that time() jumps an hour back after the first read."""
            def __init__(self):
                self.reads = 0

            def time(self_):
                self_.reads += 1
                return time.time() - (3600 if self_.reads > 1 else 0)

            def __getattr__(self_, k):
                return getattr(time, k)      # monotonic and sleep stay real

        shim = ClockStepsBack()
        octo_pkg.time = shim
        self.addCleanup(lambda: setattr(octo_pkg, "time", time))

        outcome = {}

        def attempt():
            try:
                with self.brain.lock_held(timeout=0.5):
                    outcome["acquired"] = True
            except octo_pkg.PkgError as e:
                outcome["refused"] = str(e)

        started = time.monotonic()
        t = threading.Thread(target=attempt, daemon=True)
        t.start()
        t.join(10)
        waited = time.monotonic() - started
        self.assertFalse(t.is_alive(),
                         "the clock stepped back an hour and lock_held(timeout=0.5) is "
                         "still waiting: its bound is measured on a wall clock, so an "
                         "NTP correction suspends it")
        self.assertNotIn("acquired", outcome, "the lock was held by another fd")
        self.assertIn("refused", outcome)
        self.assertLess(waited, 5, f"asked for 0.5s, waited {waited:.1f}s")


class TestQaCycle15(ArmFixture):
    """cmd_sync's two pre-fetch guards, and the run-level bound the lock never had.

    Cycle 14 pinned every field of the identity that the in-lock re-check compares.
    Four lines ABOVE that re-check, `cmd_sync` has two guards that nothing reached:
    the fetched manifest's hash against the row's, and the fetched manifest's NAME
    against the row's. Both survived all 359 tests and all 58 selftest legs; the
    no-op control in the same mutation batch survived too, so the run discriminated.

    The name one is the worst finding of this series because its failure mode is
    silent and green. The threat model is the module's own: packages.lock.json is
    TRACKED and UNSIGNED, so one edited row arrives through an ordinary `git pull`.
    Point row `sample-aaa` at a source that publishes `sample-bbb` and edit that row's
    tree_sha256 to match, which is exactly what gets past the hash guard one line up,
    and without the name guard package B lands installed and symlinked under package
    A's name, at rc 0, under `1 restored, 0 skipped`, with verify reporting
    `2 verified, 0 failed`. Verify checks the tree against the manifest INSIDE it and
    never against the row's name, so nothing downstream ever names it, and a skill in
    skills/ runs on every prompt.
    """

    _install_signed = TestQaCycle13._install_signed
    _race = TestQaCycle13._race
    _read_lock = TestQaCycle13._read_lock
    _row = TestQaCycle13._row

    def _detach(self, name: str) -> Path:
        """Take the package off disk, leaving only its lock row: what sync restores."""
        dest = self.brain.vendor_path(name)
        link = self.brain.link_path(name)
        shutil.rmtree(dest)
        link.unlink()
        self.brain.exclude_remove(f"skills/{name}")
        return dest

    def _edit_row(self, name: str, **fields) -> None:
        """Edit ONE row of the tracked, unsigned lockfile. This is not a contrivance:
        it is the exact shape in which a lock change reaches a machine, an ordinary
        `git pull`, and it is why every field read out of this file is a guard's job
        rather than a fact."""
        lock = json.loads(self.brain.lock_path.read_text(encoding="utf-8"))
        for entry in lock["packages"]:
            if entry["name"] == name:
                entry.update(fields)
        self.brain.lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    def _sync(self) -> tuple[int, str]:
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = octo_pkg.main(["--brain", str(self.root), "sync"])
        return rc, buf.getvalue()

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_does_not_install_one_package_under_another_packages_name(self):
        """Row A points at a source publishing B, with A's hash edited to match.

        The hash guard one line above passes BY CONSTRUCTION here: the row carries B's
        hash and the fetch produces B's tree. So this test can only be carried by the
        name guard, and the in-lock identity re-check cannot carry it either, because
        nothing races and the row is byte-identical to the entry it was read from.

        Without the guard, measured: tree installed at skills/vendor/sample-aaa whose
        SKILL.md says sample-bbb, symlink created, `1 restored, 0 skipped`, rc 0, and
        verify `2 verified, 0 failed (2/2)`.
        """
        a, dest_a = self._install_signed("aaa")
        b, _ = self._install_signed("bbb")
        src_b = self.tmp / "src-bbb"
        self._edit_row(a, source=str(src_b),
                       tree_sha256=json.loads((src_b / "skill.json").read_text(
                           encoding="utf-8"))["tree_sha256"])
        self._detach(a)

        rc, said = self._sync()

        installed = ""
        if (dest_a / "SKILL.md").exists():
            installed = (dest_a / "SKILL.md").read_text(encoding="utf-8")
        self.assertFalse(dest_a.exists(),
                         f"{b} is installed at {octo_pkg.VENDOR_REL}/{a}: a package "
                         f"under another package's name, in the always-on discovery "
                         f"path, at rc {rc} under a success receipt. What landed says "
                         f"{installed!r}")
        self.assertFalse(self.brain.link_path(a).is_symlink())
        self.assertFalse(self.brain.exclude_has(f"skills/{a}"))
        self.assertIn("source now publishes", said)
        self.assertIn(b, said, "the WARN has to name what the source actually "
                               "publishes; that is the whole content of the message")
        self.assertIn("0 restored", said)

    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_does_not_install_a_tree_the_lock_row_does_not_describe(self):
        """One edited hash on a row whose source is real, signed and unchanged.

        The name guard cannot carry this (the source publishes exactly this name) and
        neither can the in-lock re-check (nothing races). Without the guard the tree
        is restored, the symlink created and the receipt says `1 restored`, and only
        the trailing verify then fails at rc 1: less severe than the name guard only
        because it eventually surfaces, and it still put an unverifiable tree in the
        discovery path first.
        """
        name, dest = self._install_signed("drift")
        self._edit_row(name, source=str(self.tmp / "src-drift"), tree_sha256="f" * 64)
        self._detach(name)

        rc, said = self._sync()

        self.assertFalse(dest.exists(),
                         "a tree whose hash the lock row does not carry was restored "
                         "into the discovery path, and only verify said so afterwards")
        self.assertFalse(self.brain.link_path(name).is_symlink())
        self.assertFalse(self.brain.exclude_has(f"skills/{name}"))
        self.assertIn("source tree hash differs", said)
        self.assertIn("0 restored", said)

    @unittest.skipUnless(_fcntl_ok(), "no fcntl: the POSIX branch is not the one that runs here")
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_bounds_the_lock_wait_of_a_whole_run_not_of_one_acquire(self):
        """The fourteenth instance of this commit's own pattern, in this commit.

        lock_held's timeout is per ACQUIRE. cmd_sync acquires once per absent package
        inside a `try` whose `except PkgError` turns a refusal into a WARN and
        continues, so the docstring's bound ("a pull must not hang behind a session
        holding the lock for a clone") was a per-RUN claim at a scope nothing imposed.
        QA measured three absent packages against a held lock at 90.5s, and 234 rows
        would be ~117 minutes of sequential 30-second waits.

        The kill is exact rather than timed, because a timeout is not a detection and
        this box has run this module at 22s and at 900s: after the first acquire spends
        the whole budget, every later acquire is handed 0.0, which is what "one
        deadline for the run" MEANS. Per-acquire hands out the same number three times.
        The wall-clock assertion is over the lock wait ONLY, summed inside the wrapper,
        so no fetch, install or verify time is in it.
        """
        import contextlib, fcntl, time
        budget = 0.4
        names = []
        for i in range(3):
            name, _ = self._install_signed("bound%d" % i)
            self._edit_row(name, source=str(self.tmp / ("src-bound%d" % i)))
            self._detach(name)
            names.append(name)

        guard = self.brain.lock_path.with_name(self.brain.lock_path.name + ".lock")
        guard.parent.mkdir(parents=True, exist_ok=True)
        holder = open(guard, "a+")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)   # a second fd: flock is per ofd

        asked, waits = [], []
        real = octo_pkg.Brain.lock_held

        @contextlib.contextmanager
        def recording(self_, timeout=30.0):
            asked.append(timeout)
            started = time.monotonic()
            try:
                with real(self_, timeout):
                    waits.append(time.monotonic() - started)
                    yield
            except octo_pkg.PkgError:
                waits.append(time.monotonic() - started)
                raise

        octo_pkg.Brain.lock_held = recording
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "lock_held", real))
        prior = octo_pkg.SYNC_LOCK_BUDGET
        octo_pkg.SYNC_LOCK_BUDGET = budget
        self.addCleanup(lambda: setattr(octo_pkg, "SYNC_LOCK_BUDGET", prior))

        rc, said = self._sync()

        self.assertEqual(len(asked), 3, "one acquire per absent package")
        # First, because it is the one that names the bug: a per-acquire timeout hands
        # out the same number three times and a run deadline hands out what is left.
        self.assertEqual(asked[1:], [0.0, 0.0],
                         f"each acquire was handed a fresh budget ({asked}): the bound "
                         f"is per acquire and a run of N absent packages waits N times "
                         f"it, which is the claim the docstring makes and the mechanism "
                         f"does not impose")
        self.assertLessEqual(asked[0], budget)
        self.assertLess(sum(waits), 2 * budget,
                        f"the whole run waited {sum(waits):.2f}s for a lock it was "
                        f"told to wait {budget}s for")
        for name in names:
            self.assertFalse(self.brain.vendor_path(name).exists(),
                             "the lock was held throughout: nothing can be restored")
        self.assertEqual(said.count("could not acquire"), 3)
        self.assertIn("0 restored", said)

    @unittest.skipUnless(_fcntl_ok(), "no fcntl: the POSIX branch is not the one that runs here")
    @unittest.skipUnless(_ssh_ok(), "ssh-keygen -Y unavailable")
    def test_sync_spends_its_budget_on_waiting_and_not_on_fetching(self):
        """The fifteenth instance of the pattern, inside the edit that fixed the
        fourteenth.

        The run bound was first written as an absolute deadline taken before the loop,
        so EVERYTHING in the loop consumed it and the network fetches consume nearly
        all of it, while the docstring promised three times over that "what is bounded
        is the WAITING and only the waiting". QA cycle 16 measured it with NOTHING
        holding the lock and a 1.5s fetch against a 2.0s budget: the acquires were
        handed [0.484, 0.0, 0.0]. A run that waited for nothing arrived at a bare
        non-blocking probe, and at the shipped 30s a fresh clone spends the whole
        budget cloning and then refuses a package to any session holding the lock for
        50ms, where the per-acquire shape would have waited and restored it.

        The contended leg above cannot see this and neither reading is wrong there: it
        holds the lock throughout, so the budget goes to waiting under BOTH semantics
        and `asked[1:] == [0.0, 0.0]` is satisfied by both. This leg is the one where
        they disagree, and it is the uncontended one. Nothing holds the lock and one
        fetch alone outlasts the whole budget: waiting-only hands every acquire the
        full budget and restores all three, an elapsed-time deadline hands out 0.0
        from the first acquire on.
        """
        import contextlib, time
        budget = 0.4
        names = []
        for i in range(3):
            name, _ = self._install_signed("slow%d" % i)
            self._edit_row(name, source=str(self.tmp / ("src-slow%d" % i)))
            self._detach(name)
            names.append(name)

        real_fetch = octo_pkg.fetch_source

        def slow_fetch(*a, **kw):
            time.sleep(budget + 0.2)   # one fetch alone outlasts the whole budget
            return real_fetch(*a, **kw)

        octo_pkg.fetch_source = slow_fetch
        self.addCleanup(lambda: setattr(octo_pkg, "fetch_source", real_fetch))

        asked = []
        real = octo_pkg.Brain.lock_held

        @contextlib.contextmanager
        def recording(self_, timeout=30.0):
            asked.append(timeout)
            with real(self_, timeout):
                yield

        octo_pkg.Brain.lock_held = recording
        self.addCleanup(lambda: setattr(octo_pkg.Brain, "lock_held", real))
        prior = octo_pkg.SYNC_LOCK_BUDGET
        octo_pkg.SYNC_LOCK_BUDGET = budget
        self.addCleanup(lambda: setattr(octo_pkg, "SYNC_LOCK_BUDGET", prior))

        rc, said = self._sync()

        self.assertEqual(len(asked), 3, "one acquire per absent package")
        self.assertGreater(
            min(asked), 0.9 * budget,
            f"nothing held the lock, so this run waited for nothing, and its acquires "
            f"were handed {asked} out of a {budget}s budget: the bound is over elapsed "
            f"time and the fetches are spending it, not over the waiting the docstring "
            f"says it bounds")
        for name in names:
            self.assertTrue(self.brain.vendor_path(name).exists(),
                            "nothing held the lock: every package is restorable")
        self.assertIn("3 restored", said)

    def test_the_identity_labels_are_in_the_order_the_identity_returns(self):
        """Using IDENTITY_FIELDS removed the LENGTH half of the drift risk, not the
        order half. cmd_lock's WARN zips the constant against the tuple, so reordering
        the constant mis-names every field that moved. Each field's name is its own
        value here, so the identity of a row built from the constant IS the constant
        when, and only when, the two agree in order.

        "and no test failed" is what this test was first written against, and QA cycle
        16 measured that it is not true of EVERY reordering, so the claim is narrowed
        to what was measured. Swapping `installed_at` with `tree_sha256` kills three
        tests, two of which already failed at the parent commit for their own reasons.
        The reordering that nothing caught is `kind` with `source`: it survives all 151
        tests at the parent commit and dies only here.
        """
        self.assertEqual(
            octo_pkg.entry_identity({f: f for f in octo_pkg.IDENTITY_FIELDS}),
            octo_pkg.IDENTITY_FIELDS,
            "entry_identity returns its fields in a different order than "
            "IDENTITY_FIELDS labels them: the WARN names the wrong field")


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
        (d / "LICENSE.txt").write_text("Apache License, Version 2.0\n", encoding="utf-8")
        gen.main(["--root", str(self.root), "--write", "--default-license", "MIT"])
        man = json.loads((d / "skill.json").read_text(encoding="utf-8"))
        self.assertEqual(man["license"], "Apache-2.0")


if __name__ == "__main__":
    unittest.main()

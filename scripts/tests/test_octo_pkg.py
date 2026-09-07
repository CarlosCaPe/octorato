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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


octo_pkg = _load("octo_pkg_under_test", SCRIPTS / "octo_pkg.py")
gen = _load("gen_skill_manifests_under_test", SCRIPTS / "gen_skill_manifests.py")


def _ssh_ok() -> bool:
    return shutil.which("ssh-keygen") is not None and octo_pkg.ssh_keygen_y_supported()


class SandboxCase(unittest.TestCase):
    """A brain checkout in a temp dir, with a key minted per test class."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-octo-pkg-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._home = os.environ.get("HOME")
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

    def test_git_dir_ignored(self):
        d = self._pkg()
        before = octo_pkg.tree_sha256(d)
        (d / ".git").mkdir()
        (d / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        self.assertEqual(before, octo_pkg.tree_sha256(d))

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

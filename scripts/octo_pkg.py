#!/usr/bin/env python3
"""octo_pkg.py: the PACKAGE primitive of the v8 kernel.

A skill installed from somewhere else is code the brain runs on every prompt, so it
gets the same treatment a service gets: a manifest with a version, a hash over the
tree, a detached signature, a tracked lockfile, and a verify that runs at doctor and
pre-push time. Without that, "install a skill" means "copy a stranger's directory
into the always-on context and hope".

Subcommands (named so `octo pkg <verb>` can delegate here verbatim once the `octo`
thunk lands in Phase 1b):

  install <source> [--kind skill|arm] [--path P] [--ref R] [--name N] [--dest D]
  verify [<name> ...] [--all] [--json]
  uninstall <name>
  list [--json]
  hash <dir> [--write]
  lock
  sync

`<source>` is a plain directory (the package), a git repository (path or URL), a
GitHub URL, or owner/repo with --path.

Install, for a skill:
  1. stage the source (a local directory, or a GitHub repo via the zip / sparse
     checkout paths of skills/skill-installer/scripts/install-skill-from-github.py)
  2. `skill.json` validates against schemas/skill-manifest.schema.json
  3. the tree hash recomputed over every file except `skill.json` and
     `skill.json.sig` must equal the embedded `tree_sha256`
  4. `ssh-keygen -Y verify -n octorato-pkg` must pass against a principal in
     registry/pkg-signers.pub or the gitignored company/config/pkg-signers
  5. only then is anything copied: to `skills/vendor/<name>` (gitignored), with
     `skills/<name>` as a symlink to it so the runtime's documented discovery path
     (`~/.claude/skills/<name>/SKILL.md`) loads it, and `skills/<name>` appended to
     `.git/info/exclude` (per machine, untracked, so the symlink is not a diff)

Steps 2 to 4 all run in the staging area. A refusal copies nothing. The tree check
runs BEFORE the signature check on purpose: a mismatched tree is a fact about the
bytes on disk and needs no key to establish, and proving that order is one leg of
the selftest.

Arms are validated, not signed: `install --kind arm <git-url>` clones to `--dest`
(or company/config/arms-root), validates `arm.json`, registers the path in
company/config/arms-paths.json and runs sync-ai-docs for it. An arm is the
operator's own repo, not a third party's package, so a signature would only be the
operator signing to himself.

Verify ladder (`verify --all` exits 1 only on the FAIL tier):
  PASS  present, tree hash matches, signature verifies, symlink resolves
  WARN  a lock entry absent on disk (a second machine pulled the lock offline;
        it must still be able to push an unrelated change), or a dangling
        skills/<name> link that points at a vendor tree nobody locked
  FAIL  a present entry whose tree hash, signature or symlink does not match, a lock
        entry whose signer is in no allowed-signers file, an entry whose declared
        kind disagrees with the installed (signed) manifest, or a vendored tree with
        no lock entry at all

`verify --all` is disk-driven as well as lock-driven. The lock is unsigned and tracked,
so it is an input, never the authority: deleting an entry, or editing its `kind`, must
not be able to switch the ladder off for a tree that is still loading on every prompt.
Presence at skills/vendor/<name> is what selects the skill ladder; the installed
manifest, which the signature covers, is what says whether the package is a skill or an
arm. A real arm, with no vendor tree, still PASSes on its lock row alone: arm isolation
means verify never reaches into the arm's own repo.

Selftest: `python3 scripts/octo_pkg.py --selftest registry/fixtures/META.kernel-package`
runs every leg under a throwaway HOME with an ed25519 key generated at run time, so
no private key ever lives in the repo.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

# Force UTF-8 on stdout/stderr so the check glyphs survive on Windows shells that
# start in cp1252. Same preamble as the rest of the brain's scripts.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SIG_NAMESPACE = "octorato-pkg"
MANIFEST_NAME = {"skill": "skill.json", "arm": "arm.json"}
SIG_NAME = "skill.json.sig"
LOCK_REL = "packages.lock.json"
PUBLIC_SIGNERS_REL = "registry/pkg-signers.pub"
PRIVATE_SIGNERS_REL = "company/config/pkg-signers"
ARMS_PATHS_REL = "company/config/arms-paths.json"
ARMS_ROOT_REL = "company/config/arms-root"
VENDOR_REL = "skills/vendor"

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# The schema's own name pattern. Every package name is matched against it at BOTH
# ends: when a manifest is read, and when the lockfile is read. The lock is a tracked
# file, so a name like "../../../escaped" arrives through a normal `git pull` and
# would otherwise be joined onto skills/vendor and written outside the brain.
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# `vendor` is the container the packages live in, so a package called vendor would
# make skills/vendor/vendor and a symlink at skills/vendor over the container itself.
RESERVED_NAMES = {"vendor", "learned"}
GITHUB_HOSTS = {"github.com", "www.github.com"}
REF_FALLBACKS = ("main", "master")

# Env git exports to its hooks. A child `git` that inherits GIT_DIR operates on the
# LIVE repo, not on the throwaway one a selftest built (brain_doctor.py carries the
# same scrub for the same reason).
_GIT_HOOK_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
                 "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH")

# Counts calls to _verify_signature. The selftest asserts it stays at 0 across a
# tampered install: that is the machine proof of the tree-before-signature order,
# which a message-substring assertion could not give.
SIG_VERIFY_CALLS = 0


def valid_name(name: str) -> str:
    """Return the name, or raise. One place, used by the manifest path, the --name
    override and the lockfile reader, so the three cannot drift."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise PkgError(f"invalid package name {name!r}: must match {NAME_RE.pattern}")
    if len(name) < 2 or len(name) > 64:
        raise PkgError(f"invalid package name {name!r}: 2 to 64 characters")
    if name in RESERVED_NAMES:
        raise PkgError(f"package name {name!r} is reserved")
    return name


class PkgError(Exception):
    """Any refusal. Carries a one-line reason; nothing has been copied when raised
    from the install path, because every check runs in the staging area."""


# --------------------------------------------------------------------------
# process helpers
# --------------------------------------------------------------------------

def _env() -> dict:
    e = dict(os.environ)
    for k in _GIT_HOOK_ENV:
        e.pop(k, None)
    return e


def _run(args: list[str], cwd: Path | None = None, stdin_bytes: bytes | None = None):
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        input=stdin_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(),
    )


def ssh_keygen_y_supported() -> bool:
    """True when the local OpenSSH understands `ssh-keygen -Y`. Old Windows OpenSSH
    does not, and the honest answer there is FAIL with an unlock, never a silent
    skip: a verify that cannot check a signature has not checked it."""
    if shutil.which("ssh-keygen") is None:
        return False
    cp = _run(["ssh-keygen", "-Y", "check-novalidate", "-n", SIG_NAMESPACE, "-s", os.devnull],
              stdin_bytes=b"")
    err = (cp.stderr or b"").decode("utf-8", "replace")
    return "unknown option" not in err.lower() and "usage:" not in err.lower()


# --------------------------------------------------------------------------
# the brain under operation
# --------------------------------------------------------------------------

class Brain:
    """The checkout being operated on. Resolved from --brain, then CLAUDE_DIR, then
    the script's own parent, so a selftest drives a sandbox without touching ~/."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # ---- paths -----------------------------------------------------------
    @property
    def lock_path(self) -> Path:
        return self.root / LOCK_REL

    @property
    def vendor_dir(self) -> Path:
        return self.root / VENDOR_REL

    @property
    def schema_path(self) -> Path:
        return self.root / "schemas" / "skill-manifest.schema.json"

    def link_path(self, name: str) -> Path:
        return self.root / "skills" / name

    def vendor_path(self, name: str) -> Path:
        return self.vendor_dir / name

    # ---- git exclude -----------------------------------------------------
    def _exclude_file(self) -> Path | None:
        """`.git/info/exclude` of the COMMON dir. In a worktree `.git` is a file, so
        resolving it by hand would write the exclude into a per-worktree dir where
        git still reads it, but the main checkout would not see it."""
        cp = _run(["git", "rev-parse", "--git-common-dir"], cwd=self.root)
        if cp.returncode != 0:
            return None
        raw = (cp.stdout or b"").decode("utf-8", "replace").strip()
        if not raw:
            return None
        common = Path(raw)
        if not common.is_absolute():
            common = (self.root / common).resolve()
        common = common.resolve()
        # The brain root may sit INSIDE an unrelated enclosing repo (a sandbox under a
        # versioned HOME, a checkout inside another checkout). git would then hand back
        # that outer repo's common dir and we would write an exclude line into a
        # stranger's repository.
        #
        # The test is NOT "is the git dir under the brain root". A git WORKTREE, which
        # is how this brain runs parallel sessions, keeps its common dir back in the
        # main checkout, far outside the worktree; requiring containment silently
        # disabled the exclude in exactly the setup the brain uses most. The right
        # question is whether this repo's work tree IS the brain: if the toplevel is an
        # ancestor rather than the brain itself, the repo belongs to someone else.
        cp = _run(["git", "rev-parse", "--show-toplevel"], cwd=self.root)
        if cp.returncode != 0:
            return None
        top = (cp.stdout or b"").decode("utf-8", "replace").strip()
        if not top or Path(top).resolve() != self.root:
            return None
        return common / "info" / "exclude"

    def _exclude_lines(self, f: Path) -> list[str]:
        """.git/info/exclude, through the seam.

        It is a plain text file that never becomes JSON, so naming the seam after
        JSON left it outside, the same way it left the allowed-signers file outside
        (QA cycles 5 and 6, the same finding twice). It is also written by hand and
        by other tools, and on Windows a cp1252 comment in it is ordinary; that byte
        used to raise UnicodeDecodeError straight through install's unwind, which
        caught only OSError and PkgError, leaving a vendored tree and a live symlink
        in the discovery path with no lock entry.
        """
        if not stat_ok(f.exists, False, str(f)):
            return []
        return read_text(f, str(f)).splitlines()

    def exclude_add(self, rel: str) -> bool:
        f = self._exclude_file()
        if f is None:
            return False
        f.parent.mkdir(parents=True, exist_ok=True)
        lines = self._exclude_lines(f)
        if rel in lines:
            return True
        lines.append(rel)
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    def exclude_remove(self, rel: str) -> bool:
        f = self._exclude_file()
        if f is None or not stat_ok(f.exists, False, str(f)):
            return False
        lines = [ln for ln in self._exclude_lines(f) if ln != rel]
        f.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
        return True

    def exclude_has(self, rel: str) -> bool:
        f = self._exclude_file()
        if f is None:
            return False
        return rel in self._exclude_lines(f)

    # ---- lock ------------------------------------------------------------
    @contextlib.contextmanager
    def lock_held(self, timeout: float = 30.0):
        """Hold an exclusive advisory lock around a whole load-modify-save.

        Two `octo pkg install` runs (two sessions, or a `sync` racing an install) each
        read the lockfile, add their own entry and write the file back. Without this,
        the second write is computed from a snapshot taken before the first, and one
        of the two packages is on disk with no lock entry: it then verifies as an
        untracked stray forever. The lock lives beside the lockfile and is never
        committed.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        guard = self.lock_path.with_name(self.lock_path.name + ".lock")
        fh = open(guard, "a+")
        try:
            try:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except ImportError:
                # No fcntl (Windows): fall back to an O_EXCL sentinel with a timeout,
                # so the contract degrades in speed, never in correctness.
                sentinel = Path(str(guard) + ".excl")
                deadline = time.time() + timeout
                while True:
                    try:
                        fd = os.open(str(sentinel), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        os.close(fd)
                        break
                    except FileExistsError:
                        if time.time() > deadline:
                            raise PkgError(f"could not acquire {sentinel} within {timeout}s")
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    sentinel.unlink(missing_ok=True)
                return
            yield
        finally:
            fh.close()

    def load_lock(self) -> dict:
        """Read and VALIDATE the lockfile. A bad entry refuses the whole file.

        packages.lock.json is tracked, so its contents arrive from a remote like any
        other file. An entry whose name is `../../../escaped` would be joined onto
        skills/vendor by install and sync, and would print PASS at verify because the
        path it resolves to happens to exist. Refusing the file is the only safe
        reading: a lock nobody can trust is not a lock with one bad row.
        """
        if not self.lock_path.exists():
            return {"version": 1, "packages": []}
        data = read_json(self.lock_path, LOCK_REL)
        if not isinstance(data, dict) or not isinstance(data.get("packages"), list):
            raise PkgError(f"{LOCK_REL} is not a lockfile object with a packages list")
        seen = set()
        for i, entry in enumerate(data["packages"]):
            if not isinstance(entry, dict):
                raise PkgError(f"{LOCK_REL} entry {i} is not an object")
            try:
                name = valid_name(entry.get("name"))
            except PkgError as e:
                raise PkgError(f"{LOCK_REL} entry {i}: {e}")
            if name in seen:
                raise PkgError(f"{LOCK_REL} names {name!r} twice")
            seen.add(name)
            if entry.get("kind") not in (None, "skill", "arm"):
                raise PkgError(f"{LOCK_REL} entry {name}: kind must be skill or arm")
            # Every field a consumer treats as a string is type-checked HERE, at the
            # one place the file is read, rather than at each use. `signer` reached a
            # set membership test and a list value raised TypeError; `source` reached
            # .startswith in sync. The lock is tracked and unsigned, so these arrive
            # from a remote like any other file (QA cycle 4).
            for field in ("signer", "source", "tree_sha256", "version"):
                value = entry.get(field)
                if value is not None and not isinstance(value, str):
                    raise PkgError(f"{LOCK_REL} entry {name}: {field} must be a string")
        return data

    def save_lock(self, lock: dict) -> None:
        """Write atomically: a crash mid-write must not leave a truncated lockfile,
        and a concurrent reader must see either the old file or the new one."""
        lock["packages"] = sorted(lock.get("packages", []), key=lambda p: str(p.get("name", "")))
        for entry in lock["packages"]:
            valid_name(entry.get("name"))
        payload = json.dumps(lock, indent=2, ensure_ascii=False) + "\n"
        # Named so the tracked .gitignore's `*.tmp` / `*.lock` patterns cover it: a
        # crash between write and replace must not leave an untracked file that shows
        # in git status and rides along in someone's `git add`.
        tmp = self.lock_path.with_name(f"{self.lock_path.name}.{os.getpid()}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.lock_path)

    # ---- allowed signers -------------------------------------------------
    def signer_files(self) -> list[Path]:
        """Public first, then the adopter's private file. Both are allowed-signers
        files in OpenSSH format: `<principal> <keytype> <base64>`."""
        out = []
        for rel in (PUBLIC_SIGNERS_REL, PRIVATE_SIGNERS_REL):
            p = self.root / rel
            if p.exists():
                out.append(p)
        return out

    def known_principals(self) -> dict[str, Path]:
        """principal -> the allowed-signers file that declares it.

        A file this cannot read is SKIPPED, not fatal. That is deliberate and no
        caller reads an empty set as permissive: every consumer turns an unknown
        signer into a refusal. One measured exception to "it can only shrink the
        set", because the absolute claim is false: principals are first-wins, public
        before private, so a principal declared in BOTH files with different keys
        answers with the private key when the public file is unreadable. Deleting
        the public file does the same thing and always has, since signer_files gates
        on exists, and only someone who can write the gitignored private file can
        reach it, who could add a principal instead. The precedence is a preference,
        not a boundary. Raising here would be worse than useless, because
        `registry/pkg-signers.pub` is tracked: one stray byte in a comment line
        would take down verify for every package at once, which is how QA cycle 5
        found this (the read caught OSError but not the UnicodeDecodeError a
        latin-1 byte raises).
        """
        found: dict[str, Path] = {}
        for f in self.signer_files():
            try:
                text = read_text(f, str(f))
            except PkgError:
                continue
            for ln in text.splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                principal = ln.split()[0]
                # a comma-separated principal list is legal in allowed_signers
                for p in principal.split(","):
                    if p and p not in found:
                        found[p] = f
        return found


def resolve_brain(arg: str | None) -> Brain:
    if arg:
        return Brain(Path(arg))
    env = os.environ.get("CLAUDE_DIR")
    if env:
        return Brain(Path(env))
    return Brain(Path(__file__).resolve().parent.parent)


# --------------------------------------------------------------------------
# tree hash
# --------------------------------------------------------------------------

def _walk_or_fail(root: Path) -> list[Path]:
    """Every path under root, sorted, or PkgError if any directory cannot be listed.

    NOT `rglob`. This is the one crossing seven QA cycles of call-site enumeration
    could not find, because the failure does not happen at the call: `Path.rglob`
    catches the OSError INSIDE pathlib, so a directory the process cannot list
    contributes nothing and never raises. Measured: `chmod 111` on a subdirectory
    makes it unlistable while every file in it stays readable by exact path, so a
    planted script was outside the digest, inside the package, loadable, and
    `verify --all` printed PASS over it. For a tool whose whole job is to say
    whether the bytes on disk are the bytes that were signed, that is the guarantee
    itself, defeated by one chmod.

    `os.walk` with `onerror` is what makes the failure visible: iterdir and scandir
    both raise where rglob swallows, and onerror hands the error over instead of
    skipping the directory silently. A tree this cannot fully enumerate has a hash
    that means nothing, so it never reports one, which is the same rule an
    unreadable FILE already followed.
    """
    problems: list[OSError] = []
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=problems.append,
                                                followlinks=False):
        if problems:
            break
        base = Path(dirpath)
        for name in dirnames + filenames:
            out.append(base / name)
    if problems:
        e = problems[0]
        rel = os.path.relpath(str(getattr(e, "filename", root) or root), str(root))
        raise PkgError(f"package directory cannot be listed ({rel}): {e}")
    return sorted(out)


def tree_sha256(pkg_dir: Path, kind: str = "skill") -> str:
    """Deterministic hash over the package tree.

    Exactly two files are excluded, and only the ones this package kind uses to carry
    the hash: its own manifest (`skill.json` for a skill, `arm.json` for an arm) and
    the detached `skill.json.sig`. Nothing else. An `arm.json` shipped inside a skill
    package is content like any other file and IS hashed: excluding it by filename
    would leave a hole a publisher could hide anything in.

    `.git` is hashed too, deliberately. A `.git` directory inside an installed package
    is not the package: it is a second repository living in the always-on discovery
    path, able to carry hooks and to rewrite the tree. Hashing it means a planted one
    changes the hash and verify goes FAIL, which is the whole point.

    Feeds the digest `<posix relpath>\\0<sha256 of the bytes>\\0<x|->\\0` per file, in
    sorted path order, so a rename is a different hash, a content change is a different
    hash, and a file that BECOMES executable is a different hash. Symlinks inside a
    package are refused rather than followed; a package that points outside itself is
    not a self-contained tree, and so is anything that is neither a directory nor a
    regular file.

    The third field is a normalized boolean, `x` or `-`, never the raw mode. POSIX mode
    bits are not portable and most of them are not a property of the package: the group
    and other bits, the setuid bit and the umask a publisher happened to run under would
    all make the same bytes hash differently on two machines. Owner-execute is the one
    bit that changes what the file IS, because a shipped script silently becoming
    executable is a material change to code that sits in the always-on discovery path.

    What this hash does NOT cover, stated so the next reader does not over-trust it:

      empty directories   a directory carries no bytes and no path of its own in the
                          digest, so adding or removing an EMPTY one is invisible. It
                          also carries nothing: no file, no code, nothing the runtime
                          can load. A non-empty directory IS covered, through the
                          paths of the files inside it, with no exception: an
                          unlistable one is refused outright by _walk_or_fail. The
                          earlier text here said such a directory was skipped and
                          harmless, and both halves were wrong. `chmod 111` leaves
                          every file in it readable by exact path, so the contents
                          were loadable AND outside the digest, and verify printed
                          PASS over them. That was the guarantee failing, not a
                          documented limit.
      timestamps, owner   mtime, uid and gid are not hashed. They are properties of the
                          copy, not of the package, and every copytree rewrites them.
      the mode's other    group, other, setuid, setgid and sticky bits. On the vendor
      bits                path the brain owns the tree; the bit that decides whether a
                          file can run as code is owner-execute, and that is the one.
      the manifest        `skill.json` (or `arm.json`) and `skill.json.sig`, which carry
                          the hash and the signature over it.

    FIFOs, sockets and device nodes are not "not covered": they are REFUSED, the same
    way symlinks are. They used to be skipped by the `is_file()` filter, which meant a
    planted FIFO was invisible to the hash and still sat in the package. A package is a
    tree of regular files; anything else in it is not content this primitive can verify,
    so it is not installed at all.
    """
    import hashlib
    import stat as _stat
    if kind not in MANIFEST_NAME:
        raise PkgError(f"unknown package kind {kind!r}")
    excluded = {MANIFEST_NAME[kind], SIG_NAME}
    h = hashlib.sha256()
    files = []
    for p in _walk_or_fail(pkg_dir):
        rel = p.relative_to(pkg_dir)
        if p.is_symlink():
            raise PkgError(f"package contains a symlink ({rel.as_posix()}); "
                           "a package tree must be self-contained")
        if p.is_dir():
            continue
        if not p.is_file():
            # A FIFO blocks the reader that opens it, a device node is not content at
            # all, and both used to fall through the old `if not p.is_file(): continue`
            # into the tree unhashed. Refusing is the honest answer: nothing here can
            # say what those bytes are, so nothing here should claim to have checked
            # them.
            raise PkgError(f"package contains a non-regular file ({rel.as_posix()}); "
                           "a package tree is directories and regular files only")
        if rel.as_posix() in excluded:
            continue
        files.append((rel.as_posix(), p))
    for rel_posix, p in files:
        h.update(rel_posix.encode("utf-8"))
        h.update(b"\0")
        try:
            payload = p.read_bytes()
            mode = p.stat().st_mode
        except OSError as e:
            # This function already speaks PkgError for a symlink and for a FIFO, so
            # a file it cannot read belongs in the same vocabulary. Raising OSError
            # instead sent the raw exception through three callers that catch only
            # PkgError: hash, lock and install each turned an unreadable file into a
            # traceback (QA cycle 5). One raise here beats three except clauses, and
            # it keeps the rule intact: a tree this cannot fully read is a tree whose
            # hash means nothing, so it never reports a digest at all.
            raise PkgError(f"package file cannot be read ({rel_posix}): {e}")
        h.update(hashlib.sha256(payload).hexdigest().encode("ascii"))
        h.update(b"\0")
        # Windows has no POSIX exec bit; CPython synthesizes one from the extension
        # (.exe, .bat, .cmd, .com), so a package whose hash was computed on Linux can
        # differ when recomputed on Windows for exactly those files. That residual is
        # named here rather than papered over with a platform branch: a hash that is
        # computed differently per platform is worse than one whose limits are written
        # down, and the brain publishes packages from POSIX.
        h.update(b"x" if mode & _stat.S_IXUSR else b"-")
        h.update(b"\0")
    return h.hexdigest()


# --------------------------------------------------------------------------
# manifest + signature
# --------------------------------------------------------------------------

def read_json(path: Path, label: str):
    """Read one JSON file, or raise PkgError. The ONLY way this module parses JSON.

    Four QA cycles in a row found the same shape: another input class escaping as a
    traceback instead of a reported failure. First an unhashable `kind`, then a
    manifest that parses but is not an object, then invalid UTF-8, 200k nested
    brackets, an unreadable directory, then a latin-1 byte in the allowed-signers
    file, which never becomes JSON at all. Catching them one at a time loses to the
    next one nobody thought of, so the fix is a seam rather than a longer except
    clause. The seam is `read_text`: everything that can go wrong turning bytes on
    disk into a Python value comes back as PkgError, which every caller already
    reports as a FAIL naming the package.

    OSError covers the file (missing, unreadable, a directory, EIO) and ValueError
    the bytes, both in read_text. Here RecursionError is added, because deep nesting
    reaches it before the parser gives up and it is neither of those. The shape is
    NOT checked: `[]` and `42` are valid JSON, and what a given caller needs is the
    caller's business.
    """
    return _parse_json(read_text(path, label), label)


def read_text(path: Path, label: str) -> str:
    """Read one text file, or raise PkgError. The seam is BYTES to value, not JSON.

    QA cycle 5 found the eighth of the same shape by enumerating rather than
    guessing: `known_principals` read the tracked allowed-signers file with an
    `except OSError` and no ValueError, so one latin-1 byte in a comment line of
    `registry/pkg-signers.pub` raised UnicodeDecodeError out of the whole sweep.
    That file never becomes JSON, which is exactly why naming the seam after JSON
    left it outside. The boundary this module actually has is external bytes
    turning into a Python value, and every crossing of it belongs here.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        raise PkgError(f"{label} cannot be read: {type(e).__name__}: {e}")


def resolve_or_fail(path: Path, label: str) -> Path:
    """`Path.resolve()`, or PkgError. The third crossing family, and the last.

    pathlib turns a symlink loop into a RuntimeError, not an OSError, so
    "filesystem crossing" and "OSError" are not the same set even inside the
    standard library. QA found that at one call site, the fix named that site, and
    the next cycle found the identical bug one verb over in `hash`. That is the
    losing move this file has already made six times, so `.resolve()` joins
    `read_text` and `stat_ok` as a seam instead: the family is closed rather than
    the instance.
    """
    try:
        return path.resolve()
    except (OSError, RuntimeError) as e:
        raise PkgError(f"{label} cannot be resolved: {type(e).__name__}: {e}")


def read_bytes(path: Path, label: str) -> bytes:
    """The same seam for bytes. No decode, so no ValueError to catch."""
    try:
        return path.read_bytes()
    except OSError as e:
        raise PkgError(f"{label} cannot be read: {type(e).__name__}: {e}")


def stat_ok(fn, default, label: str):
    """Run one stat-family call, or turn its OSError into PkgError.

    `default` is what an ABSENT path answers, and it is passed rather than assumed
    because the callers disagree: `exists` wants False, `is_dir` wants False, and a
    caller that must know the difference passes None. What this never does is answer
    the default for a path it could not stat. pathlib swallows ENOENT and ENOTDIR
    itself and raises EACCES, and six cycles of QA all landed on the same fact: not
    knowing what is on disk is a failure to report, never a pass.
    """
    try:
        return fn()
    except OSError as e:
        raise PkgError(f"{label} cannot be read: {type(e).__name__}: {e}")


def _parse_json(text: str, label: str):
    try:
        return json.loads(text)
    except (ValueError, RecursionError) as e:
        raise PkgError(f"{label} does not parse: {type(e).__name__}: {e}")


def load_manifest(pkg_dir: Path, kind: str) -> tuple[Path, dict]:
    mpath = pkg_dir / MANIFEST_NAME[kind]
    try:
        is_file = mpath.is_file()
    except OSError as e:
        # is_file swallows ENOENT and ENOTDIR, not EACCES: a mode-000 package
        # DIRECTORY raised PermissionError from the stat itself, outside every
        # try in the caller (QA cycle 4).
        raise PkgError(f"{MANIFEST_NAME[kind]} in {pkg_dir} cannot be read: {e}")
    if not is_file:
        raise PkgError(f"{MANIFEST_NAME[kind]} not found in {pkg_dir}")
    return mpath, read_json(mpath, MANIFEST_NAME[kind])


def validate_manifest(brain: Brain, mpath: Path) -> None:
    """Validate against schemas/skill-manifest.schema.json, reusing the validator
    of scripts/validate-skill-manifest.py rather than a second copy of the logic."""
    if not brain.schema_path.exists():
        raise PkgError(f"manifest schema missing at {brain.schema_path}")
    try:
        from jsonschema import Draft202012Validator
    except ImportError as e:
        raise PkgError(
            f"jsonschema is not importable ({e}); a manifest cannot be validated and "
            f"an unvalidated manifest is never installed. Install it: "
            f"python3 -m pip install --user jsonschema (it is in requirements.txt)")
    schema = read_json(brain.schema_path, "the manifest schema")
    validator = Draft202012Validator(schema)
    data = read_json(mpath, mpath.name)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(map(str, first.path)) or "<root>"
        raise PkgError(f"{mpath.name} invalid: {where}: {first.message}")


def _verify_signature(brain: Brain, mpath: Path, sig_path: Path) -> str:
    """Return the principal whose allowed-signers entry verified the manifest.

    The signature covers the manifest bytes, and the manifest carries the tree hash,
    so a valid signature over a manifest whose hash matches the tree is a signature
    over the tree.
    """
    global SIG_VERIFY_CALLS
    SIG_VERIFY_CALLS += 1
    if not sig_path.is_file():
        raise PkgError(f"{sig_path.name} not found: unsigned packages are refused")
    if not ssh_keygen_y_supported():
        raise PkgError("ssh-keygen -Y is not supported by the local OpenSSH; "
                       "signature cannot be checked (install OpenSSH >= 8.2)")
    principals = brain.known_principals()
    if not principals:
        raise PkgError(f"no allowed-signers file: add {PUBLIC_SIGNERS_REL} "
                       f"or {PRIVATE_SIGNERS_REL}")
    payload = read_bytes(mpath, mpath.name)
    last = ""
    for principal, signers_file in principals.items():
        cp = _run(["ssh-keygen", "-Y", "verify", "-f", str(signers_file),
                   "-I", principal, "-n", SIG_NAMESPACE, "-s", str(sig_path)],
                  stdin_bytes=payload)
        if cp.returncode == 0:
            return principal
        last = (cp.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        last = last[0]
    raise PkgError(f"signature does not verify for any known principal "
                   f"({', '.join(sorted(principals))}): {last}")


def check_package(brain: Brain, pkg_dir: Path, kind: str) -> dict:
    """Run the three pre-copy checks in order and return the manifest.

    Order is load-and-validate, then tree, then signature. A tampered tree is
    refused with no key involved at all.
    """
    mpath, manifest = load_manifest(pkg_dir, kind)
    validate_manifest(brain, mpath)
    if kind == "arm":
        # arms are validated, not signed: the operator's own repo, not a third
        # party's package. A hash over a live working tree would be meaningless.
        return manifest
    embedded = manifest.get("tree_sha256")
    if not embedded:
        raise PkgError(f"{mpath.name} carries no tree_sha256; an unhashed tree cannot be verified")
    actual = tree_sha256(pkg_dir, "skill")
    if actual != embedded:
        raise PkgError(f"tree_sha256 mismatch: manifest says {embedded[:12]}, "
                       f"tree hashes to {actual[:12]}")
    manifest["_signer"] = _verify_signature(brain, mpath, pkg_dir / SIG_NAME)
    return manifest


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def _is_git_repo(path: Path) -> bool:
    """A checkout (has .git) or a bare repo (has HEAD + objects)."""
    return (path / ".git").exists() or ((path / "HEAD").is_file() and (path / "objects").is_dir())


def _is_local_source(source: str) -> bool:
    """A LOCAL PACKAGE directory: a directory that is not itself a git repository.

    The distinction matters. A plain directory is the package, used in place. A
    directory that IS a repo is a git source and goes through the clone path, exactly
    like a remote URL, so the same code runs whether the repo is across the network or
    on the next disk over."""
    p = Path(os.path.expanduser(source))
    return p.is_dir() and not _is_git_repo(p)


def _github_module():
    """Import the installer's fetch helpers lazily: they pull in github_utils, and a
    local-path install must not need the network path to exist at all.

    sys.modules registration is NOT optional. install-skill-from-github.py carries
    `from __future__ import annotations` and dataclasses; the dataclass machinery
    resolves the module by name through sys.modules while the module body is still
    executing, so a module that is not registered raises KeyError there and every
    GitHub install died with a misleading 'cannot load installer helpers'.
    """
    import importlib.util
    here = Path(__file__).resolve().parent.parent
    mod_path = here / "skills" / "skill-installer" / "scripts" / "install-skill-from-github.py"
    if not mod_path.exists():
        raise PkgError(f"installer helpers not found at {mod_path}")
    name = "_octo_gh_install"
    if name in sys.modules:
        return sys.modules[name]
    if str(mod_path.parent) not in sys.path:
        sys.path.insert(0, str(mod_path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, mod_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        sys.modules.pop(name, None)
        raise PkgError(f"cannot load installer helpers: {e}")


# owner/repo: two path-ish segments, no scheme and no host. Anything else that is not
# already a URL is treated as a bare host form and gets a scheme so it can be PARSED,
# never so it can be trusted: the host check still runs on the parsed netloc.
_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


def _as_url(source: str) -> str:
    """Turn any accepted remote source spelling into a URL, without judging the host."""
    if urlsplit(source).scheme:
        return source
    if _OWNER_REPO_RE.match(source):
        return f"https://github.com/{source}"
    return f"https://{source}"


def parse_github_url(url: str, subpath: str | None = None, ref: str | None = None):
    """(owner, repo, ref, path) from a GitHub URL.

    Host check is on the parsed netloc, never on a substring of the URL: an
    `https://github.com.evil.test/o/r` or an `https://x/?u=github.com/o/r` both carry
    the literal 'github.com' and neither is GitHub (CodeQL
    py/incomplete-url-substring-sanitization).

    A branch name may contain slashes (`feat/v8/kernel`), and `/tree/<ref>/<path>`
    gives no delimiter between the two. So: when --path is supplied, EVERYTHING after
    /tree/ is the ref, which is exact. Only without --path do we fall back to the
    one-segment-ref guess, and say so when it fails.
    """
    parts = urlsplit(url)
    if parts.netloc.lower() not in GITHUB_HOSTS:
        raise PkgError(f"not a GitHub URL: host {parts.netloc!r} is not github.com")
    seg = [s for s in parts.path.split("/") if s]
    if len(seg) < 2:
        raise PkgError("GitHub URL must be /<owner>/<repo>[/tree/<ref>/<path>]")
    owner, repo = seg[0], seg[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    url_ref, url_path = None, None
    if len(seg) > 2:
        if seg[2] in ("tree", "blob"):
            rest = seg[3:]
            if not rest:
                raise PkgError("GitHub URL missing ref after /tree/")
            if subpath:
                # `--path` given: the path is known exactly, so the ref is whatever is
                # left. The common shape is a full browser URL that ALREADY ends with
                # that path (the wiki's own install line), so strip the tail when it
                # matches; only when it does not is the whole tail the ref, which is
                # the branch-with-slashes case that has no other delimiter.
                sub_seg = [s for s in subpath.split("/") if s]
                if len(rest) > len(sub_seg) and rest[-len(sub_seg):] == sub_seg:
                    url_ref = "/".join(rest[:-len(sub_seg)])
                else:
                    url_ref = "/".join(rest)
            else:
                # No --path: the ref/path boundary is genuinely ambiguous, so take the
                # single-segment ref, which is what a browser URL for a plain branch
                # looks like. A branch with slashes needs --path to be unambiguous.
                url_ref, url_path = rest[0], "/".join(rest[1:]) or None
        else:
            url_path = "/".join(seg[2:])
    return owner, repo, (ref or url_ref), (subpath or url_path)


def _split_source_spec(source: str) -> tuple[str, str | None, str | None]:
    """Split a lock `source` back into (source, subpath, ref).

    The ref is NOT optional to carry. A package installed from a tag or a maintenance
    branch records that ref; dropping it made `sync` refetch at main/master, where the
    tree hash differs, so the package was reported unrestorable forever and the WARN
    never cleared. A plain local package directory has neither subpath nor ref: the
    directory IS the package.
    """
    if source.startswith("git+file://"):
        head, _, sub_path = source.partition("#")
        head = head[len("git+file://"):]
        ref = None
        if "@" in head:
            head, ref = head.rsplit("@", 1)
        return head, (sub_path or None), (ref or None)
    return source, None, None


def _sparse_checkout(gh, repo_url: str, ref: str | None, path: str, tmp: Path) -> tuple[Path, str]:
    """Sparse-checkout `path` at `ref`, trying the default branch names when the
    caller did not pin one. `--ref` unset used to mean literally "main", so a repo
    whose default branch is master failed with a confusing clone error."""
    refs = [ref] if ref else list(REF_FALLBACKS)
    errors = []
    for candidate in refs:
        d = tmp / f"co-{candidate.replace('/', '_')}"
        d.mkdir(parents=True, exist_ok=True)
        try:
            root = gh._git_sparse_checkout(repo_url, candidate, [path], str(d))
            return Path(root), candidate
        except Exception as e:
            errors.append(f"{candidate}: {e}")
    raise PkgError("fetch failed, no usable ref (" + "; ".join(errors) + ")")


def fetch_source(source: str, subpath: str | None, ref: str | None, tmp: Path) -> tuple[Path, str]:
    """Stage the package into tmp. Returns (package dir, normalized source string).

    Three source shapes, one code path each:
      a plain directory        the package itself, used in place, never mutated
      a git repo (path or URL) cloned with the sparse-checkout helper of
                               install-skill-from-github.py
      owner/repo or a GitHub URL   the zip path first, git as fallback (same helper)

    A local git repo goes through the SAME clone code as a remote one on purpose: it
    is what lets the git path be exercised without a network, so the code that runs in
    the test is the code that runs against GitHub.
    """
    if _is_local_source(source):
        root = resolve_or_fail(Path(os.path.expanduser(source)), source)
        pkg = (root / subpath) if subpath else root
        if not pkg.is_dir():
            raise PkgError(f"package path not found: {pkg}")
        return pkg, str(pkg)

    gh = _github_module()

    local_repo = Path(os.path.expanduser(source))
    if local_repo.is_dir() and _is_git_repo(local_repo):
        if not subpath:
            raise PkgError("a git repository source needs --path")
        gh._validate_relative_path(subpath)
        repo_root, used = _sparse_checkout(gh, str(local_repo.resolve()), ref, subpath, tmp)
        pkg = repo_root / subpath
        if not pkg.is_dir():
            raise PkgError(f"path {subpath} not found in {local_repo}@{used}")
        return pkg, f"git+file://{local_repo.resolve()}@{used}#{subpath}"

    # Normalize to a URL, then let parse_github_url's urlsplit().netloc make the ONLY
    # host decision. The earlier version answered the same question twice: once by
    # scanning the raw string for a scheme separator and a host prefix, once by
    # parsing. The scan was the weaker of the two and it decided the branch, so
    # https://evil.test/github.com/x and github.com.evil.test/o/r both reached the
    # GitHub path. That is exactly the incomplete-URL-sanitization shape CodeQL
    # flags. One decision, made by a parser, is the fix.
    owner, repo, gref, path = parse_github_url(_as_url(source), subpath, ref)
    if not path:
        raise PkgError("a GitHub source needs --path (or a /tree/<ref>/<path> URL)")
    gh._validate_relative_path(path)

    last = None
    for candidate in ([gref] if gref else list(REF_FALLBACKS)):
        src = gh.Source(owner=owner, repo=repo, ref=candidate, paths=[path])
        try:
            repo_root = Path(gh._prepare_repo(src, "auto", str(tmp)))
        except Exception as e:
            last = f"{candidate}: {e}"
            continue
        pkg = repo_root / path
        if not pkg.is_dir():
            raise PkgError(f"path {path} not found in {owner}/{repo}@{candidate}")
        return pkg, f"https://github.com/{owner}/{repo}/tree/{candidate}/{path}"
    raise PkgError(f"fetch failed: {last}")


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------

def install_skill(brain: Brain, source: str, subpath: str | None, ref: str,
                  name_override: str | None) -> int:
    with tempfile.TemporaryDirectory(prefix="octo-pkg-") as td:
        tmp = Path(td)
        pkg, norm_source = fetch_source(source, subpath, ref, tmp)
        manifest = check_package(brain, pkg, "skill")
        name = valid_name(name_override or manifest["name"])

        dest = brain.vendor_path(name)
        link = brain.link_path(name)
        if dest.exists() or dest.is_symlink():
            raise PkgError(f"already installed: {dest} (uninstall first)")
        if link.exists() or link.is_symlink():
            raise PkgError(f"skills/{name} already exists and is not ours; refusing to replace it")

        # Everything above this line is a check in the staging area. Nothing on the
        # brain has been touched yet, so a refusal leaves no half-install. Everything
        # BELOW is unwound on any failure for the same reason: a tree on disk with no
        # symlink and no lock entry is an unverifiable stray, and it would sit in the
        # discovery path unnoticed.
        excluded = False
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(pkg, dest, symlinks=False)
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.path.relpath(dest, link.parent), link, target_is_directory=True)
            excluded = brain.exclude_add(f"skills/{name}")
            with brain.lock_held():
                lock = brain.load_lock()
                lock["packages"] = [p for p in lock["packages"] if p.get("name") != name]
                lock["packages"].append({
                    "name": name,
                    "kind": "skill",
                    "version": manifest["version"],
                    "tree_sha256": manifest["tree_sha256"],
                    "signer": manifest["_signer"],
                    "source": norm_source,
                    "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })
                brain.save_lock(lock)
        except BaseException as e:
            # BaseException, and the width is the point. The docstring above promises
            # that everything below the staging line is unwound on ANY failure, and
            # `(OSError, PkgError)` did not keep that promise: a UnicodeDecodeError
            # out of .git/info/exclude walked straight past it and left a vendored
            # tree with a live symlink and no lock entry, which is the exact state
            # scan_unlocked calls the most dangerous of all (QA cycle 6). A
            # KeyboardInterrupt mid-install has the same consequence, so it unwinds
            # too. Nothing is swallowed: PkgError carries the reason out, and
            # anything that is not an Exception is re-raised after the cleanup, so a
            # Ctrl-C still stops the program.
            # The WHOLE cleanup is wrapped, not just the exclude call. A bare stat
            # in here can raise on a tree that became unreadable mid-install, and
            # then the unwind does not happen AND the original cause is lost, which
            # is the state this handler exists to prevent (QA cycle 7, reachable
            # only by injection but written down rather than assumed).
            try:
                if link.is_symlink():
                    link.unlink()
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                brain.exclude_remove(f"skills/{name}")
            except (OSError, PkgError):
                pass          # the cleanup is what failed; do not mask the cause
            if not isinstance(e, Exception):
                raise
            raise PkgError(f"install of {name} rolled back: {type(e).__name__}: {e}")

    print(f"installed {name} {manifest['version']} (signer {manifest['_signer']})")
    print(f"  tree     {brain.vendor_path(name)}")
    print(f"  link     {brain.link_path(name)} -> {VENDOR_REL}/{name}")
    if excluded:
        print(f"  excluded skills/{name} in .git/info/exclude (per machine, untracked)")
    else:
        print("  note: .git/info/exclude not written (not a git checkout); "
              "the symlink will show in git status")
    return 0


def install_arm(brain: Brain, source: str, dest: str | None) -> int:
    """Clone an arm, validate arm.json, register it, sync its AI docs.

    Arms are validated, not signed (v8 decision 2): an arm is the operator's own
    sealed repo. What matters is that it is shaped like an arm and that the brain
    knows where it is.
    """
    if dest:
        target = resolve_or_fail(Path(os.path.expanduser(dest)), dest)
    else:
        root_file = brain.root / ARMS_ROOT_REL
        if not root_file.exists():
            raise PkgError(f"no --dest and no {ARMS_ROOT_REL}; say where the arm goes")
        root = Path(os.path.expanduser(read_text(root_file, str(root_file)).strip()))
        target = (root / Path(source.rstrip("/")).name.removesuffix(".git")).resolve()
    if target.exists():
        raise PkgError(f"destination already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if _is_local_source(source):
        cp = _run(["git", "clone", str(Path(os.path.expanduser(source)).resolve()), str(target)])
    else:
        cp = _run(["git", "clone", source, str(target)])
    if cp.returncode != 0:
        raise PkgError("clone failed: " + (cp.stderr or b"").decode("utf-8", "replace").strip())

    try:
        mpath, manifest = load_manifest(target, "arm")
        validate_manifest(brain, mpath)
        if manifest.get("kind") != "arm":
            raise PkgError("arm.json must declare kind: arm")
    except PkgError:
        shutil.rmtree(target, ignore_errors=True)
        raise

    name = manifest["name"]
    cfg = brain.root / ARMS_PATHS_REL
    arms = {}
    if cfg.exists():
        arms = read_json(cfg, ARMS_PATHS_REL)
        if not isinstance(arms, dict):
            raise PkgError(f"{ARMS_PATHS_REL} is not an object; fix it before registering an arm")
    try:
        rel = str(target.relative_to(Path.home()))
    except ValueError:
        rel = str(target)
    arms[name] = rel
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(arms, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lock = brain.load_lock()
    lock["packages"] = [p for p in lock["packages"] if p.get("name") != name]
    lock["packages"].append({
        "name": name,
        "kind": "arm",
        "version": manifest["version"],
        "tree_sha256": None,
        "signer": None,
        "source": source,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    brain.save_lock(lock)

    sync_script = brain.root / "scripts" / "ai_sync.py"
    if sync_script.exists():
        _run([sys.executable or "python3", str(sync_script), "sync", name], cwd=brain.root)
    print(f"installed arm {name} {manifest['version']} at {target}")
    print(f"  registered in {ARMS_PATHS_REL} (validated, not signed)")
    return 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def installed_kind(dest: Path) -> str | None:
    """What the INSTALLED tree says it is, or None when it says nothing readable.

    The manifest bytes are what the signature covers, so the manifest is the authority
    on a package's kind. `packages.lock.json` is not: it is tracked, unsigned, and
    arrives from a remote like any other file.

    A tree carrying both manifests answers from `skill.json`, because that is the one
    the signature and the tree hash are built around; the extra `arm.json` is content
    and is hashed as such (see tree_sha256).
    """
    for kind in ("skill", "arm"):
        mpath = dest / MANIFEST_NAME[kind]
        try:
            if not mpath.is_file():
                continue
        except OSError:
            # a mode-000 package directory: the stat itself raises EACCES, which
            # is_file does not swallow. Nothing readable says what this tree is.
            return None
        try:
            data = read_json(mpath, MANIFEST_NAME[kind])
        except PkgError:
            return None
        if not isinstance(data, dict):
            # `[]`, `"skill"`, `42` and `null` all parse as JSON. A manifest that is
            # not an object says nothing readable about its kind, and .get would
            # raise on it. Verify never raises: an unreadable manifest is a FAIL
            # the caller reports, not a traceback that loses the rest of the sweep.
            return None
        declared = data.get("kind")
        # isinstance first: `in` on a dict hashes the value, and a crafted list or
        # dict in `kind` would raise TypeError. A non-string kind is unreadable,
        # which is what None means here.
        if isinstance(declared, str) and declared in MANIFEST_NAME:
            # What the manifest DECLARES wins over the file it was written into. A
            # skill.json saying `"kind": "arm"` is answered as an arm and fails the
            # comparison below, rather than being read as a skill because of its name.
            return declared
        if declared is None:
            # schemas/skill-manifest.schema.json: "Absent means skill", and the same
            # default applied to arm.json is the file's own kind.
            return kind
        return None
    return None


def _skill_ladder(brain: Brain, entry: dict, dest: Path) -> list[str]:
    """Every check a PRESENT vendored tree must pass. Returns the problems it found.

    Split out of verify_entry so it can be run unconditionally on a tree that exists,
    whatever the lock's `kind` claims. It is a list and not an early return because a
    contradiction (lock says arm, tree is vendored) and a tamper are two facts about the
    same entry, and reporting only the first hides the second from whoever reads the
    failure.
    """
    name = str(entry.get("name") or "?")
    problems: list[str] = []

    signer = entry.get("signer")
    if not signer:
        problems.append("lock entry carries no signer")
    elif signer not in brain.known_principals():
        problems.append(f"signer '{signer}' is in no allowed-signers file")

    link = brain.link_path(name)
    if not link.is_symlink():
        problems.append(f"skills/{name} is not a symlink to {VENDOR_REL}/{name}")
    else:
        expected = os.path.relpath(dest, link.parent)
        actual_link = os.readlink(link)
        # readlink, not resolve: resolve() reports where the link ENDS UP, so a link
        # rewritten to an absolute path outside the brain that happens to hold a copy of
        # the tree would compare equal. The stored target itself has to be ours.
        if actual_link != expected:
            problems.append(f"skills/{name} points at {actual_link!r}, expected {expected!r}")
        elif link.resolve() != dest.resolve():
            problems.append(f"skills/{name} resolves to {link.resolve()}, not {dest}")

    try:
        actual = tree_sha256(dest, "skill")
    except (PkgError, OSError) as e:
        # Without a hash nothing downstream means anything: the signature covers a
        # manifest that carries a hash, and there is none to compare it to.
        problems.append(str(e))
        return problems
    if actual != entry.get("tree_sha256"):
        problems.append(f"tree changed since install "
                        f"(lock {str(entry.get('tree_sha256'))[:12]}, disk {actual[:12]})")

    try:
        mpath, manifest = load_manifest(dest, "skill")
        if not isinstance(manifest, dict):
            problems.append("installed manifest is not a JSON object")
            return problems
        if manifest.get("tree_sha256") != actual:
            problems.append("installed manifest tree_sha256 does not match its own tree")
        got = _verify_signature(brain, mpath, dest / SIG_NAME)
        if got != signer:
            problems.append(f"signed by '{got}', lock says '{signer}'")
    except (PkgError, OSError) as e:
        problems.append(str(e))
    return problems


def lock_kind(entry: dict) -> str:
    """What a lock entry says it is, with the schema's default applied ONCE.

    `schemas/skill-manifest.schema.json` says absent means skill, and three readers
    disagreed about that: verify applied the default, sync and lock compared to
    "skill" directly and therefore skipped an entry with no `kind`. The visible
    effect was a prescription that does nothing: verify printed `absent on disk,
    fix: sync`, and sync skipped that entry forever (QA cycle 8). One default, one
    place.
    """
    return str(entry.get("kind") or "skill")


def verify_entry(brain: Brain, entry: dict) -> tuple[str, str]:
    """Return (status, message) for one lock entry. Never raises.

    The lock's `kind` is NEVER load-bearing on its own. packages.lock.json is tracked
    and unsigned, so one edited field arrives through an ordinary `git pull`; when
    `kind: arm` short-circuited straight to PASS, that single edit switched the whole
    ladder off for a tampered tree still sitting in the always-on discovery path. Two
    rules replace it, and they hold in both directions:

      1. a tree at skills/vendor/<name> means the full skill ladder RUNS, whatever the
         lock says, because the code is loadable either way
      2. what the package IS comes from the installed manifest, which the signature
         covers, and a disagreement with the lock is a FAIL naming both values

    A real arm entry, with no vendor tree, still PASSes: an arm lives in its own sealed
    repo and verify does not reach in (arm isolation). That is why presence on disk, not
    the declared kind, is what selects the ladder.
    """
    name = str(entry.get("name") or "?")
    declared_kind = lock_kind(entry)
    dest = brain.vendor_path(name)

    try:
        on_disk_is_link = dest.is_symlink()
        on_disk_exists = dest.exists()
    except OSError as e:
        # The guard on `is_file` inside load_manifest was one directory too deep:
        # when the CONTAINER skills/vendor is unreadable, the stat raises here
        # instead, and here it aborted the whole sweep rather than one entry.
        # Not knowing what is on disk is a failure to report, never a pass.
        return FAIL, f"{name}: {VENDOR_REL}/{name} cannot be read: {e}"

    if on_disk_is_link:
        # The vendor entry itself must be a real directory. A symlink there means the
        # hashed bytes live somewhere nobody verified, and resolve() would happily
        # follow it and report PASS on a tree that is not the package.
        return FAIL, f"{name}: {VENDOR_REL}/{name} is a symlink, not the package tree"

    if not on_disk_exists:
        if declared_kind == "arm":
            # arms are not vendored into the brain; presence is the arm repo's own
            # business (arm isolation). The lock records them, verify does not reach in.
            return PASS, f"{name}: arm registered (validated, not signed)"
        signer = entry.get("signer")
        if not signer:
            return FAIL, f"{name}: lock entry carries no signer"
        if signer not in brain.known_principals():
            return FAIL, f"{name}: signer '{signer}' is in no allowed-signers file"
        return WARN, f"{name}: absent on disk"

    problems: list[str] = []
    on_disk = installed_kind(dest)
    if on_disk is None:
        problems.append(f"{VENDOR_REL}/{name} exists but declares no readable kind; "
                        f"nothing there says what this tree is")
    elif on_disk != declared_kind:
        problems.append(f"installed manifest says kind '{on_disk}', "
                        f"{LOCK_REL} says '{declared_kind}'")
    if declared_kind == "arm":
        # Both may even agree that it is an arm, and it is still wrong: an arm is a
        # repo of the operator's own, cloned to its own path and registered in
        # arms-paths.json. A copy of one under skills/vendor is a directory in the
        # discovery path that nothing hashed and nothing signed.
        problems.append(f"{LOCK_REL} says arm, yet {VENDOR_REL}/{name} exists; "
                        f"an arm is never vendored into the brain")
    problems += _skill_ladder(brain, entry, dest)

    if problems:
        return FAIL, f"{name}: " + "; ".join(problems)
    return PASS, f"{name} {entry.get('version')}: tree, signature and symlink match"


def scan_unlocked(brain: Brain, locked: set[str]) -> list[tuple[str, str]]:
    """Walk skills/vendor on DISK and report what the lock does not name.

    verify used to be lock-driven only, which made the most dangerous state of all
    invisible: delete an entry from packages.lock.json, leave the vendored tree and its
    skills/<name> symlink alone, and verify answered pass 0, fail [], ok true. Both
    paths are gitignored and the symlink sits in .git/info/exclude, so `git status` had
    nothing to say either, and the tree kept loading on every prompt. A lock is only a
    manifest of what SHOULD be there; the disk is what actually runs.

    Two shapes, two tiers:

      FAIL  a directory (or a symlink) at skills/vendor/<name> with no lock entry. That
            is loadable code nobody signed for, in the always-on discovery path. It is
            the whole finding.
      WARN  a dangling skills/<name> symlink into a vendor tree that does not exist.
            Deliberately not a FAIL: a broken link resolves to nothing, so the runtime
            loads no code from it. It is litter from a half-removed install, and
            blocking a push over litter would train the operator to bypass the gate.
            It is still reported, because nothing else cleans it up: `sync` only unlinks
            a dangling link when a lock entry asks for a restore, and there is none.

    A plain FILE dropped into skills/vendor is ignored: the discovery path loads
    skills/<name>/SKILL.md, so a loose file there is not a package and inventing a
    failure for it would be noise.
    """
    results: list[tuple[str, str]] = []
    seen_trees: set[str] = set()
    try:
        entries = sorted(brain.vendor_dir.iterdir()) if brain.vendor_dir.is_dir() else []
    except OSError as e:
        # An unreadable skills/vendor is the sweep's blind spot, not its absence:
        # trees can be sitting in the always-on discovery path where nothing can
        # enumerate them. Saying so is the only honest answer, and it must not
        # abort the per-entry results already collected (QA cycle 5).
        entries = []
        results.append((FAIL, f"{VENDOR_REL} cannot be listed ({e}); "
                              f"an unlocked package there would be invisible"))
    for p in entries:
        if p.name in locked:
            continue
        if not (p.is_dir() or p.is_symlink()):
            continue
        seen_trees.add(p.name)
        results.append((FAIL, f"{p.name}: {VENDOR_REL}/{p.name} is on disk with no "
                              f"{LOCK_REL} entry (unlocked package at {p})"))

    skills_dir = brain.root / "skills"
    try:
        links = sorted(skills_dir.iterdir()) if skills_dir.is_dir() else []
    except OSError as e:
        # The same guard as the vendor loop above. Cycle 5's diagnosis was that the
        # EACCES check sat one directory too deep; the fix moved it up one level and
        # stopped there, which is how this survived to cycle 6.
        links = []
        results.append((FAIL, f"skills/ cannot be listed ({e}); a stray link there "
                              f"would be invisible"))
    for p in links:
        if not p.is_symlink() or p.name in locked or p.name in seen_trees:
            continue
        target = Path(os.path.normpath(os.path.join(str(p.parent), os.readlink(p))))
        # Only links that claim to be ours. A symlink the operator made to somewhere
        # else in his own filesystem is his business, not this primitive's.
        try:
            target_there = target.exists()
        except OSError:
            # The link points into a vendor dir this cannot stat. That is exactly the
            # half-removed litter this branch exists to report, so report it rather
            # than assume the tree is there and stay quiet.
            target_there = False
        if target != brain.vendor_path(p.name) or target_there:
            continue
        results.append((WARN, f"{p.name}: skills/{p.name} points at "
                              f"{VENDOR_REL}/{p.name}, which does not exist and is in "
                              f"no {LOCK_REL} entry (stray link from a half-removed "
                              f"install; fix: octo pkg uninstall {p.name})"))
    return results


def cmd_verify(brain: Brain, names: list[str], all_: bool, as_json: bool) -> int:
    probe = ssh_keygen_y_supported()
    try:
        lock = brain.load_lock()
    except PkgError as e:
        payload = {"ok": False, "ssh_keygen_y": probe, "error": str(e),
                   "pass": 0, "warn": [], "fail": [str(e)], "total": 0}
        print(json.dumps(payload) if as_json else f"[FAIL] {e}")
        return 1

    pkgs = lock["packages"]
    if names:
        wanted = set(names)
        pkgs = [p for p in pkgs if p.get("name") in wanted]
        missing = sorted(wanted - {str(p.get("name")) for p in pkgs})
    elif not all_:
        missing = []
    else:
        missing = []

    results = [verify_entry(brain, p) for p in pkgs]
    for n in missing:
        results.append((FAIL, f"{n}: not in {LOCK_REL}"))

    # The disk sweep runs only on the full pass. A targeted `verify <name>` answers
    # about that name, and turning it into a whole-brain audit would make the doctor's
    # scoped calls report failures the caller never asked about.
    strays = scan_unlocked(brain, {str(p.get("name")) for p in lock["packages"]}) if all_ and not names else []
    results.extend(strays)

    # Not conditional on the lock having entries. The doctor reports the probe as FAIL
    # on an empty lock too, and a verify that silently PASSes here while the doctor
    # goes red is the two disagreeing about the same machine.
    if not probe:
        results.append((FAIL, "ssh-keygen -Y unsupported: signatures cannot be checked"))

    fails = [m for s, m in results if s == FAIL]
    warns = [m for s, m in results if s == WARN]
    passes = [m for s, m in results if s == PASS]
    # Strays count toward the total, so the doctor's "n/total verified" line stays an
    # honest ratio: an unlocked tree is a package this brain is carrying, and leaving it
    # out of the denominator would let the count read full while one of them is unsigned.
    total = len(pkgs) + len(missing) + len(strays)

    if as_json:
        print(json.dumps({
            "ok": not fails,
            "ssh_keygen_y": probe,
            "pass": len(passes),
            "warn": warns,
            "fail": fails,
            "total": total,
        }, ensure_ascii=False))
    else:
        for status, msg in results:
            print(f"[{status}] {msg}")
        print(f"packages: {len(passes)} verified, {len(warns)} absent, {len(fails)} failed "
              f"({len(passes)}/{total})")
        # Only the absent-on-disk WARNs are fixed by a sync. A stray-link WARN carries
        # its own unlock in its message, and printing "run sync" under it would send the
        # operator to a command that does nothing for the thing he just read about.
        if any("fix:" not in m for m in warns):
            print(f"  fix: python3 scripts/{Path(__file__).name} sync")
    return 1 if fails else 0


# --------------------------------------------------------------------------
# uninstall / list / lock / sync
# --------------------------------------------------------------------------

def cmd_uninstall(brain: Brain, name: str) -> int:
    valid_name(name)
    lock = brain.load_lock()
    entry = next((p for p in lock["packages"] if p.get("name") == name), None)
    dest, link = brain.vendor_path(name), brain.link_path(name)
    try:
        tree_there = dest.exists()
    except OSError as e:
        # Refusing beats guessing here: uninstall DELETES, and a stat it cannot make
        # means it does not know what it would be deleting. PkgError so the caller
        # prints a reason instead of a traceback (QA cycle 5).
        raise PkgError(f"{VENDOR_REL}/{name} cannot be read ({e}); refusing to remove "
                       f"what cannot be inspected")
    if entry is None and not tree_there and not link.is_symlink():
        raise PkgError(f"{name} is not installed")

    if not link.is_symlink() and link.exists():
        raise PkgError(f"skills/{name} exists but is not our symlink; refusing to delete it")
    # The TREE goes first, then the link. The old order unlinked and then removed,
    # so a rmtree that could not finish (an unreadable subdirectory, EACCES) left a
    # half-removed install: tree present, symlink gone, lock entry still there. The
    # tree is the part that carries code, so it is the part that must be gone before
    # anything else is touched. rmtree deletes as it walks, so a failure can leave a
    # PARTIAL tree rather than nothing (QA cycle 6 corrected the earlier claim that
    # nothing would be removed); what holds is that the link and the lock entry are
    # untouched, so the state is over-claiming rather than an invisible stray, and
    # verify names it as `tree changed since install`.
    if tree_there:
        try:
            shutil.rmtree(dest)
        except OSError as e:
            # The ordering comment above names exactly this case, and it was still
            # leaving as a traceback (QA cycle 6). rmtree deletes as it walks, so a
            # partial tree is possible; verify catches that as `tree changed since
            # install`, and the lock still says installed, which is the reportable
            # direction. The link is untouched, so nothing became an unlocked tree.
            raise PkgError(f"{VENDOR_REL}/{name} could not be removed ({e}); "
                           f"the install is left as it was, run verify to see it")
    if link.is_symlink():
        link.unlink()
    brain.exclude_remove(f"skills/{name}")

    with brain.lock_held():
        lock = brain.load_lock()
        lock["packages"] = [p for p in lock["packages"] if p.get("name") != name]
        brain.save_lock(lock)
    print(f"uninstalled {name}: vendor tree, symlink, exclude entry and lock entry removed")
    return 0


def cmd_list(brain: Brain, as_json: bool) -> int:
    lock = brain.load_lock()
    rows = []
    for p in lock["packages"]:
        status, _ = verify_entry(brain, p)
        rows.append({**{k: v for k, v in p.items()}, "status": status})
    if as_json:
        print(json.dumps({"packages": rows}, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("no packages installed (empty lock)")
        return 0
    width = max(len(str(r["name"])) for r in rows)
    for r in rows:
        print(f"  [{r['status']}] {str(r['name']).ljust(width)}  {r.get('version')}  "
              f"{r.get('kind')}  signer={r.get('signer') or '-'}  {r.get('source')}")
    print(f"{len(rows)} package(s) in {LOCK_REL}")
    return 0


def cmd_hash(brain: Brain, target: str, write: bool) -> int:
    """Print the tree hash of a package directory, and optionally embed it.

    This is the publisher's first step: the number that goes into `tree_sha256` has to
    come from the same function the installer will use, or the two disagree and every
    install of that package is refused for a reason nobody can see.
    """
    d = resolve_or_fail(Path(os.path.expanduser(target)), target)
    if not stat_ok(d.is_dir, False, str(d)):
        raise PkgError(f"not a directory: {d}")
    kind = "arm" if (d / MANIFEST_NAME["arm"]).is_file() and not (d / MANIFEST_NAME["skill"]).is_file() else "skill"
    digest = tree_sha256(d, kind)
    print(digest)
    if not write:
        return 0
    mpath = d / MANIFEST_NAME[kind]
    if not mpath.is_file():
        raise PkgError(f"--write needs {MANIFEST_NAME[kind]} in {d}")
    manifest = read_json(mpath, MANIFEST_NAME[kind])
    if not isinstance(manifest, dict):
        raise PkgError(f"{MANIFEST_NAME[kind]} in {d} is not a JSON object")
    manifest["tree_sha256"] = digest
    mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"embedded in {mpath}")
    # The manifest just changed, so any signature beside it now covers different bytes.
    # It cannot be left there: `ssh-keygen -Y sign` over an existing .sig PROMPTS to
    # overwrite, and on EOF (a script, a CI step, a heredoc) it declines, keeps the OLD
    # signature and STILL EXITS 0. The publisher then ships a package whose signature
    # verifies against a manifest nobody has. Deleting it here makes that impossible:
    # sign writes fresh, or there is no signature at all and install refuses.
    sig = d / SIG_NAME
    if sig.exists():
        sig.unlink()
        print(f"removed stale {sig.name}: it signed the previous manifest")
    print(f"next: ssh-keygen -Y sign -f <your-key> -n {SIG_NAMESPACE} {mpath}")
    return 0


def cmd_lock(brain: Brain) -> int:
    """Re-lock: recompute each installed skill's tree hash and signer from disk.

    The honest use is after a deliberate, verified local change to a vendored
    package. It never invents a signer: an entry whose signature no longer verifies
    is reported and left alone, so re-locking cannot launder a tampered tree.
    """
    lock = brain.load_lock()
    changed, refused = [], []
    for entry in lock["packages"]:
        if lock_kind(entry) != "skill":
            continue
        name = entry["name"]
        dest = brain.vendor_path(name)
        try:
            if not dest.exists():
                continue
            manifest = check_package(brain, dest, "skill")
        except (PkgError, OSError) as e:
            # OSError next to PkgError: the stat is as able to fail as the read, and
            # re-locking is the one verb that WRITES the lock, so an entry it cannot
            # inspect has to be refused and left exactly as it was. Silently skipping
            # would be worse than the traceback it replaces.
            refused.append(f"{name}: {e}")
            continue
        if entry.get("tree_sha256") != manifest["tree_sha256"] or entry.get("signer") != manifest["_signer"]:
            entry["tree_sha256"] = manifest["tree_sha256"]
            entry["signer"] = manifest["_signer"]
            entry["version"] = manifest["version"]
            changed.append(name)
    with brain.lock_held():
        brain.save_lock(lock)
    for r in refused:
        print(f"[FAIL] {r}")
    print(f"re-locked: {len(changed)} entry(ies) updated"
          + (f" ({', '.join(changed)})" if changed else "")
          + (f", {len(refused)} refused" if refused else ""))
    return 1 if refused else 0


def cmd_sync(brain: Brain) -> int:
    """Install from the lock what is not on disk, then verify.

    An empty lock is a no-op. A fetch failure prints WARN and continues, because
    `ai-pull` calls this: a machine that is offline, or a source repo that moved,
    must not break the whole sync of the brain.
    """
    lock = brain.load_lock()
    if not lock["packages"]:
        print("packages: empty lock, nothing to sync")
        return 0
    restored, warned = 0, []
    for entry in list(lock["packages"]):
        name = str(entry.get("name") or "?")
        if lock_kind(entry) != "skill":
            continue
        dest = brain.vendor_path(name)
        try:
            already_there = dest.exists() or dest.is_symlink()
        except OSError as e:
            # sync runs from ai-pull, so a stat it cannot make must not take the
            # whole pull down. Not knowing whether the tree is there is a reason to
            # leave it alone and say so, never to restore over something unseen.
            print(f"  WARN {name}: {VENDOR_REL}/{name} cannot be read ({e}); skipped")
            continue
        if already_there:
            continue
        link = brain.link_path(name)
        if link.is_symlink():
            link.unlink()  # a dangling link from a half-removed install
        elif link.exists():
            # A real directory the operator (or another tool) put there. sync is a
            # restore, never an overwrite: whatever is at skills/<name> is first-party
            # until proven otherwise, and clobbering it would delete their work.
            warned.append(f"{name}: skills/{name} exists and is not our symlink; not restored")
            continue
        source = entry.get("source") or ""
        source_spec, sub_path, pinned_ref = _split_source_spec(source)
        try:
            with tempfile.TemporaryDirectory(prefix="octo-pkg-sync-") as td:
                pkg, _ = fetch_source(source_spec, sub_path, pinned_ref, Path(td))
                manifest = check_package(brain, pkg, "skill")
                if manifest.get("tree_sha256") != entry.get("tree_sha256"):
                    warned.append(f"{name}: source tree hash differs from the lock; not installed")
                    continue
                if manifest.get("name") != name:
                    warned.append(f"{name}: source now publishes {manifest.get('name')!r}; not installed")
                    continue
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(pkg, dest, symlinks=False)
                    link.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(os.path.relpath(dest, link.parent), link, target_is_directory=True)
                    brain.exclude_add(f"skills/{name}")
                except BaseException:
                    # The same stance as install, and now literally the same width.
                    # The comment used to claim they matched while this caught only
                    # OSError; when exclude_add started raising PkgError through the
                    # seam, that walked past this into the outer handler and sync
                    # reported "0 restored, 1 skipped" for a package it had in fact
                    # restored whole (QA cycle 7). A half-restore leaves an
                    # unverifiable tree in the discovery path, so any failure unwinds.
                    if link.is_symlink():
                        link.unlink()
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    raise
                restored += 1
        except PkgError as e:
            warned.append(f"{name}: {e}")
        except OSError as e:
            warned.append(f"{name}: {e}")
    for w in warned:
        print(f"[WARN] {w}")
    print(f"packages: {restored} restored from {LOCK_REL}, {len(warned)} skipped")
    return cmd_verify(brain, [], True, False)


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------

def _sandbox_brain(tmp: Path, real: Brain) -> Brain:
    """A throwaway brain: its own HOME, its own git repo, the real schema, an empty
    lock, and no signers file yet (the key is minted below)."""
    home = tmp / "home"
    root = home / ".claude"
    (root / "schemas").mkdir(parents=True)
    (root / "registry").mkdir(parents=True)
    (root / "skills").mkdir(parents=True)
    shutil.copy2(real.schema_path, root / "schemas" / "skill-manifest.schema.json")
    (root / LOCK_REL).write_text(json.dumps({"version": 1, "packages": []}, indent=2) + "\n",
                                 encoding="utf-8")
    _run(["git", "init", "-q", str(root)])
    os.environ["HOME"] = str(home)
    return Brain(root)


def _sign(key: Path, mpath: Path) -> None:
    cp = _run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", SIG_NAMESPACE, str(mpath)])
    if cp.returncode != 0:
        raise PkgError("ssh-keygen -Y sign failed: "
                       + (cp.stderr or b"").decode("utf-8", "replace"))


def selftest(fixture: Path, real: Brain) -> int:
    """Every leg of the PACKAGE contract, under a throwaway HOME and a key minted at
    run time. No private key ever lives in the repo (push-policy.txt blocks key
    blocks, and a committed key would be a real one)."""
    if not fixture.is_dir():
        print(f"selftest: fixture dir not found: {fixture}", file=sys.stderr)
        return 2
    if not ssh_keygen_y_supported():
        print("selftest: ssh-keygen -Y unsupported here; cannot prove the signature leg",
              file=sys.stderr)
        return 2

    failures: list[str] = []

    def check(label: str, cond: bool) -> None:
        print(f"  {'ok  ' if cond else 'FAIL'} {label}")
        if not cond:
            failures.append(label)

    saved_home = os.environ.get("HOME")
    tmp = Path(tempfile.mkdtemp(prefix="octo-pkg-selftest-"))
    try:
        brain = _sandbox_brain(tmp, real)

        # throwaway release key, minted here, never on disk in the repo
        keydir = tmp / "keys"
        keydir.mkdir()
        key = keydir / "release"
        cp = _run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "octorato-selftest",
                   "-f", str(key)])
        if cp.returncode != 0:
            print("selftest: ssh-keygen could not mint a key", file=sys.stderr)
            return 2
        pub = key.with_suffix(".pub").read_text(encoding="utf-8").split()
        (brain.root / PUBLIC_SIGNERS_REL).write_text(
            f"octorato-release {pub[0]} {pub[1]}\n", encoding="utf-8")

        # stage the three sample trees and sign two of them
        src = tmp / "src"
        shutil.copytree(fixture, src)
        signed, unsigned, tampered = src / "signed", src / "unsigned", src / "tampered"
        _sign(key, signed / "skill.json")
        _sign(key, tampered / "skill.json")  # validly signed, tree hash deliberately wrong

        name = json.loads((signed / "skill.json").read_text(encoding="utf-8"))["name"]
        dest, link = brain.vendor_path(name), brain.link_path(name)

        # 1. the signed sample installs
        rc = main(["--brain", str(brain.root), "install", str(signed)])
        check("signed install exits 0", rc == 0)
        check("vendor tree present", dest.is_dir())
        check("skills/<name> is a symlink to the vendor tree",
              link.is_symlink() and link.resolve() == dest.resolve())
        check("exclude entry written", brain.exclude_has(f"skills/{name}"))
        check("lock has one entry", len(brain.load_lock()["packages"]) == 1)

        # 2. verify --all is green
        check("verify --all exits 0 after install",
              main(["--brain", str(brain.root), "verify", "--all"]) == 0)

        # 3. one edited byte turns verify red
        skill_md = dest / "SKILL.md"
        original = skill_md.read_bytes()
        skill_md.write_bytes(original + b"x")
        check("verify --all exits 1 on a mismatched present entry (FAIL tier)",
              main(["--brain", str(brain.root), "verify", "--all"]) == 1)
        skill_md.write_bytes(original)
        check("verify --all green again once the byte is restored",
              main(["--brain", str(brain.root), "verify", "--all"]) == 0)

        # 4. the unsigned sample is refused and copies nothing
        u_name = json.loads((unsigned / "skill.json").read_text(encoding="utf-8"))["name"]
        rc = main(["--brain", str(brain.root), "install", str(unsigned)])
        check("unsigned install exits 1", rc == 1)
        check("unsigned copied nothing",
              not brain.vendor_path(u_name).exists() and not brain.link_path(u_name).exists())

        # 5. the tampered tree is refused BEFORE the signature is ever checked
        global SIG_VERIFY_CALLS
        SIG_VERIFY_CALLS = 0
        t_name = json.loads((tampered / "skill.json").read_text(encoding="utf-8"))["name"]
        rc = main(["--brain", str(brain.root), "install", str(tampered)])
        check("tampered install exits 1", rc == 1)
        check("signature never checked on a tampered tree", SIG_VERIFY_CALLS == 0)
        check("tampered copied nothing",
              not brain.vendor_path(t_name).exists() and not brain.link_path(t_name).exists())

        # 6. an entry absent on disk is WARN, not FAIL: exit 0
        shutil.rmtree(dest)
        link.unlink()
        check("verify --all exits 0 on an absent-on-disk entry (WARN tier)",
              main(["--brain", str(brain.root), "verify", "--all"]) == 0)

        # 7. sync restores it from the lock
        check("sync exits 0", main(["--brain", str(brain.root), "sync"]) == 0)
        check("sync restored the vendor tree", dest.is_dir())
        check("sync restored the symlink",
              link.is_symlink() and link.resolve() == dest.resolve())

        # 8. uninstall removes both paths and shrinks the lock
        check("uninstall exits 0", main(["--brain", str(brain.root), "uninstall", name]) == 0)
        check("uninstall removed the vendor tree", not dest.exists())
        check("uninstall removed the symlink", not link.is_symlink() and not link.exists())
        check("uninstall removed the exclude entry", not brain.exclude_has(f"skills/{name}"))
        check("uninstall emptied the lock", brain.load_lock()["packages"] == [])

        # 9. a git repository source goes through the sparse-checkout helper. Local
        # git repo, so this leg proves the GitHub code path with no network: same
        # _github_module import, same gh._git_sparse_checkout call.
        gitsrc = tmp / "gitrepo"
        (gitsrc / "skills").mkdir(parents=True)
        shutil.copytree(signed, gitsrc / "skills" / "sample-package")
        for cmd in (["git", "init", "-q", "-b", "master", str(gitsrc)],
                    ["git", "-C", str(gitsrc), "add", "-A"],
                    ["git", "-C", str(gitsrc), "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "-m", "seed"]):
            _run(cmd)
        rc = main(["--brain", str(brain.root), "install", str(gitsrc),
                   "--path", "skills/sample-package"])
        check("install from a git repository exits 0 (no --ref: master fallback)", rc == 0)
        check("git-sourced package installed", dest.is_dir() and link.is_symlink())
        check("git source recorded in the lock",
              brain.load_lock()["packages"][0]["source"].startswith("git+file://"))

        # 10. a .git planted inside the installed tree changes the hash: FAIL
        (dest / ".git").mkdir()
        (dest / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        check("a .git dir planted in vendor turns verify FAIL",
              main(["--brain", str(brain.root), "verify", "--all"]) == 1)
        shutil.rmtree(dest / ".git")
        check("verify green again once it is removed",
              main(["--brain", str(brain.root), "verify", "--all"]) == 0)

        # 11. the symlink retargeted to an identical copy elsewhere: FAIL on readlink
        elsewhere = tmp / "elsewhere"
        shutil.copytree(dest, elsewhere)
        link.unlink()
        os.symlink(str(elsewhere), link, target_is_directory=True)
        check("a retargeted symlink is FAIL even when the bytes match",
              main(["--brain", str(brain.root), "verify", "--all"]) == 1)
        link.unlink()
        os.symlink(os.path.relpath(dest, link.parent), link, target_is_directory=True)

        # 12. a lock naming an escaped path refuses the whole file
        good_lock = brain.lock_path.read_text(encoding="utf-8")
        brain.lock_path.write_text(json.dumps({"version": 1, "packages": [
            {"name": "../../../escaped", "kind": "skill", "version": "1.0.0",
             "tree_sha256": "0" * 64, "signer": "octorato-release",
             "source": str(signed), "installed_at": "2026-01-01T00:00:00Z"}]}, indent=2),
            encoding="utf-8")
        check("a lock naming an escaped path is refused, not PASSed",
              main(["--brain", str(brain.root), "verify", "--all"]) == 1)
        check("sync refuses that lock too and writes nothing",
              main(["--brain", str(brain.root), "sync"]) == 1
              and not (brain.root.parent.parent / "escaped").exists())
        brain.lock_path.write_text(good_lock, encoding="utf-8")
        main(["--brain", str(brain.root), "uninstall", name])

        # 13. reserved and malformed --name are refused
        check("--name vendor is refused",
              main(["--brain", str(brain.root), "install", str(signed), "--name", "vendor"]) == 1)
        check("--name with a path separator is refused",
              main(["--brain", str(brain.root), "install", str(signed), "--name", "a/b"]) == 1)
        check("neither refusal left a tree behind",
              not brain.vendor_path("vendor").exists() and not (brain.vendor_dir / "a").exists())

        # 14. hash --write invalidates a signature that no longer covers the manifest
        pub = tmp / "publish"
        shutil.copytree(signed, pub)
        _sign(key, pub / "skill.json")
        (pub / "LATER.md").write_text("an edit after signing\n", encoding="utf-8")
        main(["--brain", str(brain.root), "hash", str(pub), "--write"])
        check("hash --write removes a signature that no longer covers the manifest",
              not (pub / SIG_NAME).exists())
        check("the edited package is refused while unsigned",
              main(["--brain", str(brain.root), "install", str(pub)]) == 1)
        _sign(key, pub / "skill.json")
        check("re-signed after re-hashing, it installs",
              main(["--brain", str(brain.root), "install", str(pub)]) == 0)
        main(["--brain", str(brain.root), "uninstall", name])

        # 15. sync on an empty lock is a no-op
        before = sorted(p.name for p in brain.vendor_dir.iterdir()) if brain.vendor_dir.exists() else []
        check("sync on an empty lock exits 0", main(["--brain", str(brain.root), "sync"]) == 0)
        after = sorted(p.name for p in brain.vendor_dir.iterdir()) if brain.vendor_dir.exists() else []
        check("sync on an empty lock changed nothing", before == after == [])
        check("verify --all exits 0 on an empty lock",
              main(["--brain", str(brain.root), "verify", "--all"]) == 0)

        # 16. the lock's own fields are not what decides whether the ladder runs, and
        # the lock is not the only thing verify looks at. Three legs, one per QA cycle 3
        # finding, because each of them was a state where verify printed ok:true over a
        # package the brain was still loading.
        main(["--brain", str(brain.root), "install", str(signed)])
        lock_json = json.loads(brain.lock_path.read_text(encoding="utf-8"))
        lock_json["packages"][0]["kind"] = "arm"
        brain.lock_path.write_text(json.dumps(lock_json, indent=2) + "\n", encoding="utf-8")
        ref = dest / "reference.txt"
        keep = ref.read_bytes()
        ref.write_bytes(keep + b"tampered\n")
        check("kind flipped to arm over a tampered tree is FAIL, not PASS",
              main(["--brain", str(brain.root), "verify", "--all"]) == 1)
        ref.write_bytes(keep)
        lock_json["packages"][0]["kind"] = "skill"
        brain.lock_path.write_text(json.dumps(lock_json, indent=2) + "\n", encoding="utf-8")
        check("green again with the kind and the byte restored",
              main(["--brain", str(brain.root), "verify", "--all"]) == 0)

        os.chmod(ref, 0o755)
        check("chmod +x on a package file turns verify FAIL",
              main(["--brain", str(brain.root), "verify", "--all"]) == 1)
        os.chmod(ref, 0o644)
        check("green again once the execute bit is dropped",
              main(["--brain", str(brain.root), "verify", "--all"]) == 0)

        brain.lock_path.write_text(json.dumps({"version": 1, "packages": []}, indent=2) + "\n",
                                   encoding="utf-8")
        check("a vendored tree with no lock entry is FAIL, not invisible",
              main(["--brain", str(brain.root), "verify", "--all"]) == 1)
        shutil.rmtree(dest)
        check("its dangling symlink alone is WARN, not FAIL",
              main(["--brain", str(brain.root), "verify", "--all"]) == 0)
        main(["--brain", str(brain.root), "uninstall", name])
        check("uninstall clears the stray link the WARN named",
              main(["--brain", str(brain.root), "verify", "--all"]) == 0
              and not link.is_symlink())
    finally:
        if saved_home is not None:
            os.environ["HOME"] = saved_home
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"selftest FAILED: {len(failures)} leg(s): " + "; ".join(failures), file=sys.stderr)
        return 1
    print("selftest OK: install, refusal, tamper-before-signature, verify ladder, "
          "sync and uninstall all proven")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="octo pkg",
        description="Install, verify and lock Octorato packages (skills and arms).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brain", help="brain checkout to operate on (default: CLAUDE_DIR, "
                                    "else this script's repo)")
    ap.add_argument("--selftest", metavar="FIXTURE_DIR",
                    help="run every PACKAGE leg under a throwaway HOME and key")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("install", help="install a package after validating, hashing and verifying it")
    p.add_argument("source", help="local directory, GitHub URL, or owner/repo")
    p.add_argument("--kind", choices=["skill", "arm"], default="skill")
    p.add_argument("--path", help="package path inside the repo")
    p.add_argument("--ref", default=None,
                   help="branch or tag; unset tries main then master")
    p.add_argument("--name", help="install under this name instead of the manifest's")
    p.add_argument("--dest", help="arm only: where to clone")

    p = sub.add_parser("verify", help="verify installed packages against the lock")
    p.add_argument("names", nargs="*")
    p.add_argument("--all", action="store_true", help="verify every lock entry")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("uninstall", help="remove a package, its symlink and its lock entry")
    p.add_argument("name")

    p = sub.add_parser("list", help="list lock entries with their live status")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("hash", help="print a package directory's tree_sha256")
    p.add_argument("dir")
    p.add_argument("--write", action="store_true", help="embed it into the manifest")

    sub.add_parser("lock", help="recompute tree hash and signer for installed packages")
    sub.add_parser("sync", help="install from the lock what is missing, then verify")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        brain = resolve_brain(args.brain)
    except (OSError, RuntimeError) as e:
        # RuntimeError is not a typo: pathlib converts a symlink loop into one, so
        # "filesystem crossing" and "OSError" are not the same set even inside the
        # standard library. This call sat outside the backstop below (QA cycle 7).
        print(f"error: --brain cannot be resolved: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1

    if args.selftest:
        return selftest(Path(args.selftest) if os.path.isabs(args.selftest)
                        else brain.root / args.selftest, brain)
    if not args.cmd:
        ap.print_help()
        return 2

    try:
        if args.cmd == "install":
            if args.kind == "arm":
                return install_arm(brain, args.source, args.dest)
            return install_skill(brain, args.source, args.path, args.ref, args.name)
        if args.cmd == "verify":
            if not args.names and not args.all:
                args.all = True
            return cmd_verify(brain, args.names, args.all, args.json)
        if args.cmd == "uninstall":
            return cmd_uninstall(brain, args.name)
        if args.cmd == "list":
            return cmd_list(brain, args.json)
        if args.cmd == "hash":
            return cmd_hash(brain, args.dir, args.write)
        if args.cmd == "lock":
            return cmd_lock(brain)
        if args.cmd == "sync":
            return cmd_sync(brain)
    except PkgError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError, RuntimeError) as e:
        # The backstop, and the reason this is the last cycle of its kind. Six QA
        # rounds each found one more crossing of the filesystem boundary that left
        # as a traceback instead of a report, and each fix named the site it had
        # just been shown. Naming sites loses to the next one nobody enumerated.
        # This does not replace the guards above it: the ones on the way down say
        # WHICH package failed and let the sweep finish, which is the whole value.
        # It replaces the traceback with a report for the crossing that was missed,
        # so a future miss costs a worse message rather than the caller's output.
        # RuntimeError is here because pathlib raises it for a symlink loop, and
        # UnicodeDecodeError because it is the class that
        # actually recurred, twice, and it is a ValueError: the net that caught only
        # OSError would not have held the very thing it was built for. Still NOT
        # Exception: a TypeError here is a bug in this module and must keep its
        # traceback, because a bug that reports itself as a refusal is a bug nobody
        # fixes.
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        print("       (an unguarded filesystem crossing; the operation did not "
              "complete and may have left work half done)", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())

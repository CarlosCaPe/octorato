#!/usr/bin/env python3
"""Install a skill from a GitHub repo path into $CODEX_HOME/skills."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import zipfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))

import proc_group  # noqa: E402  (the single group-kill implementation)
from github_utils import github_request
DEFAULT_REF = "main"


@dataclass
class Args:
    url: str | None = None
    repo: str | None = None
    path: list[str] | None = None
    ref: str = DEFAULT_REF
    dest: str | None = None
    name: str | None = None
    method: str = "auto"


@dataclass
class Source:
    owner: str
    repo: str
    ref: str
    paths: list[str]
    repo_url: str | None = None


class InstallError(Exception):
    pass


def _codex_home() -> str:
    return os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))


def _tmp_root() -> str:
    base = os.path.join(tempfile.gettempdir(), "codex")
    os.makedirs(base, exist_ok=True)
    return base


def _request(url: str) -> bytes:
    return github_request(url, "codex-skill-install")


def _parse_github_url(url: str, default_ref: str) -> tuple[str, str, str, str | None]:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc != "github.com":
        raise InstallError("Only GitHub URLs are supported for download mode.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise InstallError("Invalid GitHub URL.")
    owner, repo = parts[0], parts[1]
    ref = default_ref
    subpath = ""
    if len(parts) > 2:
        if parts[2] in ("tree", "blob"):
            if len(parts) < 4:
                raise InstallError("GitHub URL missing ref or path.")
            ref = parts[3]
            subpath = "/".join(parts[4:])
        else:
            subpath = "/".join(parts[2:])
    return owner, repo, ref, subpath or None


def _download_repo_zip(owner: str, repo: str, ref: str, dest_dir: str) -> str:
    zip_url = f"https://codeload.github.com/{owner}/{repo}/zip/{ref}"
    zip_path = os.path.join(dest_dir, "repo.zip")
    try:
        payload = _request(zip_url)
    except urllib.error.HTTPError as exc:
        raise InstallError(f"Download failed: HTTP {exc.code}") from exc
    with open(zip_path, "wb") as file_handle:
        file_handle.write(payload)
    with zipfile.ZipFile(zip_path, "r") as zip_file:
        _safe_extract_zip(zip_file, dest_dir)
        top_levels = {name.split("/")[0] for name in zip_file.namelist() if name}
    if not top_levels:
        raise InstallError("Downloaded archive was empty.")
    if len(top_levels) != 1:
        raise InstallError("Unexpected archive layout.")
    return os.path.join(dest_dir, next(iter(top_levels)))


# Ceiling on a git child. The clones here are shallow and blob-filtered, so a child
# still alive after this has stopped fetching and started waiting.
#
# Chosen, not derived. Measured reference: the exact clone shape below, against a 29 MB
# repository on a 4-core box at load 18, took 3.7 s. The ceiling is ~160x that. It has
# not been measured against a large repository or a throttled link, so it is deliberate
# headroom: a ceiling that cuts a slow but correct fetch would be worse than no ceiling.
_GIT_TIMEOUT = 600.0

# Grace for reaping a group that was just SIGKILLed. A task that does not go in this
# long is in uninterruptible sleep and cannot be killed from user space at all; the
# reap is abandoned rather than waited on, so this function cannot itself hang.
_REAP_GRACE = 10.0


def _run_git(args: list[str]) -> None:
    """Run one git command with no way to wait on a human, and no way to outlive us.

    Three channels, measured separately, because closing one does nothing for the
    others: a credential prompt for a repo that answers 401 goes to /dev/tty, so it
    hangs with stdin closed and needs GIT_TERMINAL_PROMPT=0; a prompt that reads stdin
    is stopped by DEVNULL and not by the env; and ssh's host-key question ("Are you sure
    you want to continue connecting?") hangs through BOTH, because ssh opens /dev/tty
    itself, and is ended by start_new_session, which leaves the child no controlling
    terminal to open. That third one matters here specifically: this function clones
    over ssh as well as https.

    start_new_session also makes the kill below a GROUP kill, which is the difference
    between reporting a timeout and actually ending one. `git clone` over ssh runs ssh
    as a grandchild, and killing only the direct child leaves that grandchild alive on
    the prompt: measured, rc 124 returned while ssh was still running and still holding
    the terminal.

    What the kill reaches is the process GROUP, not the process tree: a descendant that
    moves itself into another session survives and is not visible to the check below
    either, so the refusal will call it killed. That is the same limit octo_pkg._run
    carries, stated here too because a reader of this function should not have to find
    it in the other one.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, env=env,
                            start_new_session=True)
    try:
        _out, err = proc.communicate(timeout=_GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        # Through the shared primitive, never a second copy. The copy that used to live
        # here called killpg with no guard: when a mutant removed the start_new_session
        # above, the child shared this process's group and the call SIGKILLed the test
        # runner instead of failing a test.
        # Read before the reap, not before the kill: getpgid still answers for a
        # zombie. Once communicate() has reaped it, group_of returns None and the
        # check below can only ever say "nothing to warn about".
        group = proc_group.group_of(proc)
        landed = proc_group.kill_group(proc)
        try:
            proc.communicate(timeout=_REAP_GRACE)
        except subprocess.TimeoutExpired:
            # A descendant that left the group still holds the pipe, so this expires
            # with the child dead and unreaped. An unreaped child is a zombie, a zombie
            # is still in the group, and the check below would then call a clean kill
            # "not confirmed dead". Same line, same reason, as octo_pkg._run.
            try:
                proc.wait(timeout=_REAP_GRACE)
            except subprocess.TimeoutExpired:
                pass
        # Say whether the kill actually emptied the group. Without this the message
        # reads "was killed" while a survivor is still running, which is the same
        # wrong-cause sentence this whole function exists to stop.
        left = "" if (landed and proc_group.group_gone(proc, group)) else \
            " (process group not confirmed dead; check for leftovers)"
        raise InstallError(f"git took longer than {_GIT_TIMEOUT:.0f}s and was killed: "
                           + " ".join(args[:3]) + left)
    if proc.returncode != 0:
        raise InstallError((err or "").strip() or "Git command failed.")


def _safe_extract_zip(zip_file: zipfile.ZipFile, dest_dir: str) -> None:
    dest_root = os.path.realpath(dest_dir)
    for info in zip_file.infolist():
        extracted_path = os.path.realpath(os.path.join(dest_dir, info.filename))
        if extracted_path == dest_root or extracted_path.startswith(dest_root + os.sep):
            continue
        raise InstallError("Archive contains files outside the destination.")
    zip_file.extractall(dest_dir)


def _validate_relative_path(path: str) -> None:
    if os.path.isabs(path) or os.path.normpath(path).startswith(".."):
        raise InstallError("Skill path must be a relative path inside the repo.")


def _validate_skill_name(name: str) -> None:
    altsep = os.path.altsep
    if not name or os.path.sep in name or (altsep and altsep in name):
        raise InstallError("Skill name must be a single path segment.")
    if name in (".", ".."):
        raise InstallError("Invalid skill name.")


def _git_sparse_checkout(repo_url: str, ref: str, paths: list[str], dest_dir: str) -> str:
    # A FRESH directory per attempt. git clone refuses a non-empty destination, and
    # this function is called more than once against the same dest_dir: the caller
    # retries https then ssh, and the branch clone below retries without --branch. With
    # a shared "repo" path every retry died with "destination path already exists",
    # which masked the real failure (auth, missing ref) behind a filesystem message.
    repo_dir = tempfile.mkdtemp(prefix="clone-", dir=dest_dir)
    os.rmdir(repo_dir)
    clone_cmd = [
        "git",
        "clone",
        "--filter=blob:none",
        "--depth",
        "1",
        "--sparse",
        "--single-branch",
        "--branch",
        ref,
        repo_url,
        repo_dir,
    ]
    try:
        _run_git(clone_cmd)
    except InstallError:
        # Second attempt (repo default branch): its own empty directory, same reason.
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)
        _run_git(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--depth",
                "1",
                "--sparse",
                "--single-branch",
                repo_url,
                repo_dir,
            ]
        )
    _run_git(["git", "-C", repo_dir, "sparse-checkout", "set", *paths])
    _run_git(["git", "-C", repo_dir, "checkout", ref])
    return repo_dir


def _validate_skill(path: str) -> None:
    if not os.path.isdir(path):
        raise InstallError(f"Skill path not found: {path}")
    skill_md = os.path.join(path, "SKILL.md")
    if not os.path.isfile(skill_md):
        raise InstallError("SKILL.md not found in selected skill directory.")


def _copy_skill(src: str, dest_dir: str) -> None:
    os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
    if os.path.exists(dest_dir):
        raise InstallError(f"Destination already exists: {dest_dir}")
    shutil.copytree(src, dest_dir)


def _build_repo_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}.git"


def _build_repo_ssh(owner: str, repo: str) -> str:
    return f"git@github.com:{owner}/{repo}.git"


def _prepare_repo(source: Source, method: str, tmp_dir: str) -> str:
    if method in ("download", "auto"):
        try:
            return _download_repo_zip(source.owner, source.repo, source.ref, tmp_dir)
        except InstallError as exc:
            if method == "download":
                raise
            err_msg = str(exc)
            if "HTTP 401" in err_msg or "HTTP 403" in err_msg or "HTTP 404" in err_msg:
                pass
            else:
                raise
    if method in ("git", "auto"):
        repo_url = source.repo_url or _build_repo_url(source.owner, source.repo)
        try:
            return _git_sparse_checkout(repo_url, source.ref, source.paths, tmp_dir)
        except InstallError:
            repo_url = _build_repo_ssh(source.owner, source.repo)
            return _git_sparse_checkout(repo_url, source.ref, source.paths, tmp_dir)
    raise InstallError("Unsupported method.")


def _resolve_source(args: Args) -> Source:
    if args.url:
        owner, repo, ref, url_path = _parse_github_url(args.url, args.ref)
        if args.path is not None:
            paths = list(args.path)
        elif url_path:
            paths = [url_path]
        else:
            paths = []
        if not paths:
            raise InstallError("Missing --path for GitHub URL.")
        return Source(owner=owner, repo=repo, ref=ref, paths=paths)

    if not args.repo:
        raise InstallError("Provide --repo or --url.")
    if "://" in args.repo:
        return _resolve_source(
            Args(url=args.repo, repo=None, path=args.path, ref=args.ref)
        )

    repo_parts = [p for p in args.repo.split("/") if p]
    if len(repo_parts) != 2:
        raise InstallError("--repo must be in owner/repo format.")
    if not args.path:
        raise InstallError("Missing --path for --repo.")
    paths = list(args.path)
    return Source(
        owner=repo_parts[0],
        repo=repo_parts[1],
        ref=args.ref,
        paths=paths,
    )


def _default_dest() -> str:
    return os.path.join(_codex_home(), "skills")


def _parse_args(argv: list[str]) -> Args:
    parser = argparse.ArgumentParser(description="Install a skill from GitHub.")
    parser.add_argument("--repo", help="owner/repo")
    parser.add_argument("--url", help="https://github.com/owner/repo[/tree/ref/path]")
    parser.add_argument(
        "--path",
        nargs="+",
        help="Path(s) to skill(s) inside repo",
    )
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--dest", help="Destination skills directory")
    parser.add_argument(
        "--name", help="Destination skill name (defaults to basename of path)"
    )
    parser.add_argument(
        "--method",
        choices=["auto", "download", "git"],
        default="auto",
    )
    return parser.parse_args(argv, namespace=Args())


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    try:
        source = _resolve_source(args)
        source.ref = source.ref or args.ref
        if not source.paths:
            raise InstallError("No skill paths provided.")
        for path in source.paths:
            _validate_relative_path(path)
        dest_root = args.dest or _default_dest()
        tmp_dir = tempfile.mkdtemp(prefix="skill-install-", dir=_tmp_root())
        try:
            repo_root = _prepare_repo(source, args.method, tmp_dir)
            installed = []
            for path in source.paths:
                skill_name = args.name if len(source.paths) == 1 else None
                skill_name = skill_name or os.path.basename(path.rstrip("/"))
                _validate_skill_name(skill_name)
                if not skill_name:
                    raise InstallError("Unable to derive skill name.")
                dest_dir = os.path.join(dest_root, skill_name)
                if os.path.exists(dest_dir):
                    raise InstallError(f"Destination already exists: {dest_dir}")
                skill_src = os.path.join(repo_root, path)
                _validate_skill(skill_src)
                _copy_skill(skill_src, dest_dir)
                installed.append((skill_name, dest_dir))
        finally:
            if os.path.isdir(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
        for skill_name, dest_dir in installed:
            print(f"Installed {skill_name} to {dest_dir}")
        return 0
    except InstallError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

---
name: skill-installer
description: Install Codex skills into $CODEX_HOME/skills from a curated list or a GitHub repo path. Use when a user asks to list installable skills, install a curated skill, or install a skill from another repo (including private repos).
metadata:
  short-description: Install curated skills from openai/skills or other repos
---

# Skill Installer

## Octorato first: use `octo pkg` for anything that will live in the brain

A skill in `~/.claude/skills/` runs on every prompt. If the skill is going THERE, it
is a package and it gets installed as one:

Run these from the brain checkout (`cd ~/.claude`):

```bash
python3 scripts/octo_pkg.py list
python3 scripts/octo_pkg.py verify --all
python3 scripts/octo_pkg.py hash registry/fixtures/META.kernel-package/signed
```

Install accepts a GitHub URL, `owner/repo` with `--path`, a git repository (remote URL
or a local path), or a plain package directory:

```bash
python3 scripts/octo_pkg.py install <owner>/<repo> --path skills/<name>
python3 scripts/octo_pkg.py install https://github.com/<owner>/<repo>/tree/<ref>/skills/<name>
python3 scripts/octo_pkg.py uninstall <name>
```

`--ref` is optional: unset, it tries `main` then `master`. When a branch name contains
slashes, pass `--path` so the ref is unambiguous.

Publishing (the two commands a package author runs, in this order):

```bash
python3 scripts/octo_pkg.py hash <package-dir> --write
ssh-keygen -Y sign -f <path-to-your-private-key> -n octorato-pkg <package-dir>/skill.json
```

`hash --write` embeds `tree_sha256` using the same function the installer recomputes.
`ssh-keygen -Y sign` requires `-f` with the signing key and the `octorato-pkg` namespace;
it writes the detached `skill.json.sig`, which ships beside the manifest. A worked,
copy-paste walkthrough with a throwaway key is in the Getting-Started wiki page.

That path validates `skill.json`, recomputes the tree hash, checks the detached
`ssh-keygen -Y` signature against `registry/pkg-signers.pub`, vendors the tree into
the gitignored `skills/vendor/<name>`, symlinks `skills/<name>` to it, and records the
result in the tracked `packages.lock.json` so every machine reproduces it and pre-push
re-verifies it. See the CLAUDE.md anchor "Kernel: packages".

The scripts below stay for the case they were written for: an UNSIGNED third-party
skill, installed on the Codex `--dest` path, outside the lock. Nothing claims those
were verified, which is exactly why they do not get a seat in the brain's skills
directory. If a skill has no signature and you want it in the brain anyway, that is a
decision for the operator, not a default.

Helps install skills. By default these are from https://github.com/openai/skills/tree/main/skills/.curated, but users can also provide other locations. Experimental skills live in https://github.com/openai/skills/tree/main/skills/.experimental and can be installed the same way.

Use the helper scripts based on the task:
- List skills when the user asks what is available, or if the user uses this skill without specifying what to do. Default listing is `.curated`, but you can pass `--path skills/.experimental` when they ask about experimental skills.
- Install from the curated list when the user provides a skill name.
- Install from another repo when the user provides a GitHub repo/path (including private repos).

Install skills with the helper scripts.

## Communication

When listing skills, output approximately as follows, depending on the context of the user's request. If they ask about experimental skills, list from `.experimental` instead of `.curated` and label the source accordingly:
"""
Skills from {repo}:
1. skill-1
2. skill-2 (already installed)
3. ...
Which ones would you like installed?
"""

After installing a skill, tell the user: "Restart Codex to pick up new skills."

## Scripts

All of these scripts use network, so when running in the sandbox, request escalation when running them.

- `scripts/list-skills.py` (prints skills list with installed annotations)
- `scripts/list-skills.py --format json`
- Example (experimental list): `scripts/list-skills.py --path skills/.experimental`
- `scripts/install-skill-from-github.py --repo <owner>/<repo> --path <path/to/skill> [<path/to/skill> ...]`
- `scripts/install-skill-from-github.py --url https://github.com/<owner>/<repo>/tree/<ref>/<path>`
- Example (experimental skill): `scripts/install-skill-from-github.py --repo openai/skills --path skills/.experimental/<skill-name>`

## Behavior and Options

- Defaults to direct download for public GitHub repos.
- If download fails with auth/permission errors, falls back to git sparse checkout.
- Aborts if the destination skill directory already exists.
- Installs into `$CODEX_HOME/skills/<skill-name>` (defaults to `~/.codex/skills`). It never writes into `~/.claude/skills/`: that is `octo pkg install`'s job, and only for a signed package.
- Multiple `--path` values install multiple skills in one run, each named from the path basename unless `--name` is supplied.
- Options: `--ref <ref>` (default `main`), `--dest <path>`, `--method auto|download|git`.

## Notes

- Curated listing is fetched from `https://github.com/openai/skills/tree/main/skills/.curated` via the GitHub API. If it is unavailable, explain the error and exit.
- Private GitHub repos can be accessed via existing git credentials or optional `GITHUB_TOKEN`/`GH_TOKEN` for download.
- Git fallback tries HTTPS first, then SSH.
- The skills at https://github.com/openai/skills/tree/main/skills/.system are preinstalled, so no need to help users install those. If they ask, just explain this. If they insist, you can download and overwrite.
- Installed annotations come from `$CODEX_HOME/skills`.

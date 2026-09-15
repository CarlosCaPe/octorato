#!/usr/bin/env python3
"""gen_skill_manifests.py: mint a `skill.json` per skill from its SKILL.md front matter.

One-shot backfill for the v8 PACKAGE primitive. Every skill directory needs a
manifest so `octo pkg` can reason about identity, vintage and terms, and hand-writing
233 of them is the kind of toil that produces typos, not care.

What it derives:
  name         front-matter `name`, else the directory slug
  version      1.0.0 (the first manifest of an existing skill is its 1.0.0)
  license      `<skill>/LICENSE.txt` if present, else the repo default (LICENSE)
  description  front-matter `description`, else `metadata.short-description`,
               else the first markdown heading
  kind         skill

What it deliberately does NOT write: `tree_sha256` and `signature`. An in-repo skill
changes on every edit, so a hash embedded in it would be stale within the hour and a
stale hash reads as a tampered tree. The hash and the signature are minted at
PUBLISH time, when a version is cut, by whoever holds the release key.

Dry-run by default (brain rule: destructive operations preview, live execution is
opt-in). `--write` performs it; an existing manifest is left alone unless `--force`.

    python3 scripts/gen_skill_manifests.py --root skills --dry-run
    python3 scripts/gen_skill_manifests.py --root skills --write
    python3 scripts/gen_skill_manifests.py --root <tmpdir> --write --only sample-package

Exit codes: 0 ok, 1 at least one skill could not be described, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BRAIN = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"vendor", "learned"}

# SPDX identifiers we recognize in a LICENSE header. Anything else falls back to the
# repo default rather than guessing: a wrong license on a distributable package is a
# legal claim, not a cosmetic field.
_SPDX = [
    ("AGPL-3.0-only", re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE", re.I)),
    ("Apache-2.0", re.compile(r"Apache License,?\s+Version 2\.0", re.I)),
    ("MPL-2.0", re.compile(r"Mozilla Public License Version 2\.0", re.I)),
    ("GPL-3.0-only", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 3", re.I)),
    ("BSD-3-Clause", re.compile(r"BSD 3-Clause", re.I)),
    ("MIT", re.compile(r"\bMIT License\b", re.I)),
]


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def spdx_of(text: str) -> str | None:
    for ident, rx in _SPDX:
        if rx.search(text):
            return ident
    return None


def frontmatter(text: str) -> dict:
    """Parse the YAML front matter block. Returns {} when there is none."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        import yaml
        data = yaml.safe_load(text[3:end])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def first_heading(text: str) -> str:
    for line in text.splitlines():
        m = re.match(r"^#+\s+(.+)", line)
        if m:
            return m.group(1).strip()
    return ""


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def describe(skill_dir: Path, default_license: str) -> tuple[dict | None, str]:
    """Return (manifest, problem). manifest is None when the skill cannot be described."""
    md = skill_dir / "SKILL.md"
    text = _read(md)
    if not text:
        return None, "SKILL.md unreadable or empty"
    fm = frontmatter(text)
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}

    name = slugify(fm.get("name") or skill_dir.name)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or not 2 <= len(name) <= 64:
        return None, f"cannot derive a valid slug from '{fm.get('name') or skill_dir.name}'"

    desc = (fm.get("description") or meta.get("short-description")
            or meta.get("description") or first_heading(text) or "").strip()
    desc = re.sub(r"\s+", " ", desc)[:1024]
    if not desc:
        return None, "no description in front matter and no heading to fall back on"

    lic = None
    for cand in ("LICENSE.txt", "LICENSE", "LICENSE.md"):
        p = skill_dir / cand
        if p.is_file():
            lic = spdx_of(_read(p))
            break
    manifest = {
        "kind": "skill",
        "name": name,
        "version": "1.0.0",
        "license": lic or default_license,
        "description": desc,
    }
    return manifest, ""


def repo_default_license(root: Path) -> str:
    for cand in ("LICENSE", "LICENSE.txt", "LICENSE.md"):
        p = root / cand
        if p.is_file():
            found = spdx_of(_read(p))
            if found:
                return found
    return "MIT"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="skills",
                    help="directory of skill dirs (default: skills, relative to the brain)")
    ap.add_argument("--only", nargs="*", help="restrict to these skill directory names")
    ap.add_argument("--write", action="store_true", help="actually write (default: preview)")
    ap.add_argument("--dry-run", action="store_true", help="explicit no-op preview (the default)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing skill.json")
    ap.add_argument("--default-license",
                    help="SPDX id when a skill has no LICENSE (default: the repo's)")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    root = Path(args.root)
    if not root.is_absolute():
        root = BRAIN / root
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    default_license = args.default_license or repo_default_license(BRAIN)
    only = set(args.only or [])
    written, skipped, problems = [], [], []

    for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if skill_dir.name in SKIP_DIRS or skill_dir.is_symlink():
            continue
        if only and skill_dir.name not in only:
            continue
        if not (skill_dir / "SKILL.md").is_file():
            continue
        target = skill_dir / "skill.json"
        if target.exists() and not args.force:
            skipped.append(skill_dir.name)
            continue
        manifest, problem = describe(skill_dir, default_license)
        if manifest is None:
            problems.append(f"{skill_dir.name}: {problem}")
            continue
        if args.write:
            target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
        written.append(skill_dir.name)

    verb = "wrote" if args.write else "would write"
    print(f"{verb} {len(written)} manifest(s); {len(skipped)} already had one; "
          f"{len(problems)} need a hand-written manifest")
    for p in problems:
        print(f"  [needs hand] {p}")
    if not args.write:
        print("  preview only. Re-run with --write to apply.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

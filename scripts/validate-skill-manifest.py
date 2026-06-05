#!/usr/bin/env python3
"""validate-skill-manifest.py — validate a skill.json against the M5 manifest schema (issue #31).

Usage:
    python3 scripts/validate-skill-manifest.py <path/to/skill.json> [...]
    python3 scripts/validate-skill-manifest.py --selftest

Exit codes:
    0 — every manifest validates
    1 — at least one manifest failed validation
    2 — usage / config error (schema missing, file unreadable)

Pure stdlib + `jsonschema`. No network. The schema lives at
schemas/skill-manifest.schema.json.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


CLAUDE_DIR = Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude"))
SCHEMA_PATH = CLAUDE_DIR / "schemas" / "skill-manifest.schema.json"
SAMPLES_DIR = CLAUDE_DIR / "schemas" / "tests" / "skill-manifest-samples"


def load_validator():
    if not SCHEMA_PATH.exists():
        print(f"error: schema not found at {SCHEMA_PATH}", file=sys.stderr)
        sys.exit(2)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_file(validator, path):
    """Return (ok: bool, errors: list[str])."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, [f"could not read/parse: {e}"]
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if not errors:
        return True, []
    return False, [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]


def run_selftest(validator):
    """Validate the bundled valid/invalid sample manifests."""
    ok_path = SAMPLES_DIR / "valid.json"
    bad_path = SAMPLES_DIR / "invalid.json"
    failures = []

    ok, errs = validate_file(validator, ok_path)
    if not ok:
        failures.append(f"valid.json should PASS but failed: {errs}")
    else:
        print(f"✓ {ok_path.name} validates")

    bad_ok, _ = validate_file(validator, bad_path)
    if bad_ok:
        failures.append("invalid.json should FAIL but passed")
    else:
        print(f"✓ {bad_path.name} correctly rejected")

    if failures:
        for f in failures:
            print(f"✗ {f}", file=sys.stderr)
        return 1
    print("selftest OK")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("manifests", nargs="*", help="skill.json manifest path(s) to validate")
    ap.add_argument("--selftest", action="store_true", help="validate the bundled sample manifests")
    args = ap.parse_args()

    validator = load_validator()

    if args.selftest:
        return run_selftest(validator)

    if not args.manifests:
        ap.print_usage()
        return 2

    rc = 0
    for path in args.manifests:
        ok, errors = validate_file(validator, path)
        if ok:
            print(f"✓ {path}: valid")
        else:
            rc = 1
            print(f"✗ {path}: INVALID")
            for e in errors:
                print(f"    - {e}")
    return rc


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""validate-skill-manifest.py — validate a skill.json against the M5 manifest schema (issue #31).

Usage:
    python3 scripts/validate-skill-manifest.py <path/to/skill.json> [...]
    python3 scripts/validate-skill-manifest.py --selftest
    python3 scripts/validate-skill-manifest.py --schema <other.json> <manifest> [...]

The schema is resolved NEXT TO THIS SCRIPT (../schemas/skill-manifest.schema.json), never
from an environment variable. Script and schema ship in one tree and version together, so
reading them from two different trees is how "all 233 validate" becomes a claim about the
machine instead of about the branch: run from a worktree whose schema knows `kind` while
the env points at an older copy that does not, and every manifest reports INVALID with
'kind' was unexpected. `--schema` stays for a deliberate override, which is a stated
argument rather than ambient state.

What is checked beyond the schema, because the schema cannot see it:
  * `name` equals the directory the manifest sits in (only for files named skill.json)
  * no two manifests IN ONE RUN declare the same name

Exit codes:
    0 — every manifest validates
    1 — at least one manifest failed validation
    2 — usage / config error (schema missing, file unreadable)

Pure stdlib + `jsonschema`. No network.
"""
import argparse
import copy
import json
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


BRAIN = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = BRAIN / "schemas" / "skill-manifest.schema.json"
SAMPLES_DIR = BRAIN / "schemas" / "tests" / "skill-manifest-samples"
NEGATIVE_CASES = SAMPLES_DIR / "negative-cases.json"

# Keywords that are a RULE (something a manifest can violate) rather than prose or
# structure. Used by the selftest to assert every rule has a negative fixture: a schema
# rule no fixture exercises is a rule nobody has ever seen fire.
CONSTRAINT_KEYWORDS = {"type", "pattern", "minLength", "maxLength", "enum", "const",
                       "uniqueItems", "required", "propertyNames", "additionalProperties"}

# Keywords that LOOK like a rule and are not one here. Named, because a denominator
# the walker picks by accident is a coverage number nobody can check:
#   `format` is an annotation. jsonschema enforces it only where the optional format
#   extras are installed, so a fixture for it would pass or fail by machine rather than
#   by branch, and `homepage` is guarded by its `pattern`, which IS a rule.
ANNOTATION_KEYWORDS = {"format"}


def constraint_paths(node, path=()):
    """Every constraint keyword in the schema, as a JSON path tuple.

    Two keywords are addressed more finely than the schema writes them, because the
    coarse form lets one fixture stand in for rules it never touches:
      * `required` is emitted per MEMBER (`required/name`). One fixture that drops
        `license` says nothing about whether `name` is enforced.
      * `type` is emitted only where nothing else on the same subschema already pins
        the JSON type. Beside an `enum` or a `const` it is subsumed: no value can
        violate `type` alone, so no fixture can isolate it and its control can never
        pass. Skipping it silently would be the same defect one level up, so it is
        skipped HERE, in one place, with the reason attached.
    """
    out = []
    if not isinstance(node, dict):
        return out
    for key, value in node.items():
        here = path + (key,)
        if key == "type" and ("enum" in node or "const" in node):
            continue
        if key in CONSTRAINT_KEYWORDS:
            if key == "required" and isinstance(value, list):
                out += [here + (member,) for member in value]
            elif key == "additionalProperties" and isinstance(value, dict):
                out += constraint_paths(value, here)   # a subschema, not a constraint
            else:
                out.append(here)                       # propertyNames: the subschema IS it
            continue
        if isinstance(value, dict):
            out += constraint_paths(value, here)
    return out


def load_schema(path):
    if not Path(path).exists():
        print(f"error: schema not found at {path}", file=sys.stderr)
        sys.exit(2)
    schema = json.loads(Path(path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def make_validator(schema):
    # The format checker is wired so `format` is enforced wherever the optional format
    # extras are installed. It is not what guards `homepage`: without those extras the
    # `uri` checker is not even registered, and with them `javascript:alert(1)` is a
    # well-formed URI that passes. The scheme allowlist is a `pattern` in the schema.
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def directory_errors(path, data):
    """Errors the schema cannot express, because it never sees where the file lives."""
    p = Path(path)
    if p.name != "skill.json":
        return []
    name = data.get("name")
    parent = p.resolve().parent.name
    if isinstance(name, str) and name != parent:
        return [f"name: '{name}' does not match its directory '{parent}'"]
    return []


def validate_file(validator, path):
    """Return (ok: bool, errors: list[str], data: dict | None)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, [f"could not read/parse: {e}"], None
    errors = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
              for e in sorted(validator.iter_errors(data), key=lambda e: list(e.path))]
    if isinstance(data, dict):
        errors += directory_errors(path, data)
    return (not errors), errors, data


def duplicate_name_errors(seen):
    """seen: {name: [paths]}. Duplicates WITHIN THIS RUN only.

    Corpus-wide uniqueness and dependency resolution are deliberately NOT here: this
    script validates the paths it is handed, so a single-file invocation cannot see a
    duplicate and a missing dependency lives in a tree it was never given. Both need the
    package set, which is octo_pkg's: the lock file and the vendor dir are its state, and
    it already refuses an install on identity it cannot resolve.
    """
    out = []
    for name, paths in sorted(seen.items()):
        if len(paths) > 1:
            out.append(f"duplicate name '{name}' in: {', '.join(sorted(paths))}")
    return out


def _delete(schema, path):
    """Remove exactly one rule from a copy of the schema, and return what was removed
    (None when the path names nothing). `required` is addressed per member, so the last
    segment can be an entry in a list rather than a key in an object."""
    node = schema
    for key in path[:-1]:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    last = path[-1]
    if isinstance(node, list):
        if last not in node:
            return None
        node.remove(last)
        return last
    if not isinstance(node, dict):
        return None
    return node.pop(last, None)


def run_selftest(schema):
    """Samples, then a negative fixture per schema rule, each with its mutation control."""
    validator = make_validator(schema)
    failures = []

    for sample, want_ok in ((SAMPLES_DIR / "valid.json", True),
                            (SAMPLES_DIR / "invalid.json", False)):
        ok, errs, _ = validate_file(validator, sample)
        if ok is not want_ok:
            failures.append(f"{sample.name} should {'PASS' if want_ok else 'FAIL'}"
                            f"{': ' + str(errs) if want_ok else ' but passed'}")
        else:
            print(f"✓ {sample.name} {'validates' if want_ok else 'correctly rejected'}")

    if not NEGATIVE_CASES.exists():
        failures.append(f"negative fixtures missing at {NEGATIVE_CASES}")
        cases = []
    else:
        doc = json.loads(NEGATIVE_CASES.read_text(encoding="utf-8"))
        cases = doc.get("cases", [])
        base_ok = not list(validator.iter_errors(doc.get("base", {})))
        if not base_ok:
            failures.append("negative-cases.json: `base` must itself be valid, so every "
                            "fixture is one edit away from a manifest that passes")

    covered = set()
    for case in cases:
        name, rule = case["name"], tuple(case["rule"])
        covered.add(rule)
        errs = list(validator.iter_errors(case["manifest"]))
        if not errs:
            failures.append(f"{name}: accepted by the schema, so it proves nothing")
            continue
        mutated = copy.deepcopy(schema)
        if _delete(mutated, rule) is None:
            failures.append(f"{name}: rule {'/'.join(rule)} is not in the schema")
            continue
        still = list(make_validator(mutated).iter_errors(case["manifest"]))
        if still:
            failures.append(f"{name}: still rejected with {'/'.join(rule)} deleted "
                            f"({still[0].message}), so it does not exercise that rule")
        else:
            print(f"✓ {name}: rejected, and accepted once {'/'.join(rule)} is deleted")

    for rule in constraint_paths(schema):
        if rule not in covered:
            failures.append(f"schema rule {'/'.join(rule)} has no negative fixture; "
                            f"add a case to {NEGATIVE_CASES.name}")

    if failures:
        for f in failures:
            print(f"✗ {f}", file=sys.stderr)
        return 1
    print(f"selftest OK — {len(cases)} rules exercised, each with its mutation control")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("manifests", nargs="*", help="skill.json manifest path(s) to validate")
    ap.add_argument("--selftest", action="store_true",
                    help="validate the bundled samples and the negative fixtures")
    ap.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH),
                    help="schema to validate against (default: the one beside this script)")
    args = ap.parse_args()

    schema = load_schema(args.schema)

    if args.selftest:
        return run_selftest(schema)

    if not args.manifests:
        ap.print_usage()
        return 2

    validator = make_validator(schema)
    rc = 0
    seen = {}
    for path in args.manifests:
        ok, errors, data = validate_file(validator, path)
        if isinstance(data, dict) and isinstance(data.get("name"), str):
            seen.setdefault(data["name"], []).append(str(path))
        if ok:
            print(f"✓ {path}: valid")
        else:
            rc = 1
            print(f"✗ {path}: INVALID")
            for e in errors:
                print(f"    - {e}")
    for dup in duplicate_name_errors(seen):
        rc = 1
        print(f"✗ {dup}")
    return rc


if __name__ == "__main__":
    sys.exit(main())

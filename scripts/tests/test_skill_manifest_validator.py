#!/usr/bin/env python3
"""Unit tests for scripts/validate-skill-manifest.py and the manifest schema.

The point of this module is that the schema is exercised by something OTHER than the
generator's own output. Mutation testing found the hole: the 233 in-repo manifests are
what gen_skill_manifests.py writes, and the generator was written against the schema, so
deleting any single schema rule still left 233/233 valid. A corpus that agrees with the
schema by construction cannot tell you the schema works.

So every rule gets a negative fixture, and every fixture gets a control: with that one
rule deleted from the schema, the fixture must PASS. A fixture that is rejected for some
other reason proves nothing about the rule it claims to cover.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent.parent
SCRIPTS = BRAIN / "scripts"
VALIDATOR = SCRIPTS / "validate-skill-manifest.py"
_REAL_HOME = os.environ.get("HOME")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vsm = _load("validate_skill_manifest_under_test", VALIDATOR)
# Resolved from THIS repo, deliberately not from the module under test. If the module
# ever resolves its schema somewhere else again, that is the defect being tested, and a
# test module that could not even import would report it as an unnamed collection error.
SCHEMA_PATH = BRAIN / "schemas" / "skill-manifest.schema.json"
CASES_PATH = BRAIN / "schemas" / "tests" / "skill-manifest-samples" / "negative-cases.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _run(args, env=None):
    e = dict(os.environ)
    e["HOME"] = _REAL_HOME or e.get("HOME", "")
    e.update(env or {})
    return subprocess.run([sys.executable, str(VALIDATOR), *args],
                          capture_output=True, text=True, env=e)


class TestSchemaIsExercised(unittest.TestCase):
    def test_the_base_fixture_is_itself_valid(self):
        # Every negative fixture is one edit from this. If the base were invalid, a
        # fixture could be rejected for a reason that has nothing to do with its rule.
        errs = list(vsm.make_validator(SCHEMA).iter_errors(CASES["base"]))
        self.assertEqual([e.message for e in errs], [])

    def test_every_schema_rule_has_a_negative_fixture(self):
        covered = {tuple(c["rule"]) for c in CASES["cases"]}
        missing = ["/".join(r) for r in vsm.constraint_paths(SCHEMA) if r not in covered]
        self.assertEqual(missing, [], "schema rules with nothing that exercises them")

    def test_each_fixture_is_rejected_by_the_rule_it_names(self):
        validator = vsm.make_validator(SCHEMA)
        for case in CASES["cases"]:
            with self.subTest(case["name"]):
                self.assertTrue(list(validator.iter_errors(case["manifest"])),
                                "accepted by the full schema")
                mutated = json.loads(json.dumps(SCHEMA))
                self.assertIsNotNone(vsm._delete(mutated, tuple(case["rule"])),
                                     "the rule this fixture names is not in the schema")
                still = list(vsm.make_validator(mutated).iter_errors(case["manifest"]))
                self.assertEqual([e.message for e in still], [],
                                 "still rejected with its rule deleted: the fixture is "
                                 "not what makes that rule fire")

    def test_the_denominator_is_stated_and_not_whatever_the_walker_notices(self):
        # `type` and per-member `required` used to sit outside CONSTRAINT_KEYWORDS, so
        # 22 schema mutations passed every check green while nothing exercised them.
        # `format` stays out ON PURPOSE and is named, because a rule silently dropped
        # and a rule deliberately excluded look identical in a coverage number.
        self.assertIn("type", vsm.CONSTRAINT_KEYWORDS)
        self.assertEqual(vsm.ANNOTATION_KEYWORDS, {"format"})
        paths = vsm.constraint_paths(SCHEMA)
        for member in SCHEMA["required"]:
            self.assertIn(("required", member), paths)
        self.assertNotIn(("required",), paths, "one omission stood in for three fields")
        self.assertNotIn(("properties", "homepage", "format"), paths)
        # subsumed: an enum or a const on the same subschema already pins the type
        self.assertNotIn(("properties", "kind", "type"), paths)
        self.assertIn(("properties", "license", "type"), paths)

    def test_a_non_string_name_is_rejected_by_the_schema_not_by_the_directory_check(self):
        # The concrete hole: with `properties/name/type` gone, {"name": 5} validated,
        # and `directory_errors` waved it through because it only compares a str.
        bad = dict(CASES["base"], name=5)
        self.assertTrue(list(vsm.make_validator(SCHEMA).iter_errors(bad)))
        self.assertEqual(vsm.directory_errors("/anywhere/alpha/skill.json", bad), [],
                         "the directory check is not what catches this, the schema is")

    def test_selftest_exits_zero(self):
        cp = _run(["--selftest"])
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)


class TestChecksTheSchemaCannotMake(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-vsm-"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)

    def _manifest(self, dirname, **over):
        d = self.tmp / dirname
        d.mkdir(parents=True, exist_ok=True)
        man = {"kind": "skill", "name": dirname, "version": "1.0.0",
               "license": "MIT", "description": "d"}
        man.update(over)
        (d / "skill.json").write_text(json.dumps(man) + "\n", encoding="utf-8")
        return d / "skill.json"

    def test_a_name_that_does_not_match_its_directory_is_rejected(self):
        path = self._manifest("alpha", name="beta")
        cp = _run([str(path)])
        self.assertEqual(cp.returncode, 1, cp.stdout)
        self.assertIn("does not match its directory", cp.stdout)

    def test_a_matching_name_passes(self):
        cp = _run([str(self._manifest("alpha"))])
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)

    def test_two_manifests_with_the_same_name_in_one_run_are_reported(self):
        a = self._manifest("gamma")
        b = self.tmp / "delta" / "skill.json"
        b.parent.mkdir()
        # A second directory declaring the first one's identity. Both are schema-valid
        # on their own, which is the point: only seeing them together catches it.
        b.write_text(json.dumps({"kind": "skill", "name": "gamma", "version": "1.0.0",
                                 "license": "MIT"}) + "\n", encoding="utf-8")
        cp = _run([str(a), str(b)])
        self.assertEqual(cp.returncode, 1, cp.stdout)
        self.assertIn("duplicate name 'gamma'", cp.stdout)

    def test_a_javascript_url_is_not_a_homepage(self):
        cp = _run([str(self._manifest("eps", homepage="javascript:alert(1)"))])
        self.assertEqual(cp.returncode, 1, cp.stdout)
        self.assertIn("homepage", cp.stdout)


class TestSchemaResolution(unittest.TestCase):
    def test_the_schema_comes_from_the_tree_the_script_lives_in(self):
        # The defect this replaces: the schema was read from $CLAUDE_DIR, so running the
        # documented command from a worktree resolved the schema of a DIFFERENT tree and
        # reported every manifest INVALID. The env must not be able to decide that.
        stale = Path(tempfile.mkdtemp(prefix="test-vsm-stale-"))
        self.addCleanup(__import__("shutil").rmtree, stale, ignore_errors=True)
        (stale / "schemas").mkdir()
        (stale / "schemas" / "skill-manifest.schema.json").write_text(
            json.dumps({"type": "object", "additionalProperties": False,
                        "properties": {"name": {"type": "string"}}}), encoding="utf-8")
        manifest = BRAIN / "skills" / "querymaster" / "skill.json"
        cp = _run([str(manifest)], env={"CLAUDE_DIR": str(stale)})
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)

    def test_the_whole_in_repo_corpus_validates(self):
        manifests = sorted((BRAIN / "skills").glob("*/skill.json"))
        self.assertTrue(manifests)
        cp = _run([str(m) for m in manifests])
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)


if __name__ == "__main__":
    unittest.main()

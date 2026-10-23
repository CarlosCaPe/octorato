#!/usr/bin/env python3
"""A budgets config the gate cannot read is named, never a silent allow.

budgets.yaml.example shipped an `arms:` map that budget-check.py never read,
so a copied config enforced no cap and every check said OK. budget-check now
names any unrecognised top-level key, or a file with neither `budgets:` nor
`default:`, as a WARN in its output; brain_doctor's finops-enforcement check
reports it as WARN with the fix. No cap is invented and the decision is the
same.

Needs PyYAML:  python3 -m unittest scripts.tests.test_budget_config_shape
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
ARMS = Path(__file__).resolve().parent / "budget-config-samples" / "arms_shape.yaml"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bc = _load("budget_check_shape", SCRIPTS / "budget-check.py")


class BudgetConfigShape(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="budget-shape-"))
        self.yaml_path = self.tmp / "budgets.yaml"
        self.patches = [mock.patch.object(bc, "BUDGETS_YAML", self.yaml_path),
                        mock.patch.object(bc, "BUDGETS_JSON", self.tmp / "none.json"),
                        mock.patch.dict(os.environ, {"HOME": str(self.tmp), "USERPROFILE": str(self.tmp)})]
        for p in self.patches:
            p.start()
        self.runs = 0
        self.prof = mock.patch.object(bc, "_profiler_spend", self._fake)
        self.prof.start()

    def _fake(self):
        self.runs += 1
        return {"example_arm": 1e6}

    def tearDown(self):
        self.prof.stop()
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_arms_shaped_config_is_named_and_the_decision_is_unchanged(self):
        shutil.copy(ARMS, self.yaml_path)
        v = bc.evaluate()
        self.assertEqual(v["status"], "OK")              # same decision as before: nothing read
        self.assertEqual(self.runs, 0)                   # and no cap invented from `arms:`
        joined = " | ".join(v["config_warnings"])
        self.assertIn("unrecognised top-level key(s) ignored: arms", joined)
        self.assertIn("neither budgets: nor default:", joined)
        self.assertEqual(v["config_fix"], "convert to the budgets: list documented in budget-check.py")

    def test_the_warning_is_printed_in_both_output_modes(self):
        shutil.copy(ARMS, self.yaml_path)
        for argv, stream in ((["--json"], "err"), ([], "out")):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch("sys.stdin", io.StringIO("")), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(bc.main(argv), 0)
            text = (err if stream == "err" else out).getvalue()
            self.assertIn("WARN", text, argv)
            self.assertIn("arms", text, argv)
            if argv:
                self.assertIn("config_warnings", json.loads(out.getvalue()))

    def test_the_documented_shape_and_the_tracked_example_read_clean(self):
        import yaml
        example = yaml.safe_load((ROOT / "budgets.yaml.example").read_text(encoding="utf-8"))
        self.assertEqual(bc.config_problems(example), [])
        self.assertEqual(bc.config_problems({"budgets": [], "spend_json": "x"}), [])
        self.assertEqual(bc.config_problems({}), [])
        shutil.copy(ROOT / "budgets.yaml.example", self.yaml_path)
        v = bc.evaluate()
        self.assertNotIn("config_warnings", v)
        self.assertEqual(v["status"], "HARD_STOP")       # its example_arm cap is read now

    def test_a_config_that_does_not_parse_is_named(self):
        self.yaml_path.write_text("budgets: [\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            v = bc.evaluate()
        self.assertEqual(v["status"], "OK")
        self.assertIn("failed to parse", " ".join(v["config_warnings"]))

    def test_wrong_inner_types_are_named(self):
        self.assertIn("budgets: is not a list", " ".join(bc.config_problems({"budgets": {"a": {}}})))
        self.assertIn("not a mapping", " ".join(bc.config_problems(["x"])))


class DoctorFinopsShape(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="doctor-finops-"))
        os.symlink(SCRIPTS, self.root / "scripts")
        self.bd = _load("brain_doctor_finops", SCRIPTS / "brain_doctor.py")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def check(self):
        with mock.patch.object(self.bd, "CLAUDE_DIR", self.root):
            return self.bd.check_finops_enforcement(False)

    def test_an_arms_shaped_config_is_a_warn_with_the_fix(self):
        shutil.copy(ARMS, self.root / "budgets.yaml")
        r = self.check()
        self.assertEqual(r.status, self.bd.WARN)
        self.assertIn("arms", r.message)
        self.assertIn("convert to the budgets: list documented in budget-check.py", r.hint)

    def test_the_documented_shape_passes(self):
        shutil.copy(ROOT / "budgets.yaml.example", self.root / "budgets.yaml")
        self.assertEqual(self.check().status, self.bd.PASS)


if __name__ == "__main__":
    unittest.main()

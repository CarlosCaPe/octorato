#!/usr/bin/env python3
"""brain_doctor's Runtime_Registry checks (v11 spec 202610141000, AC-01, AC-03).

runtime-registry         registry/runtimes.yaml present, parseable, complete;
                         a `supported` entry maps the four tiers (AC-08).
runtime-doc-agreement    same harnesses and statuses as the doc's Runtimes table.
runtime-census-evidence  fail closed: every census harness present, no unknown
                         harness id, no repeated key, exact statuses, every
                         `supported` names its PINNED doctor check in
                         `evidence` and that check does not FAIL, and a Gemini/Codex
                         `supported` needs a census record that shows shell,
                         file write and file edit blocked.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain_doctor  # noqa: E402

PASS, WARN, FAIL = brain_doctor.PASS, brain_doctor.WARN, brain_doctor.FAIL
_R = brain_doctor.Result
FAKE_CHECKS = [
    ("fake-ok", lambda fix: _R("fake-ok", PASS, "ok")),
    ("fake-warn", lambda fix: _R("fake-warn", WARN, "drift")),
    ("fake-fail", lambda fix: _R("fake-fail", FAIL, "broken")),
    ("fake-slow", lambda fix: _R("fake-slow", PASS, "should not run standalone")),
]


TIERS = {"mechanical": "m-slug", "bulk": "b-slug", "build": "x-slug", "judgment": "j-slug"}


def _entry(name, status, **extra):
    e = {"name": name, "status": status, "instruction_file": "X.md", "hook_config": "h.json",
         "block_contract": ["exit 2"], "tool_map": {"Bash": "Bash"},
         "tiers": dict(TIERS) if status == "supported" else None,
         "unprojected": {"events": [], "matchers": []}}
    e.update(extra)
    return e


BASE = {"schema": 1, "runtimes": {
    "claude-code": _entry("Claude Code", "supported", evidence="brain_doctor fake-ok (fixture)"),
    "gemini-cli": _entry("Gemini CLI", "gap", census="census/gemini.json",
                         classes_not_blocked=["shell", "file_write", "file_edit"]),
    "codex-cli": _entry("Codex CLI", "gap", census="census/codex.json",
                        classes_not_blocked=["shell", "file_write", "file_edit"]),
}}

DOC = """# Multi-runtime

## Runtimes

| Runtime | Status | How the brain is loaded |
|---|---|---|
| **Claude Code** | `supported` | natively |
| **Gemini CLI** | `gap` | GEMINI.md |
| **Codex CLI** | `gap` | AGENTS.md |

## Next section

| Runtime | Status |
|---|---|
| **Stray** | `gap` |
"""


def _census(blocked: bool | None) -> dict:
    return {"tool_classes": {c: {"harness_blocked_violation": blocked,
                                 "harness_allowed_benign": blocked}
                             for c in ("shell", "file_write", "file_edit", "mcp")}}


class RuntimeRegistryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.reg = self.root / "runtimes.yaml"
        self.doc = self.root / "multi-runtime.md"
        (self.root / "census").mkdir()
        self.census = self.root / "census" / "gemini.json"
        self.write(BASE)
        self.doc.write_text(DOC, encoding="utf-8")
        self.census.write_text(json.dumps(_census(None)), encoding="utf-8")
        (self.root / "census" / "codex.json").write_text(json.dumps(_census(None)), encoding="utf-8")
        for patcher in (mock.patch.object(brain_doctor, "CHECKS", list(brain_doctor.CHECKS) + FAKE_CHECKS),
                        mock.patch.object(brain_doctor, "EVIDENCE_HARNESSES",
                                          {"claude-code": "fake-ok", "cursor": "fake-ok"}),
                        mock.patch.object(brain_doctor, "SLOW_CHECKS",
                                          {**brain_doctor.SLOW_CHECKS, "fake-slow": "fixture"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        getattr(brain_doctor, "_CURRENT_RUN", {}).clear()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, data):
        self.reg.write_text(yaml.safe_dump(data), encoding="utf-8")

    def mutated(self):
        return copy.deepcopy(BASE)

    # (a) presence and parse
    def test_registry_present_and_complete_passes(self):
        r = brain_doctor.check_runtime_registry(False, self.reg)
        self.assertEqual(r.status, PASS, r.message)

    def test_missing_registry_fails(self):
        self.reg.unlink()
        r = brain_doctor.check_runtime_registry(False, self.reg)
        self.assertEqual(r.status, FAIL)
        self.assertIn("missing", r.message)

    def test_unparseable_registry_fails(self):
        self.reg.write_text("runtimes: [unclosed\n", encoding="utf-8")
        self.assertEqual(brain_doctor.check_runtime_registry(False, self.reg).status, FAIL)

    def test_unknown_status_or_missing_field_fails(self):
        d = self.mutated()
        d["runtimes"]["claude-code"]["status"] = "partial"
        del d["runtimes"]["gemini-cli"]["tool_map"]
        self.write(d)
        r = brain_doctor.check_runtime_registry(False, self.reg)
        self.assertEqual(r.status, FAIL)
        self.assertIn("partial", r.message)
        self.assertIn("tool_map", r.message)

    # (a2) AC-08: a supported entry maps the four tiers; a gap entry is not bound
    def test_supported_without_tiers_fails(self):
        d = self.mutated()
        d["runtimes"]["claude-code"]["tiers"] = None
        self.write(d)
        r = brain_doctor.check_runtime_registry(False, self.reg)
        self.assertEqual(r.status, FAIL)
        self.assertIn("claude-code", r.message)
        self.assertIn("AC-08", r.message)

    def test_supported_missing_or_empty_tier_fails(self):
        d = self.mutated()
        del d["runtimes"]["claude-code"]["tiers"]["judgment"]
        d["runtimes"]["claude-code"]["tiers"]["bulk"] = " "
        self.write(d)
        r = brain_doctor.check_runtime_registry(False, self.reg)
        self.assertEqual(r.status, FAIL)
        self.assertIn("bulk, judgment", r.message)

    def test_supported_with_fifth_tier_fails(self):
        d = self.mutated()
        d["runtimes"]["claude-code"]["tiers"]["vendor-special"] = "x"
        self.write(d)
        r = brain_doctor.check_runtime_registry(False, self.reg)
        self.assertEqual(r.status, FAIL)
        self.assertIn("vendor-special", r.message)

    def test_gap_entry_with_tiers_fails(self):
        d = self.mutated()
        d["runtimes"]["codex-cli"]["tiers"] = dict(TIERS)
        self.write(d)
        r = brain_doctor.check_runtime_registry(False, self.reg)
        self.assertEqual(r.status, FAIL)
        self.assertIn("codex-cli", r.message)
        self.assertIn("tiers: null", r.message)

    def test_gap_entry_with_null_tiers_passes(self):
        self.assertIsNone(BASE["runtimes"]["gemini-cli"]["tiers"])
        r = brain_doctor.check_runtime_registry(False, self.reg)
        self.assertEqual(r.status, PASS, r.message)

    # (b) agreement with the doc
    def test_doc_agreement_passes_and_ignores_later_tables(self):
        r = brain_doctor.check_runtime_doc_agreement(False, self.reg, self.doc)
        self.assertEqual(r.status, PASS, r.message)
        self.assertEqual(brain_doctor.runtime_doc_rows(DOC),
                         {"Claude Code": "supported", "Gemini CLI": "gap", "Codex CLI": "gap"})

    def test_status_disagreement_fails(self):
        self.doc.write_text(DOC.replace("| **Gemini CLI** | `gap`", "| **Gemini CLI** | `supported`"),
                            encoding="utf-8")
        r = brain_doctor.check_runtime_doc_agreement(False, self.reg, self.doc)
        self.assertEqual(r.status, FAIL)
        self.assertIn("Gemini CLI: registry gap, doc supported", r.message)

    def test_harness_in_one_side_only_fails(self):
        d = self.mutated()
        d["runtimes"]["cursor"] = _entry("Cursor", "gap")
        self.write(d)
        r = brain_doctor.check_runtime_doc_agreement(False, self.reg, self.doc)
        self.assertEqual(r.status, FAIL)
        self.assertIn("Cursor only in registry", r.message)

    def test_doc_without_runtimes_table_fails(self):
        self.doc.write_text("# Multi-runtime\n\n## Supported runtimes\n", encoding="utf-8")
        r = brain_doctor.check_runtime_doc_agreement(False, self.reg, self.doc)
        self.assertEqual(r.status, FAIL)

    # (c) census evidence
    def test_gap_matching_census_passes(self):
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, PASS, r.message)

    def test_supported_without_blocking_evidence_fails(self):
        d = self.mutated()
        d["runtimes"]["gemini-cli"]["status"] = "supported"
        self.write(d)
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, FAIL)
        self.assertIn("shell", r.message)

    def test_supported_without_census_record_fails(self):
        d = self.mutated()
        d["runtimes"]["gemini-cli"]["status"] = "supported"
        d["runtimes"]["gemini-cli"]["census"] = "census/absent.json"
        self.write(d)
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, FAIL)
        self.assertIn("no readable census record", r.message)

    def test_supported_with_one_class_unblocked_fails(self):
        rec = _census(True)
        rec["tool_classes"]["file_edit"]["harness_allowed_benign"] = None
        self.census.write_text(json.dumps(rec), encoding="utf-8")
        d = self.mutated()
        d["runtimes"]["gemini-cli"]["status"] = "supported"
        self.write(d)
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, FAIL)
        self.assertIn("file_edit", r.message)

    def test_supported_with_full_blocking_evidence_passes(self):
        self.census.write_text(json.dumps(_census(True)), encoding="utf-8")
        d = self.mutated()
        d["runtimes"]["gemini-cli"]["status"] = "supported"
        d["runtimes"]["gemini-cli"]["evidence"] = "brain_doctor runtime-census-evidence (census record)"
        d["runtimes"]["gemini-cli"].pop("classes_not_blocked")
        self.write(d)
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, PASS, r.message)

    def test_gap_listing_wrong_classes_fails(self):
        d = self.mutated()
        d["runtimes"]["gemini-cli"]["classes_not_blocked"] = ["shell"]
        self.write(d)
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, FAIL)

    # (d) fail closed: QA NEEDS-WORK on 094e7fd
    def assertCensusFails(self, *needles):
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, FAIL, r.message)
        for n in needles:
            self.assertIn(n, r.message)
        return r

    def test_deleted_census_entry_fails(self):
        d = self.mutated()
        del d["runtimes"]["gemini-cli"]
        self.write(d)
        self.assertCensusFails("gemini-cli has no registry entry")

    def test_renamed_census_key_marked_supported_fails(self):
        d = self.mutated()
        e = d["runtimes"].pop("gemini-cli")
        e["status"] = "supported"
        e["evidence"] = "brain_doctor fake-ok"
        d["runtimes"]["gemini"] = e
        self.write(d)
        self.assertCensusFails("gemini-cli has no registry entry", "gemini is not a known harness id")

    def test_unknown_supported_harness_fails(self):
        d = self.mutated()
        d["runtimes"]["windsurf"] = _entry("Windsurf", "supported")
        self.write(d)
        self.assertCensusFails("windsurf is not a known harness id")

    def test_supported_without_evidence_field_fails(self):
        d = self.mutated()
        d["runtimes"]["claude-code"].pop("evidence")
        self.write(d)
        self.assertCensusFails("claude-code is supported with no `evidence`")
        self.assertEqual(brain_doctor.check_runtime_registry(False, self.reg).status, FAIL)

    def test_evidence_naming_unknown_check_fails(self):
        d = self.mutated()
        d["runtimes"]["claude-code"]["evidence"] = "brain_doctor no-such-check"
        self.write(d)
        self.assertCensusFails("claude-code evidence names 'no-such-check'")
        # a pin that names an unregistered check is itself a FAIL
        self.pin(claude_code="no-such-check")
        self.assertCensusFails("unknown doctor check 'no-such-check'")

    # (e) pinned evidence, unique keys, exact statuses: QA NEEDS-WORK on c21f1eb
    def test_evidence_self_reference_fails(self):
        d = self.mutated()
        d["runtimes"]["claude-code"]["evidence"] = "brain_doctor runtime-census-evidence"
        d["runtimes"]["cursor"] = _entry("Cursor", "supported",
                                         evidence="brain_doctor runtime-census-evidence")
        self.write(d)
        self.assertCensusFails("claude-code evidence names 'runtime-census-evidence'",
                               "cursor evidence names 'runtime-census-evidence'")

    def test_evidence_naming_unrelated_passing_check_fails(self):
        for other in ("runtime-registry", "repo-identity"):
            d = self.mutated()
            d["runtimes"]["claude-code"]["evidence"] = f"brain_doctor {other}"
            self.write(d)
            self.assertCensusFails(f"claude-code evidence names {other!r}; the only check "
                                   "that evidences claude-code is 'fake-ok'")

    def test_census_harness_evidence_must_be_its_census_check(self):
        self.census.write_text(json.dumps(_census(True)), encoding="utf-8")
        d = self.mutated()
        d["runtimes"]["gemini-cli"].update(status="supported", evidence="brain_doctor fake-ok")
        d["runtimes"]["gemini-cli"].pop("classes_not_blocked")
        self.write(d)
        self.assertCensusFails("gemini-cli evidence names 'fake-ok'")

    def test_duplicate_key_fails_with_the_key_name(self):
        e = _entry("Cursor", "supported", evidence="brain_doctor fake-ok")
        body = yaml.safe_dump({"cursor": e}).replace("\n", "\n  ")
        gap = yaml.safe_dump({"cursor": _entry("Cursor", "gap")}).replace("\n", "\n  ")
        rest = yaml.safe_dump(self.mutated()["runtimes"]).replace("\n", "\n  ")
        # the second `cursor:` used to win silently and turn the first one into `gap`
        self.reg.write_text(f"schema: 1\nruntimes:\n  {rest}{body}{gap}", encoding="utf-8")
        for fn in (brain_doctor.check_runtime_registry, brain_doctor.check_runtime_census_evidence):
            r = fn(False, self.reg)
            self.assertEqual(r.status, FAIL, f"{r.key}: {r.message}")
            self.assertIn("duplicate key 'cursor'", r.message)

    def test_status_casing_and_unknown_status_fail_census_check(self):
        for status in ("Supported", "GAP", "partial"):
            d = self.mutated()
            d["runtimes"]["gemini-cli"]["status"] = status
            self.write(d)
            self.assertCensusFails(f"gemini-cli: status {status!r} is not one of supported, gap")
            self.assertEqual(brain_doctor.check_runtime_registry(False, self.reg).status, FAIL)

    def pin(self, **pins):
        brain_doctor.EVIDENCE_HARNESSES.update({k.replace("_", "-"): v for k, v in pins.items()})

    def test_supported_whose_evidence_check_fails_fails(self):
        self.pin(cursor="fake-fail")
        d = self.mutated()
        d["runtimes"]["cursor"] = _entry("Cursor", "supported", evidence="brain_doctor fake-fail (projection)")
        self.write(d)
        self.assertCensusFails("cursor is supported but its evidence fake-fail FAILs: broken")

    def test_no_entries_checked_fails(self):
        d = self.mutated()
        for rid in list(d["runtimes"]):
            d["runtimes"][f"x-{rid}"] = d["runtimes"].pop(rid)
        self.write(d)
        self.assertCensusFails("gemini-cli has no registry entry", "codex-cli has no registry entry")
        # checked == 0 with nothing else wrong: the guard itself must FAIL, not PASS.
        with mock.patch.object(brain_doctor, "CENSUS_HARNESSES", ()), \
                mock.patch.object(brain_doctor, "load_runtime_registry",
                                  lambda path=None: ({"claude-code": "not a mapping"}, [])):
            r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
            self.assertEqual(r.status, FAIL, r.message)

    def test_evidence_warn_degrades_to_warn(self):
        self.pin(cursor="fake-warn")
        d = self.mutated()
        d["runtimes"]["cursor"] = _entry("Cursor", "supported", evidence="brain_doctor fake-warn")
        self.write(d)
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, WARN, r.message)
        self.assertIn("cursor evidence fake-warn is WARN: drift", r.message)

    def test_slow_evidence_not_run_is_not_verified(self):
        self.pin(claude_code="fake-slow")
        d = self.mutated()
        d["runtimes"]["claude-code"]["evidence"] = "brain_doctor fake-slow"
        self.write(d)
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, WARN, r.message)
        self.assertIn("not verified", r.message)
        brain_doctor._CURRENT_RUN["fake-slow"] = _R("fake-slow", PASS, "ran in the full profile")
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, PASS, r.message)

    # the tracked brain itself
    def test_live_registry_and_doc_pass_all_three(self):
        mock.patch.stopall()  # the live registry is checked against the real pins
        for fn in (brain_doctor.check_runtime_registry, brain_doctor.check_runtime_doc_agreement):
            r = fn(False)
            self.assertEqual(r.status, PASS, f"{r.key}: {r.message}")
        # standalone, gate-liveness (a SLOW check) is not run: WARN, never FAIL.
        r = brain_doctor.check_runtime_census_evidence(False)
        self.assertNotEqual(r.status, FAIL, r.message)


if __name__ == "__main__":
    unittest.main()

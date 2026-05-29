#!/usr/bin/env python3
"""Validation test for schemas/trace-event.schema.json (issue #29).

Asserts that every real trace sample under trace-samples/ validates against the
frozen v1 schema, and that the schema's conditional rules actually reject the
malformed events they are meant to catch.

Runs with the standard library only plus `jsonschema`:

    python3 -m unittest schemas.tests.test_trace_event_schema
    python3 schemas/tests/test_trace_event_schema.py

No external services, no network. `jsonschema` is the single third-party
dependency (already used elsewhere in the brain).
"""
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE.parent / "trace-event.schema.json"
SAMPLES_DIR = HERE / "trace-samples"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TraceEventSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = _load_json(SCHEMA_PATH)
        # Fails loudly if the schema itself is not a valid Draft 2020-12 schema.
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def _valid(self, event: dict) -> None:
        self.validator.validate(event)  # raises ValidationError on failure

    def _invalid(self, event: dict) -> None:
        with self.assertRaises(ValidationError):
            self.validator.validate(event)

    # --- positive cases: every real trace sample must validate -----------
    def test_real_samples_validate(self) -> None:
        samples = sorted(SAMPLES_DIR.glob("*.json"))
        self.assertGreater(len(samples), 0, "no trace samples found to validate")
        for path in samples:
            with self.subTest(sample=path.name):
                self._valid(_load_json(path))

    # --- negative cases: the schema must reject malformed events ---------
    def test_status_error_requires_error_string(self) -> None:
        bad = _load_json(SAMPLES_DIR / "skill_fire_error.json")
        bad["error"] = None  # status=error but no message
        self._invalid(bad)

    def test_phase_boundary_name_is_restricted(self) -> None:
        bad = _load_json(SAMPLES_DIR / "phase_boundary.json")
        bad["name"] = "not-a-4d-phase"
        self._invalid(bad)

    def test_additional_properties_rejected(self) -> None:
        bad = _load_json(SAMPLES_DIR / "skill_fire.json")
        bad["typo_field"] = "should not be allowed"
        self._invalid(bad)

    def test_missing_required_field_rejected(self) -> None:
        bad = _load_json(SAMPLES_DIR / "skill_fire.json")
        del bad["status"]
        self._invalid(bad)

    def test_unknown_event_class_rejected(self) -> None:
        bad = _load_json(SAMPLES_DIR / "skill_fire.json")
        bad["event"] = "mystery_event"
        self._invalid(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Tests for the reply panel's source class (FLOW.panel-before-reply, FR-06).

Pins the Basis parser: `Basis` followed by a colon or whitespace, any case,
the label followed by a colon or a `·` separator; a Basis that is empty or
names self / own reasoning stays SELF; a word that merely contains `self`
inside a longer token does not make it SELF.

Stdlib only:

    python3 -m unittest scripts.tests.test_reply_panel_source_class
"""
import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
GATE = SCRIPTS / "g__stop__reply-panel.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("reply_panel_gate_sc", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RP = _load_gate()
BODY = "The row counts match the source table.\n\n"

SOURCED = [
    "Provenance: Basis /home/u/notes.md:11-62 · Engine: main loop",
    "Procedencia: Basis REST de SharePoint DEV (status 200) · /home/u/a.md",
    "Procedencia · Basis: /tmp/a.md",
    "Provenance · Basis: output of `ai-sync` and `brain_doctor.py --fast`",
    "Provenance: basis git log origin/master",
    "Provenance: BASIS: git log",
    "**Provenance:** **Basis** migration.log",
    "Provenance: Basis: scripts/selftest.py",
    "Provenance: Basis: self-review of scripts/x.py, migration.log",
    "Provenance: Basis: git log, checked myself",
    "Provenance: Basis: /opt/selfhosted/run.log",
]

SELF = [
    "Provenance: Basis: myself",
    "Provenance: Basis: self-evident",
    "Provenance: Basis: SELF · Engine: main loop",
    "Provenance: Basis self",
    "Provenance: Basis own reasoning",
    "Provenance: Basis: my own reasoning",
    "Provenance: Basis: razonamiento propio",
    "Provenance: Basis: eigene Überlegung",
    "Provenance: Basis: eigene Ueberlegung",
    "Provenance: Basis: git log + own reasoning",
    "Provenance: Basis: migration.log, myself",
    "Provenance: Basis: SELF (no sources)",
    "Provenance: Basis",
    "Provenance: Basis · Engine: main loop",
    "Provenance: Basis none",
    "Provenance: Basis —",
    "Provenance: Engine: main loop",
    "Provenance: Basisfoo bar",
    "Procedencia: /tmp/panel_block.txt",
    "Procedencia · Basis: razonamiento propio",
    "Provenance: Basis: a.md\nProvenance: Basis self",
]


class SourceClassTests(unittest.TestCase):
    def test_sourced(self):
        for footer in SOURCED:
            with self.subTest(footer=footer):
                self.assertEqual(RP.source_class(BODY + footer), "SOURCED")

    def test_self(self):
        for footer in SELF:
            with self.subTest(footer=footer):
                self.assertEqual(RP.source_class(BODY + footer), "SELF")

    def test_no_footer_is_self(self):
        self.assertEqual(RP.source_class("Done."), "SELF")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for g__stop__no-menu-question.py (rule COMMS.no-menu-question).

Pins the matcher (closing choice question in ES and EN, quote/code/blockquote
exemptions, the irreducible-step list, the hatch), the block-once contract, the
config loader (a readable YAML overrides the defaults key by key, an unreadable
one keeps them) and the wiring (hooks.json, rules.yaml, friction signatures).

Stdlib only:

    python3 -m unittest scripts.tests.test_no_menu_question
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
GATE = SCRIPTS / "g__stop__no-menu-question.py"
FIXTURES = ROOT / "registry" / "fixtures" / "COMMS.no-menu-question"


def _load_gate():
    spec = importlib.util.spec_from_file_location("no_menu_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(payload: dict, env_extra: dict = None) -> dict:
    env = dict(os.environ)
    env.pop("OCTO_KERNEL_OPEN", None)
    if env_extra:
        env.update(env_extra)
    cp = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                        capture_output=True, text=True, env=env)
    out = cp.stdout.strip()
    return {"rc": cp.returncode, "json": json.loads(out) if out else None}


def _transcript(tmp: Path, text: str) -> str:
    p = tmp / "t.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "text", "text": text}]}}, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return str(p)


class MatcherTest(unittest.TestCase):
    def setUp(self):
        self.g = _load_gate()
        self.cfg = self.g._load_config()

    def _menu(self, text):
        return self.g.find_menu(text, self.cfg)[1]

    def test_es_alternatives_at_the_end_block(self):
        self.assertTrue(self._menu("Listo. ¿Lo cableo como Stop gate o como PreToolUse?"))
        self.assertEqual(self._menu("Listo. ¿Lo dejamos en Stop o en PreToolUse?"), "alternatives")

    def test_en_alternatives_at_the_end_block(self):
        self.assertEqual(self._menu("Done. Do you want the Stop gate or the PreToolUse one?"), "opener")

    def test_go_ahead_opener_without_alternatives_blocks(self):
        self.assertEqual(self._menu("Tests pass. ¿Procedo?"), "opener")
        self.assertEqual(self._menu("Tests pass. Shall I proceed?"), "opener")

    def test_decision_does_not_block(self):
        self.assertEqual(self._menu("Listo. Lo cableo como Stop gate; ya está en hooks.json."), "")

    def test_question_followed_by_decision_does_not_block(self):
        self.assertEqual(self._menu("¿Stop o PreToolUse? Elegí Stop, ya está cableado."), "")

    def test_quoted_question_does_not_block(self):
        self.assertEqual(self._menu('Ya contesté. Él escribió: "¿Lo quieren en PDF o en Excel?"'), "")

    def test_code_block_question_does_not_block(self):
        self.assertEqual(self._menu("Borrador:\n\n```\n¿Prefieren mensual o quincenal?\n```"), "")

    def test_blockquote_question_does_not_block(self):
        self.assertEqual(self._menu("Último del hilo.\n> ¿Avanzamos con A o B?"), "")

    def test_footer_after_the_question_is_ignored(self):
        text = "¿Dale a A o B?\n\nProvenance: Basis: x · Engine: y · Touched: none · Verified: z"
        self.assertTrue(self._menu(text))

    def test_disclose_one_liner_after_the_question_is_ignored(self):
        text = "¿Dale a A o B?\n💡 Unlock-suggestion: export FOO=1"
        self.assertTrue(self._menu(text))

    def test_menu_ok_hatch(self):
        self.assertEqual(self._menu("Listo. ¿A o B? menu-ok"), "")

    def test_irreducible_step_is_let_through(self):
        self.assertEqual(self._menu("Listo. ¿Exportas OCTO_MERGE_APPROVE=417 o lo dejo en la rama?"), "")
        self.assertEqual(self._menu("Done. Which password, the old one or the new one?"), "")
        self.assertEqual(self._menu("Listo. ¿Hago el pago hoy o mañana?"), "")

    def test_information_question_is_not_a_menu(self):
        self.assertEqual(self._menu("Export listo. ¿Qué correo del cliente uso?"), "")

    def test_accent_folding_in_openers(self):
        self.assertEqual(self._menu("Listo. ¿Cual prefieres?"), "opener")
        self.assertEqual(self._menu("Listo. ¿Cuál prefieres?"), "opener")


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.g = _load_gate()

    def test_unreadable_file_keeps_defaults(self):
        cfg = self.g._load_config("/nonexistent/no-menu-question.yaml")
        self.assertEqual(cfg["openers"], list(self.g._DEFAULT_OPENERS))
        self.assertEqual(cfg["irreducible"], list(self.g._DEFAULT_IRREDUCIBLE))

    def test_readable_file_overrides_key_by_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.yaml"
            p.write_text("# comment\nopeners:\n  - zig\nirreducible:\n", encoding="utf-8")
            cfg = self.g._load_config(str(p))
        self.assertEqual(cfg["openers"], ["zig"])
        self.assertEqual(cfg["irreducible"], list(self.g._DEFAULT_IRREDUCIBLE))

    def test_shipped_config_parses_both_keys(self):
        cfg = self.g._load_config()
        self.assertIn("dale", cfg["openers"])
        self.assertIn("send-ok", cfg["irreducible"])


class GateProcessTest(unittest.TestCase):
    def test_blocks_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = _transcript(Path(tmp), "Listo. ¿Lo cableo como Stop o como PreToolUse?")
            first = _run({"transcript_path": t, "stop_hook_active": False})
            second = _run({"transcript_path": t, "stop_hook_active": True})
        self.assertEqual(first["rc"], 0)
        self.assertEqual(first["json"]["decision"], "block")
        self.assertIn("/choice", first["json"]["reason"])
        self.assertIn("SIN-MENÚ", first["json"]["reason"])
        self.assertIsNone(second["json"])

    def test_last_assistant_message_fallback(self):
        r = _run({"last_assistant_message": "Done. Shall I proceed?", "stop_hook_active": False})
        self.assertEqual(r["json"]["decision"], "block")

    def test_fails_open_on_garbage_stdin(self):
        cp = subprocess.run([sys.executable, str(GATE)], input="not json",
                            capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(cp.stdout.strip(), "")

    def test_selftest_passes(self):
        cp = subprocess.run([sys.executable, str(GATE), "--selftest", str(FIXTURES)],
                            capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)


class WiringTest(unittest.TestCase):
    def test_registered_on_stop_in_hooks_json(self):
        hooks = json.loads((ROOT / "hooks.json").read_text(encoding="utf-8"))
        cmds = [h.get("command", "") for grp in hooks["Stop"] for h in grp.get("hooks", [])]
        self.assertTrue(any("g__stop__no-menu-question.py" in c for c in cmds))

    def test_rule_entry_and_fixture_twins(self):
        rules = (ROOT / "registry" / "rules.yaml").read_text(encoding="utf-8")
        self.assertIn("- id: COMMS.no-menu-question", rules)
        self.assertIn("anchor: No menu questions", rules)
        self.assertIn("### No menu questions", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
        names = {p.name for p in FIXTURES.glob("*.json")}
        self.assertIn("violation.json", names)
        self.assertIn("benign.json", names)
        for v in ("es", "en", "opener", "quoted", "codeblock", "blockquote", "merge"):
            self.assertIn(f"violation_{v}.json", names)
            self.assertIn(f"benign_{v}.json", names)

    def test_friction_signature_matches_the_block_text(self):
        raw = json.loads((ROOT / "registry" / "friction-signatures.json").read_text(encoding="utf-8"))
        rows = [s for s in raw["signatures"] if s["gate"] == "g__stop__no-menu-question.py"]
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0]["pattern"], GATE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

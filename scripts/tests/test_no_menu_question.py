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
        # First-person "hago": the agent's act, so the payment is a noun in its choice.
        self.assertEqual(self._menu("Listo. ¿Hago el pago hoy o mañana?"), "opener")
        self.assertEqual(self._menu("Listo. ¿Haces el pago hoy o mañana?"), "")

    def test_information_question_is_not_a_menu(self):
        self.assertEqual(self._menu("Export listo. ¿Qué correo del cliente uso?"), "")

    def test_accent_folding_in_openers(self):
        self.assertEqual(self._menu("Listo. ¿Cual prefieres?"), "opener")
        self.assertEqual(self._menu("Listo. ¿Cuál prefieres?"), "opener")


class StructuralRuleTest(unittest.TestCase):
    """QA findings 3-7 and the trailing-filler case: the closing question is
    judged by its shape, not by a fixed opener list."""

    def setUp(self):
        self.g = _load_gate()
        self.cfg = self.g._load_config()

    def _menu(self, text):
        return self.g.find_menu(text, self.cfg)[1]

    def test_short_permission_questions_block(self):
        for q in ("¿Lo lanzo?", "¿Lo despliego?", "¿Merge?", "¿Va?", "Ready to merge?",
                  "Should we ship it?", "¿Te lo mando?", "¿Lo envío?", "¿Continúo?",
                  "Can I delete the branch?", "OK to merge?", "Want me to open the PR?"):
            with self.subTest(q=q):
                self.assertTrue(self._menu("Listo. " + q))

    def test_short_permission_twins_allow(self):
        for d in ("Lo lanzo.", "Lo despliego.", "Merge hecho.", "Va.", "Ready to merge.",
                  "We ship it today."):
            with self.subTest(d=d):
                self.assertEqual(self._menu("Listo. " + d), "")

    def test_third_person_and_info_yes_no_questions_allow(self):
        self.assertEqual(self._menu("Listo. ¿Te llegó el correo?"), "")
        self.assertEqual(self._menu("Listo. ¿Lo tienes a mano?"), "")

    def test_numbered_list_then_selection_blocks(self):
        text = "Opciones:\n1. Stop gate\n2. PreToolUse\n¿Cuál?"
        self.assertEqual(self._menu(text), "selection")
        self.assertEqual(self._menu("Opciones:\n- Stop gate\n- PreToolUse\nWhich?"), "selection")
        self.assertEqual(self._menu("Opciones:\n1. Stop gate\n2. PreToolUse\nVa la 1."), "")

    def test_selection_without_a_list_allows(self):
        self.assertEqual(self._menu("Revisé el hilo. ¿Cuál?"), "")

    def test_trailing_decoration_is_trimmed(self):
        for q in ("**¿Lo lanzo?**", "¿Lo lanzo? 🚀", "(¿Lo lanzo?)", "_Shall I merge it?_ ",
                  "Proceed? (y/n)", "Proceed? [Y/n]", "¿Sigo? (s/n)"):
            with self.subTest(q=q):
                self.assertTrue(self._menu("Listo. " + q))
        self.assertEqual(self._menu("Listo. **Lo lanzo.** 🚀"), "")
        self.assertEqual(self._menu("Listo. Proceeding. (y/n)"), "")

    def test_irreducible_matches_whole_words_only(self):
        self.assertEqual(self._menu("Listo. ¿Apago hoy o mañana?"), "alternatives")
        self.assertEqual(self._menu("Listo. ¿Pago hoy o mañana?"), "")
        self.assertEqual(self._menu("Listo. ¿Consentimos el flujo A o el B?"), "alternatives")
        self.assertEqual(self._menu("Done. Can you give consent now or later?"), "")

    def test_irreducible_must_be_the_object(self):
        self.assertTrue(self._menu("Done. Should I do the login refactor now or after lunch?"))
        self.assertEqual(self._menu("Done. Can you do the login now or after lunch?"), "")
        self.assertTrue(self._menu("Done. Should I do the login now or after lunch?"))
        self.assertTrue(self._menu("Done. Should I ship the login refactor or the cart fix?"))

    def test_info_question_with_or_allows(self):
        self.assertEqual(self._menu("Listo. ¿Cuál es la ruta o el puerto que usa tu servidor?"), "")
        self.assertEqual(self._menu("Listo. ¿El servidor corre en tu Linux o en tu Windows?"), "")
        self.assertEqual(self._menu("Listo. ¿Cuál uso, la ruta o el puerto que usa tu servidor?"),
                         "alternatives")
        self.assertEqual(self._menu("Listo. ¿Stop o PreToolUse?"), "alternatives")

    def test_menu_ok_still_escapes_structural_hits(self):
        self.assertEqual(self._menu("Listo. ¿Lo lanzo? menu-ok"), "")

    def test_short_filler_after_the_question_does_not_hide_it(self):
        self.assertTrue(self._menu("Both builds pass. Should I use A or B? I'll wait."))
        self.assertTrue(self._menu("Listo. ¿Lo lanzo? Quedo atento."))
        self.assertEqual(self._menu("Both builds pass. Should I use A or B? I'll use A."), "")
        self.assertEqual(
            self._menu("Should I use A or B? I use A, it is merged and deployed now."), "")

    def test_invalid_regex_in_config_is_skipped(self):
        cfg = dict(self.cfg)
        cfg["permission_patterns"] = ["(unclosed"] + list(self.cfg["permission_patterns"])
        self.assertTrue(self.g.find_menu("Listo. ¿Lo lanzo?", cfg)[1])

    def test_shipped_config_lists_every_key(self):
        text = (ROOT / "registry" / "no-menu-question.yaml").read_text(encoding="utf-8")
        for key in self.g._KEYS:
            self.assertIn(f"\n{key}:\n", text)


class QaRoundTwoTest(unittest.TestCase):
    """QA NEEDS-WORK on 90d843e: diagnostic questions are information,
    selection openers and statement menus block, and an irreducible term
    exempts only the step the operator performs. Twins are one edit apart."""

    def setUp(self):
        self.g = _load_gate()
        self.cfg = self.g._load_config()

    def _menu(self, text):
        return self.g.find_menu(text, self.cfg)[1]

    def _twins(self, pairs):
        for menu, info in pairs:
            with self.subTest(menu=menu):
                self.assertTrue(self._menu("Listo. " + menu))
            with self.subTest(info=info):
                self.assertEqual(self._menu("Listo. " + info), "")

    def test_diagnostic_questions_are_information(self):
        self._twins([
            ("¿La compilación la dejo verde o sigue fallando?",
             "¿La compilación quedó verde o sigue fallando?"),
            ("¿El token expiró o lo revoco?", "¿El token expiró o lo revocaste?"),
            ("¿Lo dejo en staging o en producción?", "¿Está en staging o en producción?"),
            ("Do I put it on staging or prod?", "Is it on staging or prod?"),
        ])

    def test_verbless_fragment_is_still_a_menu(self):
        self.assertEqual(self._menu("Listo. ¿Stop o PreToolUse?"), "alternatives")
        self.assertEqual(self._menu("Listo. Is it better to use A or B?"), "alternatives")

    def test_selection_openers_block_without_a_list(self):
        self._twins([("¿Con cuál sigo?", "¿Con cuál sigue?"), ("¿Cuál uso?", "¿Cuál usas?"),
                     ("¿Por cuál empiezo?", "¿Por cuál empezaste?")])

    def test_statement_menus_block(self):
        self._twins([
            ("Let me know which you prefer: A or B.", "Let me know which you ran: A or B."),
            ("Dime cuál prefieres: A o B.", "Dime cuál corriste: A o B."),
            ("I can deploy now, or wait for QA. Thoughts?",
             "I can deploy now, and wait for QA. Thoughts?"),
            ("Good to merge?", "Good to merge."),
            ("Any objection to merging?", "No objection to merging."),
        ])

    def test_irreducible_only_when_the_operator_acts(self):
        self._twins([
            ("Should I ship the login or the cart fix?", "Could you ship the login or the cart fix?"),
            ("¿Te paso el login?", "¿Me das el login?"),
            ("¿Confirmo el pago?", "¿Confirmas el pago?"),
            ("Should I approve the merge?", "Please approve the merge."),
            ("¿Hago el pago hoy o mañana?", "¿Haces el pago hoy o mañana?"),
        ])
        self.assertEqual(
            self._menu("Listo. ¿Exportas OCTO_MERGE_APPROVE=417 o lo dejo en la rama?"), "")

    def test_near_miss_inputs_stay_linear(self):
        import time
        for txt in ("¿" + "a o " * 5000 + "b", "lo " * 7000 + "x?",
                    "let me know " + "x " * 10000 + ".", "¿Lo lanzo?" + " 🚀" * 10000,
                    "¿cual " + "abc " * 5000 + "?", "(" * 20000 + "?"):
            with self.subTest(n=len(txt)):
                t0 = time.perf_counter()
                self.g.find_menu("Listo. " + txt, self.cfg)
                self.assertLess(time.perf_counter() - t0, 1.0)


class QaRoundThreeTest(unittest.TestCase):
    """QA NEEDS-WORK on fc8e107: a second-person diagnostic "A or B" question
    about the operator's world passes; a preference verb or an agent action
    in the same question still blocks. Twins are one edit apart."""

    def setUp(self):
        self.g = _load_gate()
        self.cfg = self.g._load_config()

    def _menu(self, text):
        return self.g.find_menu(text, self.cfg)[1]

    def _twins(self, pairs):
        for menu, info in pairs:
            with self.subTest(menu=menu):
                self.assertTrue(self._menu("Listo. " + menu))
            with self.subTest(info=info):
                self.assertEqual(self._menu("Listo. " + info), "")

    def test_second_person_diagnostics_pass(self):
        self._twins([
            ("¿Te pongo el error 403 o el 401?", "¿Te sale el error 403 o el 401?"),
            ("¿Uso el banner rojo o el amarillo?", "¿Ves el banner rojo o el amarillo?"),
            ("Do you prefer the red banner or the yellow one?",
             "Do you see the red banner or the yellow one?"),
            ("Do you want a 403 or a 401?", "Do you get a 403 or a 401?"),
            ("Do you prefer the CSV or the Excel?", "Do you need the CSV or the Excel?"),
            ("Do you want the old repo or the new one?", "Do you mean the old repo or the new one?"),
            ("¿Te muevo al repo viejo o al nuevo?", "¿Te refieres al repo viejo o al nuevo?"),
            ("¿Prefieres el CSV o el Excel?", "¿Necesitas el CSV o el Excel?"),
            ("¿Abro en Chrome o en Safari?", "¿Abre en Chrome o en Safari?"),
        ])

    def test_agent_action_or_preference_still_blocks(self):
        for menu in ("¿Prefieres A o B?", "¿Ves el banner rojo o lo cambio?",
                     "Do you need the CSV or should I build the Excel?",
                     "Do you think A or B?", "Do you like A or B?",
                     "Do you need me to ship A or B?", "¿Stop o PreToolUse?"):
            with self.subTest(menu=menu):
                self.assertTrue(self._menu("Listo. " + menu))

    def test_solicit_after_alternatives(self):
        self._twins([
            ("Desplegué hoy o avisé a QA. ¿Tú qué dices?", "Desplegué hoy y avisé a QA. ¿Tú qué dices?"),
            ("Desplegué hoy o avisé a QA. ¿Qué opinas?", "Desplegué hoy y avisé a QA. ¿Qué opinas?"),
            ("I deployed now or told QA. Your call?", "I deployed now and told QA. Your call?"),
            ("Desplegué hoy o avisé a QA. Tú qué dices.", "Desplegué hoy y avisé a QA. Tú qué dices."),
        ])

    def test_near_miss_inputs_stay_linear(self):
        import time
        for txt in ("¿te " + "a" * 20000 + " o b?", "do you " + "x" * 20000 + " or y?",
                    "¿ves " + "a o " * 5000 + "b?", "do you " + "see " * 5000 + "or b?",
                    "¿se " + "se " * 7000 + "abre o b?"):
            with self.subTest(n=len(txt)):
                t0 = time.perf_counter()
                self.g.find_menu("Listo. " + txt, self.cfg)
                self.assertLess(time.perf_counter() - t0, 0.2)


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
        for v in ("es", "en", "opener", "quoted", "codeblock", "blockquote", "merge",
                  "short_es", "short_en", "one_word", "numbered_list", "decorated",
                  "yn_suffix", "word_boundary", "irreducible_object", "info_or",
                  "trailing_filler", "diag_build", "diag_token", "diag_env_es",
                  "diag_env_en", "select_con", "select_uso", "select_por", "statement_en",
                  "statement_es", "solicit", "good_to_merge", "objection",
                  "irreducible_noun", "irreducible_login", "irreducible_pay",
                  "irreducible_approve", "pay_first_person", "diag2p_sale_es",
                  "diag2p_ves_es", "diag2p_see_en", "diag2p_get_en", "diag2p_need_en",
                  "diag2p_mean_en", "diag2p_refieres_es", "diag2p_necesitas_es",
                  "diag2p_abre_es", "solicit_tu_es"):
            self.assertIn(f"violation_{v}.json", names)
            self.assertIn(f"benign_{v}.json", names)

    def test_friction_signature_matches_the_block_text(self):
        raw = json.loads((ROOT / "registry" / "friction-signatures.json").read_text(encoding="utf-8"))
        rows = [s for s in raw["signatures"] if s["gate"] == "g__stop__no-menu-question.py"]
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0]["pattern"], GATE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

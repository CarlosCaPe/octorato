#!/usr/bin/env python3
"""commit-msg language gate — the public octorato repo is English-only.

WHY. The brain (~/.claude == the octorato repo) is published open-source; its
git history is world-visible forever, and commit messages are part of it. The
operator's rule is that the public repo ships in English (i18n lives as EN/ES/DE
assets, never as Spanish commit prose). Spanish subjects drifted in because the
operator writes in Spanish and the model followed; a prose rule loses to that
pull under load, so this fires on its own as a git-hook.

WHAT. Invoked by `.githooks/commit-msg` with the path to COMMIT_EDITMSG. It reads
the human-written part of the message (git's diff comment and the trailer block
stripped) and BLOCKS the commit (exit 1) when it reads as Spanish, printing why.
English passes (exit 0). Escape hatch: put `lang-ok` on a line, or commit with
`git commit --no-verify`.

SCOPE. The hook lives in octorato's .githooks, so it only guards octorato
commits. Arm repos (private, per-client, often Spanish) are untouched.

SELFTEST. `commit_msg_language_gate.py --selftest <fixture-dir>` runs the
detector against <dir>/violation.txt (must block) and <dir>/benign.txt (must
allow), exiting 0 only if both are correct. That is the fixture-driven liveness
proof brain_doctor runs on every fail-closed gate.
"""
import re
import sys
import unicodedata
from pathlib import Path

# Signals English never uses. Any one of these is enough on its own.
STRONG = ("¿", "¡", "ñ", "Ñ")  # ¿ ¡ ñ Ñ

# Function/content words that are Spanish and NOT common in English commit prose
# or code identifiers. Stored ACCENT-STRIPPED and matched against accent-stripped
# tokens, because real Spanish commit subjects are often typed without accents
# ("mas", "vigia", "indice"): matching only the accented form misses them. A
# message needs >=2 DISTINCT hits to trip, so a lone loanword never blocks
# English. Overlaps with English/code ("no", "base", "final", "solo", "sale",
# "config", "canario") are deliberately excluded.
SPANISH_WORDS = {
    "que", "para", "con", "sin", "por", "una", "unos", "unas", "del", "los",
    "las", "este", "esta", "estos", "estas", "porque", "cuando", "desde",
    "hace", "segun", "tambien", "mas", "asi", "aviso", "correo", "cambio",
    "archivo", "entrada", "entradas", "puente", "silencio", "cliente", "cada",
    "nuevo", "nueva", "nuevos", "nuevas", "propio", "propia", "leer", "todas",
    "todos", "manda", "queda", "quedan", "cierra", "revisa", "numero",
    "indice", "linea", "chico", "chica", "tres", "avisa", "avisar", "envio",
    "pantalla", "campo", "regla", "reglas", "vigia", "vigilancia", "respuesta",
}


def _strip_accents(w: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", w)
                   if unicodedata.category(c) != "Mn")

# A real git trailer key is hyphenated multi-word (Co-Authored-By, Signed-off-by,
# Claude-Session). Requiring the hyphen means a conventional-commit subject like
# "brain: ..." or a Spanish body line "El cambio: ..." is NOT mistaken for a
# trailer and stripped.
TRAILER_RE = re.compile(r"^[A-Za-z]+(-[A-Za-z]+)+:\s")


def human_text(raw: str) -> str:
    """The part a person wrote: drop git's diff comment lines (#...) and the
    trailing trailer block. The subject (first line) is ALWAYS kept: it is the
    most load-bearing line and must never be swallowed as a trailer."""
    lines = [ln for ln in raw.splitlines() if not ln.startswith("#")]
    if not lines:
        return ""
    subject, body = lines[0], lines[1:]
    while body and (not body[-1].strip() or TRAILER_RE.match(body[-1].strip())):
        body.pop()
    return "\n".join([subject] + body)


def looks_spanish(raw: str):
    """(is_spanish, reasons). Conservative: one STRONG char, or >=2 distinct
    unambiguous Spanish function words. `lang-ok` anywhere is an explicit pass."""
    text = human_text(raw)
    if "lang-ok" in text:
        return (False, ["lang-ok override present"])
    reasons = []
    for ch in STRONG:
        if ch in text:
            reasons.append(f"Spanish character {ch!r}")
    tokens = re.findall(r"[a-záéíóúñü]+", text.lower())
    hits = sorted({_strip_accents(t) for t in tokens
                   if _strip_accents(t) in SPANISH_WORDS})
    if len(hits) >= 2:
        reasons.append("Spanish words: " + ", ".join(hits))
    return (bool(reasons), reasons)


def check_message_file(path: str) -> int:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    is_es, reasons = looks_spanish(raw)
    if is_es:
        sys.stderr.write(
            "commit-msg gate: this reads as a non-English (Spanish) commit "
            "message, and octorato is an English-only public repo.\n  "
            + "\n  ".join(reasons) + "\n"
            "Rewrite it in English. Intentional exception: add 'lang-ok' on a "
            "line, or commit with --no-verify.\n")
        return 1
    return 0


def selftest(fixture_dir: str) -> int:
    d = Path(fixture_dir)
    vio, ben = d / "violation.txt", d / "benign.txt"
    if not vio.exists() or not ben.exists():
        sys.stderr.write(f"selftest: missing violation.txt/benign.txt in {d}\n")
        return 1
    fails = []
    if not looks_spanish(vio.read_text(encoding="utf-8"))[0]:
        fails.append("violation.txt did NOT block (detector missed Spanish)")
    if looks_spanish(ben.read_text(encoding="utf-8"))[0]:
        fails.append("benign.txt was BLOCKED (false positive on English)")
    if fails:
        sys.stderr.write("selftest FAIL:\n  " + "\n  ".join(fails) + "\n")
        return 1
    print("commit-msg language gate selftest OK (violation blocks, benign allows)")
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "--selftest":
        return selftest(argv[2] if len(argv) > 2
                        else "registry/fixtures/GENERIC.commit-msg-english-only")
    if len(argv) < 2:
        sys.stderr.write("usage: commit_msg_language_gate.py <commit-msg-file>\n")
        return 2
    return check_message_file(argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))

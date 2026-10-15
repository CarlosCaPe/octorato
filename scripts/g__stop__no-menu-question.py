#!/usr/bin/env python3
"""g__stop__no-menu-question.py: Stop gate: a reply never ENDS on a menu for the operator.

Operator directive, 2026-10-15, verbatim: *"cada que termines en pregunta de
opción múltiple, quiero que apliques choice, siempre, hasta que me llegues ya
con una sugerencia, 0% de preguntas de opción múltiple"*. A reply that closes
with "¿Dale a X o Y?", "Do you want A or B?", "¿Procedo?" hands the choosing
back to the operator on work the agent could decide and do itself. The method
that replaces the menu already exists: `/choice` (commands/choice.md, "From an
Idea to a Decision") develops, debates, weighs, defends and DECIDES. The gate
makes skipping it cost a rewrite turn.

WHEN IT FIRES. In the last assistant reply, the closing sentence (footer,
Disclose one-liners, fenced code, inline code, blockquotes and quoted spans
discarded; trailing emphasis, brackets, emoji and "(y/n)" trimmed; short
courtesy filler after a question such as "I'll wait." skipped) has one of
these shapes, all read from `registry/no-menu-question.yaml`:
  - opener: a go-ahead or preference ask ("¿Dale", "¿Procedo", "Shall I");
  - alternatives: "X o Y" / "A or B" where the agent is the one choosing
    (an agent-action verb such as "¿Cuál uso", "lo revoco", "Do I put", or a
    verbless fragment such as "¿Stop o PreToolUse?");
  - permission: a short yes/no permission ask ("¿Lo lanzo?", "¿Va?",
    "Ready to merge?", "Good to merge?", "Any objection to merging?");
  - selection: "¿Cuál uso?", "¿Con cuál sigo?", "¿Por cuál empiezo?", or a
    bare "¿Cuál?" / "Which one?" right after a list of two or more items;
  - statement: an imperative ask-for-choice with no "?" ("Let me know which
    you prefer: A or B.", "Dime cuál prefieres: A o B.");
  - direction: a first-person ask for direction, with or without options
    ("¿Qué hago?", "¿Cómo sigo?", "What would you like me to do?");
  - solicit: "Thoughts?", "Any preference?", "How would you like to
    proceed?", "Let me know how you'd like to proceed." once alternatives
    were offered earlier in the final paragraph or in a list right before
    ("Opciones: A) migrar ya, B) esperar. How would you like to proceed?").

WHAT DOES NOT FIRE.
  - A diagnostic "X o Y" question about the operator's world with no agent
    action: a verb about state or the operator's past ("¿La compilación quedó
    verde o sigue fallando?", "¿El token expiró o lo revocaste?", "Is it on
    staging or prod?"), a second-person or environment verb that is not a
    preference ("¿Ves el banner rojo o el amarillo?", "¿Te sale el 403 o el
    401?", "Do you need the CSV or the Excel?"), an interrogative lead
    ("¿Cuál es la ruta o el puerto...?") or the operator's things ("tu
    servidor"). "¿Prefieres A o B?" / "Do you want A or B?" still block: the
    answer picks the agent's next step.
  - A question whose irreducible step (send-ok, OCTO_MERGE_APPROVE, a
    password, a login, a payment, a version cut; whole words, as the object)
    is the action the OPERATOR performs: no agent action in the question
    ("¿Me das el login?", "¿Confirmas el pago?"), or the alternative where
    he acts ("¿Exportas OCTO_MERGE_APPROVE=417 o lo dejo en la rama?"). The
    same term as a noun inside the agent's own choice ("Should I ship the
    login or the cart fix?", "¿Hago el pago hoy o mañana?") still blocks.
  - A quoted question (someone else's words), a question inside a code block
    or a blockquote (a draft, a transcript), a line carrying `menu-ok`.
  - A reply whose last sentence is a decision, even when a question sits
    earlier in the text: the rule is about how the turn CLOSES.

Blocks ONCE (stop_hook_active), like its siblings defer-today and
draft-promise. The block message says what to do instead: run /choice and
return the decision, executed or in execution; leave only the irreducible
operator step, stated as a step with its command.

FAILS OPEN. Any error exits 0 and silently, the same contract as the other
draft gates of this class (defer-today, draft-promise, unsourced-*).

Deliberate escape: put `menu-ok` on the line.

Stdin:  {"transcript_path": str, "stop_hook_active": bool,
         "last_assistant_message": str (optional fallback), ...}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(_HERE, "..", "registry", "no-menu-question.yaml")
HATCH = "menu-ok"

_FOOTER = re.compile(r"^\s*[>*_\s]*(Provenance|Procedencia|Herkunft)\s*:", re.IGNORECASE)
# Disclose one-liners that CLAUDE.md orders to the END of a reply: they are
# machine receipts, not the closing sentence of the prose.
_DISCLOSE = re.compile(r"^\s*(💡|☠)\s*\S*\s*(Unlock|Prune)[- ]?suggestion\s*:", re.IGNORECASE)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE = re.compile(r"`[^`\n]*`")
_QUOTED = re.compile(r'"[^"]*"|[“”][^“”]*[“”]|«[^»]*»', re.DOTALL)
_BLOCKQUOTE = re.compile(r"^\s*>")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# "X o Y" / "A or B" inside the question: the menu itself. `o` and `or` as
# whole words; "o bien" and "either ... or" fall in the same net.
_ALTERNATIVES = re.compile(r"\s(o|u|or)\s", re.IGNORECASE)
_LIST_ITEM = re.compile(r"^\s*(\d{1,2}[.)]|[-*•]|[a-zA-Z][.)])\s+\S")
_YN_SUFFIX = re.compile(r"[\(\[]\s*(y|yes|s|si|sí)\s*/\s*(n|no)\s*[\)\]]\s*$", re.IGNORECASE)
_TAIL_PUNCT = "*_~)]}>»”\"'`.…"

# Built-in defaults, overridden key by key by the YAML when it is readable.
# Kept here so a missing config never turns the gate off (a gate that depends
# on a file that can be deleted is not wired) and so the selftest proves the
# real path. Matching is on the folded text (lower case, no accents) unless a
# key says otherwise.
_DEFAULT_OPENERS = [
    # Spanish go-ahead / preference asks
    "dale", "le doy", "procedo", "proceso", "sigo", "avanzo", "lo hago", "hago",
    "lo cableo", "lo mando", "lo aplico", "lo cierro", "lo subo", "lo dejo",
    "quieres", "quieren", "prefieres", "te parece", "te late", "te va",
    "cuál prefieres", "cual prefieres", "cuál quieres", "cual quieres",
    "cuál elijo", "cual elijo", "cuál tomo", "cual tomo", "qué prefieres",
    # English go-ahead / preference asks
    "shall i", "shall we", "should i", "should we", "do you want", "would you like",
    "want me to", "do you prefer", "which do you prefer", "which one", "which would",
    "go ahead", "proceed", "ok to", "okay to",
]
# Short yes/no permission questions, as regexes on the lower-cased text with
# the leading ¿ removed. Spanish clitic + first-person verb ("¿Lo lanzo?",
# "¿Te lo mando?") is matched on the UNFOLDED text so "¿Te llegó?" (third
# person, an information question) does not read as "llego".
_DEFAULT_PERMISSION = [
    r"^((se|te|me|le|les)\s+)?(lo|la|los|las|le|les|te)\s+[a-zñáéíóú]{2,}(o|amos|emos|imos|oy)\b",
    r"^(sigo|arranco|lanzo|agrego|abro|procedo|continuo|continúo|empiezo|comienzo|aplico|subo|mando|envío|envio|corro|ejecuto|borro|elimino|despliego|mergeo|cierro|reinicio|instalo|publico|pusheo|commiteo|cambio|activo|desactivo|seguimos|arrancamos|avanzamos|procedemos|lanzamos|hacemos|desplegamos|mergeamos)\b",
    r"^(va|dale|ok|okay|sale|listo|merge|mergeo|ship|ship it|go|continue|seguimos|procedo|lo hago|good to go|lgtm|green light)$",
    r"^(should|shall|can|could|may) (i|we)\b",
    r"^(want|would you like|do you want) me to\b",
    r"^(do|would) you (want|like)\b",
    r"^ready to\b",
    r"^(is it |are you )?ok(ay)? (to|if i|if we|with)\b",
    r"^proceed\b",
    r"^(merge|ship|deploy|release|push)( it| this| now)?$",
    r"^(good|ok|okay|safe|fine|alright|all right|clear) to (merge|ship|deploy|go|proceed|push|release|land)\b",
    r"^(any )?objections? (to|if)\b",
    r"^alg[uú]na? (objeci[oó]n|inconveniente|problema) (con|en|si|para)\b",
    r"^confirmo\b",
]
# A numbered or bulleted list followed by one of these closing questions is a
# menu: "1. A / 2. B / ¿Cuál?".
_DEFAULT_SELECTION = [
    r"^(cual|cuales|que opcion|cual opcion|cual de (estas|esas|ellas|los|las|estos|esos))\b",
    r"^(which|which one|which option|which of (these|those|them)|what option|pick one|number)\b",
]
# An "A o B" question led by one of these is an information question about the
# operator's world ("¿Cuál es la ruta o el puerto que usa tu servidor?"), not a
# menu, unless a choice verb follows the interrogative ("¿Cuál uso, A o B?").
_DEFAULT_INFO_INTERROGATIVES = [
    "que", "cual", "cuales", "donde", "cuando", "quien", "quienes", "como", "cuanto",
    "cuantos", "cuanta", "cuantas", "por que", "what", "where", "when", "who", "whose",
    "how", "why", "which",
]
_DEFAULT_CHOICE_VERBS = [
    "uso", "elijo", "escojo", "tomo", "hago", "pongo", "dejo", "mando", "aplico",
    "prefieres", "quieres", "eliges", "escoges", "usamos", "elegimos", "hacemos",
    "should i", "should we", "shall i", "shall we", "do i", "do we", "do you prefer",
    "do you want", "would you like", "would you prefer", "you want", "you prefer",
    "you'd prefer", "mejor", "better", "conviene",
    # preference asks: "¿Cuál te gusta más, A o B?", "¿Qué opción te late más?"
    "te gusta", "te gustan", "te late", "te laten", "te convence", "te convencen",
    "you like", "you'd like",
]
# An "A o B" question that only asks about the operator's things ("tu
# servidor", "your server") is an information question unless it also carries
# an agent action (a permission pattern or a choice verb).
_DEFAULT_INFO_MARKERS = [
    "tu", "tus", "tienes", "usas", "your", "you use", "do you have", "you have",
]
# A short sentence (under 8 words) of pure courtesy after the closing question
# does not hide it: "Should I use A or B? I'll wait."
_DEFAULT_FILLER = [
    "i'll wait", "i will wait", "waiting", "standing by", "let me know", "your call",
    "up to you", "thanks", "thank you", "espero", "quedo atento", "quedo atenta",
    "quedo pendiente", "avisame", "tu dime", "dime", "me dices", "gracias",
    "tu decides", "como prefieras", "lo que digas",
]
_DEFAULT_IRREDUCIBLE = [
    "send-ok", "octo_merge_approve", "octo_qa_ok", "contraseña", "password",
    "login", "inicia sesión", "pago", "pagar", "payment", "pay", "cobro",
    "consentimiento", "consent", "corte de versión", "version cut", "release tag",
    "clic de consentimiento", "2fa", "otp", "código de verificación",
]
# An irreducible term is the OBJECT of the question only when nothing but a
# function word, a time word or punctuation follows it: "¿Hago el pago hoy o
# mañana?" passes, "Should I ship the login refactor or the cart fix?" does
# not ("login" there modifies "refactor").
_DEFAULT_OBJECT_FOLLOWERS = [
    "de", "del", "a", "al", "para", "por", "con", "en", "o", "u", "y", "e", "ya",
    "hoy", "manana", "ahora", "of", "for", "to", "with", "on", "in", "or", "and",
    "now", "today", "tomorrow", "the", "el", "la", "lo", "los", "las", "one",
]

# Second-person questions about the operator's world and state ("¿El token
# expiró o lo revocaste?", "¿Está en staging o en producción?", "Is it on
# staging or prod?"): a bare "X o Y" carrying one of these and no agent action
# is information, not a menu. Regexes on the lower-cased body, accents KEPT so
# the preterite "quedó" is not the first-person "quedo".
_DEFAULT_INFO_VERBS = [
    r"\b(está|están|estás|es|son|eres|era|eran|fue|fueron|hay|había|sigue|siguen|queda|quedan|tiene|tienen|corre|corren|falla|fallan|existe|existen|funciona|funcionan|apunta|apuntan)\b",
    r"\b[a-zñáéíóú]{2,}(aste|iste|asteis|isteis|aron|ieron)\b",
    r"\b[a-zñáéíú]{2,}ó\b",
    r"\b(is|are|was|were|did|does|has|had|isn't|aren't|wasn't|weren't|didn't|doesn't|hasn't|it's)\b",
]
# A first-person agent action anywhere in the question, beyond the openers,
# permission patterns and choice verbs: a clitic plus a first-person verb in
# the second alternative ("¿El token expiró o lo revoco?"). Third-person
# irregular preterites and neuter "lo + adjective" are excluded.
_DEFAULT_AGENT_ACTION = [
    r"(?<!\w)(lo|los|las|le|les|me|te|se|nos)\s+(?!(hizo|puso|tuvo|quiso|dijo|trajo|supo|pudo|vino|anduvo|condujo|produjo|propuso|supuso|nuevo|viejo|mismo|bueno|malo|otro|correcto|primero|segundo|tercero|ultimo|unico|necesario|cierto|propio|contrario|demas|largo|justo)\b)[a-zñ]{2,}(o|amos|emos|imos)\b",
]
# Selection asks that are a menu even with no list before them: "¿Cuál uso?",
# "¿Con cuál sigo?", "¿Por cuál empiezo?", "Which one should I take?".
# Regexes on the folded body.
_DEFAULT_SELECTION_OPENERS = [
    r"^((con|por|en|de|para|a)\s+)?(cual|cuales|que opcion|cual opcion)\s+([\w-]+\s+){0,3}?(sigo|uso|empiezo|elijo|escojo|tomo|arranco|hago|aplico|voy|agarro|priorizo|mando|despliego|lanzo|mergeo|dejo|pongo|seguimos|usamos|empezamos|arrancamos|elegimos|hacemos|aplicamos|vamos|priorizamos)\b",
    r"^((with|from|on)\s+)?which( one| option)?\s+(should|shall|do|would|can)\s+(i|we)\b",
    r"^((with|from)\s+)?which( one| option)?\s+(do|would) you (prefer|want|like)\b",
]
# A closing STATEMENT that asks the operator to choose is a menu without the
# "?": "Let me know which you prefer: A or B.", "Dime cuál prefieres: A o B.",
# "Pick one: A or B.". Regexes on the folded sentence.
_DEFAULT_STATEMENT_MENU = [
    r"^(let me know|tell me|dime|avisame|me dices|me avisas|decide|tu decides|you decide)\b.*\b(prefer|prefers|prefieres|want|quieres|go with|vamos con|vas con|should i|should we|do i|elijo|uso|sigo)\b",
    r"^(pick|choose|elige|escoge|decide entre|choose between|pick between)\b",
]
# A closing solicitation that hands back a choice offered in the sentence
# before it: "I can deploy now, or wait for QA. Thoughts?". Blocks only when
# the previous sentence carries alternatives. Regexes on the folded body.
_DEFAULT_SOLICIT = [
    r"^(thoughts|opinions?|preferences?|ideas|objections?|your call|up to you|what do you think|what do you say|any thoughts|que opinas|que piensas|que dices|tu que dices|tu que opinas|tu que piensas|que me dices|tu decides|tu dime|como prefieras|como veas|opiniones|ideas)$",
    r"^(any|a) (preference|preferences|favorite|favourite|pick)$",
    r"^(alguna )?(preferencia|opinion)$",
    r"^(so )?how (would|do) you (like|want) (us )?to (proceed|continue|go|move forward)( (from here|here|now|next))?$",
    r"^(let me know|tell me|dime|avisame|me dices) (how|como) (you(?:'|\u2019)?d like|you would like|you want|quieres|prefieres) (to )?(proceed|continue|go|move forward|seguir|proceder|continuar|avanzar)\b",
    r"^(y )?(como|por donde) (quieres|prefieres|quieren) (seguir|proceder|continuar|avanzar|ir)( (ahora|entonces|aqui|con esto))?$",
]
# First-person asks for direction: the agent hands the next step back with no
# options at all ("¿Qué hago?", "What would you like me to do?", "How should I
# proceed?", "¿Cómo sigo?"). They block with or without alternatives before
# them. Regexes on the folded body.
_DEFAULT_DIRECTION = [
    r"^(y |entonces |ahora )?(que|como) (hago|hacemos|sigo|seguimos|procedo|procedemos|continuo|continuamos|le hago|le hacemos)( (ahora|entonces|aqui|con esto|con eso))?$",
    r"^(que|como) (quieres|prefieres|quieren) que (haga|hagamos|siga|sigamos|proceda|procedamos|continue|continuemos)\b",
    r"^(so |then |and )?(what|how) (should|shall|do|can) (i|we) (do|proceed|continue|go|move forward)( (now|next|here|then|from here|with (this|that)))?$",
    r"^(so |then )?what (would|do) you (like|want) (me|us) to do\b",
    r"^(so |then )?how (would|do) you (like|want) (me|us) to (proceed|continue|go|move forward)\b",
]
# Inline option markers: a sentence (or list) that carries two or more of
# them offers alternatives even with no "o"/"or" ("Opciones: A) migrar ya,
# B) esperar."). Counted per sentence, never matched across it, so the scan
# stays linear. Regexes on the folded sentence.
_DEFAULT_OFFER_MARKERS = [
    r"(?:^|\s)\(?[a-d1-4][).](?=\s)",
    r"\b(?:opcion|option|plan|alternativa|alternative) [a-d1-4]\b",
]
# The irreducible exemption holds inside an agent choice only for the
# alternative where the OPERATOR is the one acting: a second-person verb or an
# imperative ("¿Exportas OCTO_MERGE_APPROVE=417 o lo dejo?", "Can you do the
# login now or after lunch?"). Regexes on the folded alternative.
_DEFAULT_OPERATOR_ACTION = [
    r"^((me|nos|te)\s+)?[a-zn]{1,}(as|es)\b",
    r"^(please|por favor)\b",
    r"\b(can|could|will|would) you\b",
    r"^(approve|confirm|export|enter|type|paste|sign|log in|aprueba|confirma|exporta|escribe|pega|firma|inicia|dame|da)\b",
]

# Second-person diagnostic questions about the operator's world: "¿Ves el
# banner rojo o el amarillo?", "¿Te sale el 403 o el 401?", "¿Abre en Chrome o
# en Safari?", "Do you need the CSV or the Excel?". With no agent action they
# are information, not a menu. Preference verbs (prefer, want, like, rather,
# quieres, prefieres) are excluded: their answer picks the agent's next step.
# Regexes on the lower-cased body, accents KEPT.
_DEFAULT_DIAGNOSTIC = [
    r"^((te|se|me|lo|la|los|las)\s+)?(ves|viste|veías|necesitas|necesitabas|necesitaste|ocupas|tienes|tenías|usas|usabas|buscas|recibes|obtienes|abres|cargas|entras|corres|corriste|recibiste|lees|notas|encuentras|sabes|recuerdas|puedes|estás|eres|trabajas|ejecutas|escribes|refieres|acuerdas|conectas|quedas|sientes|ubicas|identificas)\b",
    r"^(te|le|les)\s+(?!(lo|la|los|las|le|les)\b)[a-zñáéíóú]{2,}(a|e|an|en|as|es)\b",
    r"^(se\s+)?(abre|abren|carga|cargan|sale|salen|aparece|aparecen|marca|muestra|truena|responde|regresa|devuelve|arranca|compila|conecta|pasa|llega|salta|dice|pide|da|tarda|jala|sirve|cae|levanta|termina|imprime)\b",
    r"^(do|did|are|were|have|had)\s+you\s+(?!(want|wanna|prefer|like|wish|mind|rather|think|feel|agree|approve|ok|okay|fine|good|happy|comfortable|need me|want me|lean|leaning)\b)[a-z]{2,}\b",
]

_KEYS = {
    "openers": _DEFAULT_OPENERS,
    "permission_patterns": _DEFAULT_PERMISSION,
    "selection_patterns": _DEFAULT_SELECTION,
    "info_interrogatives": _DEFAULT_INFO_INTERROGATIVES,
    "choice_verbs": _DEFAULT_CHOICE_VERBS,
    "info_markers": _DEFAULT_INFO_MARKERS,
    "filler": _DEFAULT_FILLER,
    "irreducible": _DEFAULT_IRREDUCIBLE,
    "object_followers": _DEFAULT_OBJECT_FOLLOWERS,
    "info_verbs": _DEFAULT_INFO_VERBS,
    "agent_action_patterns": _DEFAULT_AGENT_ACTION,
    "selection_openers": _DEFAULT_SELECTION_OPENERS,
    "statement_menu_patterns": _DEFAULT_STATEMENT_MENU,
    "solicit_patterns": _DEFAULT_SOLICIT,
    "operator_action_patterns": _DEFAULT_OPERATOR_ACTION,
    "diagnostic_patterns": _DEFAULT_DIAGNOSTIC,
    "direction_asks": _DEFAULT_DIRECTION,
    "offer_markers": _DEFAULT_OFFER_MARKERS,
}


def _fold(text: str) -> str:
    """Lower-case and strip accents so 'cuál' and 'cual' are one entry."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()


def _load_config(path: str = _CONFIG_FILE) -> dict:
    """Two-level YAML subset (`key:` then `  - item`), no third-party parser.

    Same shape as registry/send-ask.yaml. An unreadable or empty file yields
    the built-in defaults; a readable file replaces a key only when it lists
    at least one item under it.
    """
    cfg = {k: list(v) for k, v in _KEYS.items()}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return cfg
    parsed: dict = {}
    key = None
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("- ") else raw.rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")) and line.endswith(":"):
            key = line[:-1].strip()
            parsed.setdefault(key, [])
            continue
        if key and line.lstrip().startswith("- "):
            item = line.lstrip()[2:].strip().strip('"').strip("'")
            if item:
                parsed[key].append(item)
    for k, items in parsed.items():
        if items:
            cfg[k] = items
    return cfg


def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _last_assistant_text(transcript_path: str) -> str:
    """Text blocks of the LAST assistant entry; stops there whether or not it
    has text, so a stale earlier reply is never linted."""
    text_parts: list = []
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
        elif isinstance(content, str):
            text_parts.append(content)
        break
    return "\n".join(text_parts)


def _strip_non_prose(text: str) -> str:
    text = _FENCE.sub("", text)
    text = re.sub(r"```.*", "", text, flags=re.DOTALL)   # unclosed trailing fence
    text = _INLINE.sub("", text)
    kept = []
    for ln in text.splitlines():
        if _FOOTER.match(ln) or _DISCLOSE.match(ln) or _BLOCKQUOTE.match(ln):
            continue
        if HATCH in ln:
            continue
        kept.append(ln)
    return "\n".join(kept)


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF or ch in "️‍⃣"
            or unicodedata.category(ch) in ("So", "Sk"))


def _trim_tail(sentence: str) -> str:
    """Drop trailing decoration so `**¿Lo lanzo?** 🚀`, `Proceed? (y/n)` and
    `(¿Va?)` all end in their `?`: whitespace, markdown emphasis, closing
    brackets and quotes, emoji, and a (y/n)-style suffix. Index-based, so a
    long decorated tail costs linear time."""
    s = sentence
    while True:
        before = s
        s = _YN_SUFFIX.sub("", s).rstrip()
        end = len(s)
        while end and (s[end - 1] in _TAIL_PUNCT or s[end - 1].isspace()
                       or _is_emoji(s[end - 1])):
            if s[end - 1] == "." and not s[:end].endswith("?."):
                break
            end -= 1
        s = s[:end]
        if s == before:
            return s


def _words(text: str) -> list:
    return re.findall(r"[\w'-]+", text)


def _is_filler(sentence: str, cfg: dict) -> bool:
    folded = _fold(sentence).strip(" .!¡?¿*_")
    if len(_words(folded)) >= 8:
        return False
    return any(folded == _fold(f) or folded.startswith(_fold(f) + " ")
               or folded.startswith(_fold(f) + ",") for f in cfg.get("filler", ()))


def _sentences(prose: str) -> list:
    prose = _QUOTED.sub(" ", prose)
    return [s.strip() for s in _SENTENCE_SPLIT.split(prose) if s.strip()]


def closing_question(prose: str, cfg: dict) -> str:
    """The sentence the turn closes on. Trailing pieces that are only
    decoration (an emoji, a `(y/n)`) are skipped, and so is short filler that
    follows a question ("Should I use A or B? I'll wait.")."""
    sentences = _sentences(prose)
    while sentences and not re.search(r"\w", _trim_tail(sentences[-1])):
        sentences.pop()
    if not sentences:
        return ""
    last = sentences[-1]
    i = len(sentences) - 1
    while i > 0 and _is_filler(sentences[i], cfg):
        i -= 1
        if _trim_tail(sentences[i]).endswith("?"):
            return sentences[i]
    return last


def last_sentence(prose: str) -> str:
    """The closing sentence of the prose, quoted spans removed first."""
    sentences = _sentences(prose)
    return sentences[-1] if sentences else ""


def _match_any(patterns, text: str) -> bool:
    for pat in patterns:
        try:
            if re.search(pat, text):
                return True
        except re.error:
            continue
    return False


def _word_in(term: str, text: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", text) is not None


def _irreducible_object(folded: str, cfg: dict) -> bool:
    """True when an irreducible operator step is the object of the question:
    the term matches as a whole word and what follows it is punctuation, the
    end, or a function/time word (never a noun it modifies)."""
    followers = {_fold(w) for w in cfg.get("object_followers", ())}
    for word in cfg.get("irreducible", ()):
        term = _fold(word)
        for m in re.finditer(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", folded):
            rest = folded[m.end():]
            if not rest.strip() or not rest[0].isspace():
                return True            # end of the question or punctuation
            nxt = re.match(r"\s*([\w'-]+)", rest)
            if nxt is None or nxt.group(1) in followers:
                return True
    return False


def _operator_owns_irreducible(body: str, cfg: dict) -> bool:
    """Inside an agent choice, the irreducible exemption holds only for an
    alternative where the operator is the one acting ("¿Exportas
    OCTO_MERGE_APPROVE=417 o lo dejo en la rama?"). A login, a payment or a
    password that is only a noun inside the agent's own choice ("Should I ship
    the login or the cart fix?") does not exempt the menu."""
    for seg in _ALTERNATIVES.split(" " + body + " "):
        seg = seg.strip(" ,;:")
        if seg.lower() in ("o", "u", "or") or not seg:
            continue
        if _irreducible_object(seg, cfg) and _match_any(
                cfg.get("operator_action_patterns", ()), seg):
            return True
    return False


def _body(sentence: str) -> str:
    return _trim_tail(sentence).strip().lstrip("¿¡*_([ \t").rstrip("?").strip()


def _agent_action(body: str, raw_body: str, cfg: dict) -> str:
    """Which agent-action marker the question carries, or ''."""
    if _match_any(cfg.get("direction_asks", ()), body):
        return "direction"
    for opener in cfg.get("openers", ()):
        op = _fold(opener)
        if body == op or body.startswith(op + " ") or body.startswith(op + ","):
            return "opener"
    if _match_any(cfg.get("permission_patterns", ()), raw_body):
        return "permission"
    if _match_any(cfg.get("selection_openers", ()), body):
        return "selection"
    if any(_word_in(_fold(v), body) for v in cfg.get("choice_verbs", ())):
        return "choice"
    if _match_any(cfg.get("agent_action_patterns", ()), raw_body):
        return "choice"
    return ""


def _offers(sentence: str, cfg: dict) -> bool:
    """True when a sentence lays out alternatives: a whole-word o/u/or, or two
    or more inline option markers ("A) migrar ya, B) esperar")."""
    folded = _fold(sentence)
    if _ALTERNATIVES.search(" " + folded + " "):
        return True
    count = 0
    for pat in cfg.get("offer_markers", ()):
        try:
            count += len(re.findall(pat, folded))
        except re.error:
            continue
    return count >= 2


def _offered_before(prose: str, sentence: str, cfg: dict) -> bool:
    """Whether alternatives were offered before the closing sentence: in an
    earlier sentence of the same final paragraph, or in a list of two or more
    items right before (inside that paragraph or as the paragraph before)."""
    paragraphs = [p for p in re.split(r"\n\s*\n", prose) if p.strip()]
    for k in range(len(paragraphs) - 1, -1, -1):
        sents = _sentences(paragraphs[k])
        if sentence not in sents:
            continue
        idx = len(sents) - 1 - sents[::-1].index(sentence)
        if any(_offers(s, cfg) for s in sents[:idx]):
            return True
        lines = paragraphs[k].splitlines()
        if k > 0:
            lines = paragraphs[k - 1].splitlines() + lines
        return sum(1 for ln in lines if _LIST_ITEM.match(ln)) >= 2
    return False


def is_choice_question(sentence: str, cfg: dict, prose: str = "", prev: str = "") -> str:
    """Return why the sentence is a menu ('opener', 'alternatives',
    'permission', 'selection', 'statement', 'solicit'), or '' when it is not a
    choice ask or its object is an irreducible step the operator performs.

    `prev` is the sentence before the closing one; a bare solicitation
    ("Thoughts?", "How would you like to proceed?") is a menu only when `prev`,
    an earlier sentence of the final paragraph or a list right before offered
    alternatives."""
    trimmed = _trim_tail(sentence.strip())
    body = _fold(_body(trimmed))
    offered = bool(prev) and _offers(prev, cfg) or bool(prose) and _offered_before(prose, sentence, cfg)
    if not trimmed.endswith("?"):
        # Statement-form menus: an imperative ask-for-choice closes the turn
        # the same way a question does.
        if _match_any(cfg.get("statement_menu_patterns", ()), body):
            return "statement"
        if _match_any(cfg.get("solicit_patterns", ()), body.rstrip(".!¡ ")) and offered:
            return "solicit"
        return ""
    folded = _fold(trimmed)
    # permission patterns read the accented text: "¿Te llegó?" is not "llego"
    raw_body = _body(trimmed).lower()
    action = _agent_action(body, raw_body, cfg)
    if _irreducible_object(folded, cfg):
        # The operator's own step (no agent action at all, or the alternative
        # he performs) passes; a noun inside the agent's choice does not.
        if not action or _operator_owns_irreducible(body, cfg):
            return ""
    if action in ("opener", "direction"):
        return action
    if _ALTERNATIVES.search(" " + body + " "):
        if action:
            return "alternatives"
        wh = next((w for w in cfg.get("info_interrogatives", ())
                   if body == _fold(w) or body.startswith(_fold(w) + " ")), None)
        info_marker = any(_word_in(_fold(m), body) for m in cfg.get("info_markers", ()))
        # A bare "X o Y" with no agent action is a menu only when it is a
        # verbless fragment ("¿Stop o PreToolUse?"); a verb about the
        # operator's world or state makes it a diagnostic question.
        info_verb = _match_any(cfg.get("info_verbs", ()), raw_body) \
            or _match_any(cfg.get("diagnostic_patterns", ()), raw_body)
        if not wh and not info_marker and not info_verb:
            return "alternatives"
    if action in ("permission", "selection"):
        return action
    if _match_any(cfg.get("solicit_patterns", ()), body) and offered:
        return "solicit"
    if prose and _match_any(cfg.get("selection_patterns", ()), body):
        items = sum(1 for ln in prose.splitlines() if _LIST_ITEM.match(ln))
        if items >= 2:
            return "selection"
    return ""


def find_menu(raw: str, cfg: dict) -> tuple:
    """(sentence, reason) when the reply closes on a choice ask, else ('', '')."""
    prose = _strip_non_prose(raw)
    if not prose.strip():
        return "", ""
    sentence = closing_question(prose, cfg)
    sentences = _sentences(prose)
    prev = ""
    if sentence in sentences:
        idx = len(sentences) - 1 - sentences[::-1].index(sentence)
        prev = sentences[idx - 1] if idx > 0 else ""
    reason = is_choice_question(sentence, cfg, prose, prev)
    return (sentence, reason) if reason else ("", "")


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if data.get("stop_hook_active"):
        return 0

    try:
        raw = ""
        transcript = data.get("transcript_path") or ""
        if transcript:
            raw = _last_assistant_text(transcript)
        if not raw.strip():
            raw = data.get("last_assistant_message") or ""
        if not raw.strip():
            return 0
        sentence, reason = find_menu(raw, _load_config())
    except Exception:
        return 0

    if not reason:
        return 0

    try:
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"🔀 SIN-MENÚ: el turno cierra con una pregunta de opción múltiple al "
                f"operador (…{sentence[:90]}…). Directiva canónica 2026-10-15: 0% de "
                f"preguntas de opción múltiple. Corre /choice (desarrolla, debate, "
                f"pondera, defiende, decide) y regresa con la DECISIÓN ya ejecutada o "
                f"en ejecución, no con el menú. Solo queda sin decidir el paso "
                f"irreducible del operador (dinero, consentimiento, envío, merge, "
                f"corte de versión, login), y viaja como paso con su comando, no como "
                f"pregunta. Para dejar la pregunta a propósito, pon `{HATCH}` en la línea. "
                f"Ver CLAUDE.md 'No menu questions'."
            ),
        }))
        _journal_deny(f"turn closed on a choice question to the operator: {sentence[:90]}", data)
    except Exception:
        pass
    return 0


# -- v8 kernel journal (Phase 4, v8-kernel.md) --------------------------------
_KERNEL_RULE = "COMMS.no-menu-question"


def _journal_deny(reason, payload=None, tool_use_id=None) -> None:
    """Mirror this refusal into the refusing process's journal. FAIL-OPEN by
    contract: every error is swallowed and the verdict is unchanged."""
    try:
        import importlib.util
        _path = os.path.join(_HERE, "kernel_proc.py")
        _spec = importlib.util.spec_from_file_location("_kernel_proc_journal", _path)
        _kp = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_kp)
        _payload = payload if isinstance(payload, dict) else {}
        _kp.journal_deny(_KERNEL_RULE, reason,
                         tool_use_id if tool_use_id is not None else _payload.get("tool_use_id"),
                         _kp.resolve_pid(_payload))
    except Exception:
        pass


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/COMMS.no-menu-question"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)

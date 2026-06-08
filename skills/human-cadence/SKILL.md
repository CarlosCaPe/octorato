---
name: human-cadence
description: "The 10 no-rules that strip AI-tells from any written output so text reads like a person, not a model, and costs fewer tokens. Inverted from the soyfelixgo TikTok 'humanizer' prompt into hard DON'Ts. ALWAYS-ON delivery discipline: every output (chat, email, doc, commit body, PR description) passes these before it ships. CLAUDE.md §Communication carries the summary; the verbatim source + per-language blocklists + reconciliation live here. Load when drafting prose, humanizing AI text, or auditing why a draft 'sounds like AI'."
metadata:
  short-description: "10 anti-AI-tell no-rules for human-sounding, token-lean output"
  type: reference
  source: "https://www.tiktok.com/@soyfelixgo/video/7642065153533496598 (caption = the humanizer prompt)"
---

# Human Cadence: The 10 No-Rules

## Why

AI text has a fingerprint: em-dashes everywhere, triads, "not only X but Y", rigid transitions, filler openers, uniform sentence length, voiceless perfect grammar. Readers feel it before they can name it, and it erodes trust, the same way an unsourced gut-call does. These 10 no-rules remove the fingerprint. Side effect: **less filler = fewer tokens**. Human cadence and token-economy are the same edit.

This is a **delivery discipline**, not a content rule. It changes *how* the answer is written, never *what* is true or sourced. The Provenance footer still ships; facts still cite. We sound like a person who knows, not a model performing.

## The 10 No-Rules (DON'T)

| # | DON'T | DO instead |
|---|-------|-----------|
| 1 | **No em-dash (—) anywhere.** | Use periods, commas, or line breaks. |
| 2 | **No AI filler vocabulary** (blocklist below). | Plain words. Say the thing. |
| 3 | **No "not only X, but Y" / "no solo X, sino Y"** contrast frame. | State it straight. |
| 4 | **No forced triads** (lists of three for rhythm). | One or two items is fine. Don't pad to three. |
| 5 | **No rigid transitions** (moreover, furthermore, additionally, in conclusion / además, asimismo, adicionalmente, en conclusión). | Let sentences connect naturally, or just start the next one. |
| 6 | **No filler openers** ("I hope this message finds you well", "in today's fast-paced world", "in the realm of", "it's worth noting that" / "espero que este mensaje te encuentre bien", "en el vertiginoso mundo actual", "en el ámbito de", "cabe destacar que"). | Open on the point. |
| 7 | **No uniform sentence length.** | Mix short, medium, long. Use fragments. Vary the rhythm. |
| 8 | **No bullets in informal/conversational prose** (chat reply, casual email, a description). | Write flowing sentences. (Exception below: structured technical output keeps its tables/code.) |
| 9 | **No repeated conclusions / summary tails** ("overall", "in summary", "to wrap up" / "en general", "en resumen", "para finalizar"). | End on the last real point. Stop. |
| 10 | **No voiceless perfect grammar.** | Use contractions, natural voice. Sound like a person. Keep the meaning, add no new ideas. |

### Read-aloud test (rule 10's enforcer)
Read the draft in your head. If a sentence sounds like a LinkedIn thought-leader wrote it, rewrite it.

## Per-language filler blocklist (rule 2)

| EN | ES | DE (extend as needed) |
|----|----|----|
| delve, tapestry, leverage, utilize, robust, seamless, multifaceted, navigate, optimize, foster, comprehensive | ahondar, tapiz, aprovechar, utilizar, robusto, fluido, multifacético, navegar, optimizar, fomentar, exhaustivo | (none yet) |

The list is a starting set, not exhaustive. The principle: if a word shows up far more in model output than in how a person actually talks, drop it.

## Reconciliation: this does NOT kill structured output

CLAUDE.md §Communication mandates "tables, bullets, code blocks; wall-of-text = failure." That still holds for **structured/technical deliverables** (specs, comparisons, runbooks, query results, step lists). Rule 8 governs **conversational prose**: chat replies, casual emails, narrative descriptions. The two coexist:

- Technical/structured answer → tables, code, numbered steps stay. Cadence rules 1–7, 9, 10 still apply *inside* the prose parts.
- Conversational/chat answer → prose, varied rhythm, contractions, no bullet-spam.

When unsure which mode you're in: is the user asking for data/structure, or talking with you? Structure for the first, cadence for the second.

The Provenance footer is a system requirement and is exempt (it's a machine receipt, not prose).

## Delivery format (operator-canonical, 2026-06-08)

Two hard rules layered on top of the 10, both operator-flagged after repeated misses:

1. **Paste-bound text ships as PLAIN TEXT.** Any chunk meant to be pasted somewhere else (LinkedIn post, email, caption, prompt, message) goes with zero markdown: no blockquote (`>`), no code fence, no bullets, no leading indent. The operator copies straight from the terminal, where a blockquote renders as `▎` plus indentation and arrives broken at the paste target. Commentary addressed TO the operator can stay normal prose; the instant a chunk is for pasting, strip its formatting. When unsure, treat it as paste-bound and keep it plain.
2. **Never open a paragraph or sentence in lowercase.** Capitalize the first letter, every time. The operator writes with normal capitalization, and a lowercase-start reads as an AI tell, worst of all when drafting in his voice.

## The source prompt (verbatim, for reuse as a humanizer)

The canonical "rewrite to sound human" prompt these rules were inverted from:

> Reescribe el siguiente texto para que suene como una persona real, no como una IA. Elimina lo siguiente:
> - Todos los guiones largos (em dash). Usa puntos, comas o saltos de línea.
> - Estas palabras: ahondar, tapiz, aprovechar, utilizar, robusto, fluido, multifacético, navegar, optimizar, fomentar, exhaustivo.
> - El formato de contraste "no solo X, es Y".
> - Listas forzadas de tres elementos. Dos elementos están bien. Uno está bien.
> - Transiciones rígidas: además, asimismo, adicionalmente, en conclusión.
> - Abridores de relleno: "Espero que este mensaje te encuentre bien", "en el vertiginoso mundo actual", "en el ámbito de", "cabe destacar que".
> - Oraciones de la misma longitud. Mezcla frases cortas, medianas y largas. Usa fragmentos.
> - Viñetas si es un correo electrónico informal o una descripción. Escribe en oraciones fluidas.
> - Repetición de conclusiones. Nada de "en general", "en resumen", "para finalizar".
> - Gramática perfecta sin voz. Usa contracciones. Suena como una persona.
> Mantén el significado original. No añadas ideas nuevas. Léelo en voz alta en tu cabeza. Si una frase suena como si la hubiera escrito un líder de opinión de LinkedIn, reescríbela.

Use this prompt directly when the operator hands you AI text and says "humanize this".

## Enforcement (reflex, not discipline — added 2026-06-04)

The rules shipped as instruction only and violations kept reaching delivered texts: instructions depend on discipline and never reach sub-agents or arm content pipelines at all. `scripts/cadence-lint.py` turns the regex-provable subset (rules 1, 2, 3, 5, 6, 9) into a mechanical check:

- **Hook mode** (`--hook`, PostToolUse `Write|Edit`): lints the newly written content of prose files (`.md`/`.txt`) and injects the violation list back into context, so the agent corrects before shipping. Never blocks; fail-open.
- **CLI mode** (`--file <path>` or stdin): exit 1 on violations — usable in any arm's CI or before publishing generated copy. Arms whose texts come from production LLM pipelines (not from a Claude session) should ALSO embed the verbatim humanizer prompt below in their generation prompt; the linter is the net under that wire.
- **Chat mode** (`scripts/cadence-stop-hook.py`, Stop hook, added 2026-06-04 after the operator caught tells in drafted comments/messages twice): lints the assistant's FINAL reply text (code fences, inline code and the Provenance footer stripped) and emits `decision: block` once so the reply is rewritten before delivery. One-shot by protocol (`stop_hook_active` escape): one forced rewrite per turn, never a loop. This closes the last uncovered surface — the operator's directive is 100% of outputs, chat included.

Rules 4/7/8/10 (triads, rhythm, bullets-in-prose, voice) stay with the model: regex can't prove them. Canon files quoting the blocklists (this skill, CLAUDE.md, `cadence-*` files) are excluded, and a line containing `cadence-ok` is skipped. One deliberate canon/linter divergence: the ES `navegar` family is NOT linted (navegador/navegación are everyday technical Spanish; flagging them would bury real hits) — the word stays on the writing blocklist above, the regex just doesn't police it.

## Related

- `token-efficient-prompting`: the same edit from the cost angle (filler = tokens).
- `voice-and-cadence-consistency`: keeps voice uniform across a long *technical* doc; different concept (consistency, not de-AI-ing).
- CLAUDE.md §Communication: the always-on summary that points here.
- 4D Disclose: these rules fire at the delivery boundary, every output.

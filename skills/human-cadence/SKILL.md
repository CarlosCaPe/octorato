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

## Related

- `token-efficient-prompting`: the same edit from the cost angle (filler = tokens).
- `voice-and-cadence-consistency`: keeps voice uniform across a long *technical* doc; different concept (consistency, not de-AI-ing).
- CLAUDE.md §Communication: the always-on summary that points here.
- 4D Disclose: these rules fire at the delivery boundary, every output.

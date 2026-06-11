---
name: client-doc-lint
description: Pre-send QA reflex for GENERATED client deliverables (cotización, propuesta, contrato PDF/DOCX). Lints the rendered artifact for stripped accents, em-dash, already-past forward dates (kickoff/vigencia), and inventories every $ amount for human eyeballing. Run it before declaring any client doc "listo para enviar". Complements cadence-lint.py (which lints prose SOURCE, not the rendered output).
metadata:
  type: reference
---

# client-doc-lint · el doc no se manda sin pasar el lint

**Por qué existe.** En una sesión se generó una propuesta completa en español para
un cliente **sin un solo acento** y con una **fecha de kickoff ya vencida**, y ambos
errores cruzaron dos rondas de regeneración hasta que un render visual manual los
cachó. Un instrucción ("cuida los acentos") depende de disciplina y nunca llega al
doc-gen de un sub-agente. Esto vuelve reflejo lo que un regex sí puede probar.

`cadence-lint.py` cubre la **prosa fuente**. `client-doc-lint.py` cubre el
**artefacto generado** (el PDF/DOCX que se envía).

## Uso
```bash
python3 ~/.claude/scripts/client-doc-lint.py <archivo.pdf|.txt|.md>     # exit 1 si algo FALLA
python3 ~/.claude/scripts/client-doc-lint.py <archivo.pdf> --today 2026-06-09   # fijar "hoy"
cat doc.txt | python3 ~/.claude/scripts/client-doc-lint.py
```
Requiere `pdftotext` (poppler-utils) para PDF.

## Qué revisa
1. **accents**: doc largo en español con ratio de acentos casi cero = acentos perdidos, FAIL. (Español sano ronda 3-6%; bandera por debajo de 0.5% en docs > 800 letras.)
2. **em-dash**: cualquier guion largo (em-dash) en el texto renderizado (human-cadence regla 1), FAIL.
3. **stale-dates**: una línea con intención futura (kickoff / agendar / semana del / antes del) cuya fecha ya pasó respecto a `--today`, FAIL. Ignora líneas de referencia (FIX/DOF/emisión) que legítimamente citan fechas pasadas.
4. **figures**: inventario informativo de todos los montos `$` para que un humano verifique consistencia entre secciones (sin veredicto automático).

## Cuándo (reflejo)
Antes de decir "listo para enviar" sobre CUALQUIER entregable de cliente generado
por código o por sub-agente. Si el lint marca FAIL, se corrige y se reemite ANTES
de mandar. Para entregables visuales, el lint NO sustituye el render + Read propio
(tablas cortadas, layout): es la primera barrera barata, no la única.

Relacionado: [[cadence-lint]] (prosa fuente), [[human-cadence]] (las 10 no-reglas),
[[cotizacion-legal-baseline]] (clausulado base), [[reflexes-over-discipline]].

---
name: tramite-mx-assistant
description: Asistente de trámites gubernamentales/burocráticos guiado por agente. Reúne la identidad del operador desde los conectores (Gmail/WhatsApp/Drive/archivos locales), maneja un portal oficial con agent-browser (o Skyvern para formularios WRITE pesados), se DETIENE en los muros que por diseño son humanos (reCAPTCHA/Turnstile, OTP, pago con tarjeta, biométricos de primera vez), entrega al humano solo eso, y recoge el resultado (PDF) del correo. Úsalo para constancias de antecedentes penales, actas, apostillas, citas consulares, visados, SAT/IMSS y trámites análogos. NO intenta vencer captchas ni automatizar pagos.
---

# Trámite MX Assistant (asistente de trámites guiado)

Patrón destilado de una corrida real (constancia de antecedentes penales federales para un visado de España). La meta NO es automatizar el 100%; es que el agente haga el 90% (reunir datos, llenar campos, recoger el PDF) y el humano solo toque lo irreducible.

## Regla de oro (antes de construir nada)
¿Ya existe en open source? Si sí y es gratis/OSS, **se adopta y se mejora**, no se reinventa. Para WRITE-tasks de formularios de gobierno el adoptado es **Skyvern** (`github.com/skyvern-ai/skyvern`, AGPL-3.0, self-host Docker, MCP-ready, "mejor en tareas WRITE: llenar forms, login, descargar"). agent-browser es el motor ligero por defecto; Skyvern es el upgrade para portales complejos o repetitivos.

## Flujo (4D)
1. **Censo de conectores (Delegate Q2).** `claude mcp list` + revisar Gmail/WhatsApp/Drive/archivos locales. Los datos de identidad (CURP, datos del acta, ID) casi siempre YA existen en el correo o en disco. No los pidas si puedes leerlos. Caso real: la CURP venía en un correo previo; el acta en PDF ya estaba en el repo.
2. **Reúne los insumos.** Acta/ID en PDF legible <2MB (requisito típico gob.mx). Extrae datos con `pdftotext`/visión, nunca los inventes.
3. **Maneja el portal.** agent-browser: `open` → `snapshot -i` → actúa sobre `@eN` → re-snapshot. Si el botón abre un modal Bootstrap (`data-toggle="modal"`), dispáralo por JS si el ref no aparece. Llena todo lo que NO sea secreto.
4. **DETENTE en los muros humanos (no negociable):**
   - **reCAPTCHA / Cloudflare Turnstile / captcha de imagen** → SIEMPRE humano. No se brinca, ni con Skyvern. (Mismo patrón que CF Dashboard Turnstile.)
   - **OTP / 2FA / login con contraseña** (Llave MX, gob.mx) → el humano teclea; el agente nunca captura ni guarda la credencial.
   - **Pago con tarjeta** (BBVA, línea de captura) → humano.
   - **Biométricos de primera vez** (ej. carta no antecedentes Jalisco estatal: 1ª vez presencial) → humano.
5. **Recoge el resultado.** El PDF suele llegar por correo (link válido N días). Búscalo con el Gmail MCP y descárgalo a la carpeta del trámite.
6. **Encadena el siguiente paso.** Muchos trámites tienen un paso 2 (ej. apostilla en línea del documento federal en `apostillaylegalizacionmexico.segob.gob.mx`). Déjalo agendado/listo.

## Avisar al humano cuando se necesita su mano
Cuando el flujo topa un muro humano y el operador no está, AVÍSALE. Hoy: el Gmail MCP **sí** envía correo → usa eso. El WhatsApp MCP conectado suele ser **solo lectura** (sin `send_message`); para WhatsApp saliente hay que habilitar el bridge (`lharies/whatsapp-mcp`). Disclose el gap con 💡 Unlock-suggestion.

## Anti-patrones
- Pedirle al operador un dato que ya está en su correo/disco (haz el censo primero).
- Intentar resolver un captcha (pérdida de tiempo + frágil + contra el diseño del sitio).
- Capturar/loggear contraseñas o datos de tarjeta.
- Apostillar/sacar con mucha anticipación documentos de vida corta (médico <3 meses, penales): hazlo cerca de la cita.

## Provenance
Cita cada requisito con su fuente oficial; los blogs/gestores valen como contexto pero si chocan con la fuente oficial, gana la oficial y el blog se marca "a verificar". Relacionado: agent-browser, harmonization-over-accretion, reflexes-over-discipline.

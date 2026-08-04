---
name: wa-guardia
description: Modo guardia sobre un chat de mensajeria. Arma un watcher cuando un turno cierra esperando respuesta de un tercero, y lee lo pendiente al retomar el trabajo de un arm. Usar cuando se mande un mensaje que espera contestacion, cuando el operador pida leer un chat, o al empezar a trabajar con un arm que tiene canal de chat vivo.
---

# Guardia de chat

Esperar una respuesta y acordarse de ir a verla son dos cosas distintas. La
segunda es disciplina, y la disciplina se salta bajo carga: el mensaje llega,
nadie lo mira, y el operador se entera horas despues. La guardia convierte esa
espera en un reflejo con condicion de disparo escrita.

## Quien es el dueño de que (leelo antes de tocar nada)

**`wa-sin-respuesta.py` es el dueño de la vigilancia durable.** Corre como timer
de systemd, fuera de cualquier sesion, y alerta por correo cuando un mensaje de
cliente pasa el umbral sin respuesta. Si un canal importa de verdad, va en la
seccion `vigilancia` de `company/config/wa-puentes.json`. Una sesion no es
infraestructura: se cierra, y con ella se apaga cualquier vigilancia colgada de
ella.

**Este skill es la capa de sesion**, y contesta otra pregunta: *ponme al dia
ahora*. Sin umbral, sin alerta, sin sobrevivir al cierre. No sustituye al vigia
y no debe convertirse en un segundo hogar del mismo concepto.

| | Vigia (`wa-sin-respuesta.py`) | Guardia de sesion (`wa-guardia.py`) |
|---|---|---|
| Pregunta | ¿se quedo alguien sin respuesta? | ¿que me deben contestar ahora? |
| Vive en | timer de systemd | la sesion viva |
| Avisa por | correo, al pasar el umbral | linea en el chat, al instante |
| Sobrevive al cierre | si | no |

**La logica compartida se importa, no se copia.** El filtro de acuses (que un
"gracias" no es un pendiente) y la ruta de los puentes viven en el vigia y en su
config; `wa-guardia.py` los importa. Dos copias de esa regla se separan con el
primer ajuste, y entonces los dos mecanismos empiezan a contradecirse.

## Cuando se arma (condicion, no capricho)

**Se arma cuando el turno cierra con algo pendiente de un tercero.** Esa es toda
la regla. Casos tipicos: mande un mensaje que pide respuesta, mande un correo que
espera acuse, deje una pregunta abierta en un grupo, subi algo que alguien tiene
que revisar.

Y el primer movimiento no es el Monitor, es preguntar **si ese chat ya tiene
vigilancia durable**. Si no la tiene, el arreglo de fondo es agregarlo a la
config del vigia; el Monitor solo cubre el rato de la sesion. Poner un parche de
sesion sobre un canal que deberia estar vigilado siempre es tratar el sintoma.
`wa-guardia.py` lo dice en cada corrida, en la linea `vigilancia durable:`.

**No se arma** cuando no hay espera. Un watcher permanente sin nada que esperar
es ruido que cuesta tokens y entrena al operador a ignorar las notificaciones,
que es peor que no tenerlas. La directiva del operador, 2026-08-04: *"al menos
cuando esperemos algo, si no pues no"*.

Antes de cerrar un turno, la pregunta es una: **¿queda alguien a quien le toca
contestar?** Si si, se arma antes de responder. Si no, no.

## Cuando se lee (sin que lo pidan)

Al **empezar a trabajar con un arm** que tiene canal de chat vivo, y siempre que
el operador pida leer el chat, lo primero es el reporte de pendientes. Entrar a
trabajar sin saber que llego mientras tanto es arrancar a ciegas, y el riesgo
concreto es contestar algo que ya se resolvio o pedir algo que ya mandaron.

## Mecanismo

`~/.claude/scripts/wa-guardia.py` lee la base del puente en modo **solo lectura**.
Nunca escribe ni manda.

    # que me deben contestar (lo entrante despues de MI ultimo envio)
    python3 ~/.claude/scripts/wa-guardia.py <chat_jid> [--puente soporte|personal]

    # ventana fija, para auditar hacia atras
    python3 ~/.claude/scripts/wa-guardia.py <chat_jid> --horas 24

    # vigilancia continua: una linea por mensaje nuevo, no termina
    python3 ~/.claude/scripts/wa-guardia.py <chat_jid> --vigilar --intervalo 60

El modo por omision corta **desde mi ultimo envio**, no desde una ventana de
horas fijada a mano. Una ventana siempre queda corta (se pierde lo de anteayer) o
larga (repite lo ya contestado); "desde que hable yo" es la unica linea que
responde de verdad a "que me deben".

Para vigilar, colgarlo de un `Monitor` con `persistent: true`. Cada mensaje nuevo
llega como notificacion sin tener que sondear.

## Reglas de uso

1. **Valida contra un caso conocido antes de confiar en el silencio.** "Sin
   mensajes nuevos" y "la consulta esta rota" se ven igual. Corre el modo
   `--horas` sobre un periodo donde SI hubo mensajes: si los trae, el silencio es
   real. Sin ese control positivo no se reporta "no hay nada".
2. **El JID del chat vive en la memoria del arm, no aqui.** Este skill es
   generico; que grupo vigilar es dato del cliente.
3. **Elige el puente correcto.** Un chat de cliente vive en el puente de soporte;
   el personal es del operador. Ver `feedback_support_channel_not_personal`.
4. **La guardia avisa, no contesta.** Un mensaje entrante no se responde solo:
   se reporta al operador con quien escribio y que dijo. Contestar en automatico
   a un cliente no esta autorizado por existir un watcher.
5. **Bajala cuando llego lo que esperabas.** `TaskStop` sobre el monitor. Una
   guardia que sobrevive a su espera es la que enseña a ignorar avisos.

## Como sabe el hook que "mande algo"

`d__stop__wa-guardia.py` (Stop, regla `FLOW.wa-guardia-on-pending`) NO se fia de
`messages.is_from_me`. Esa columna solo dice "salio de esta cuenta", y eso
incluye lo que el operador escribe desde su telefono: pedir guardia por un
mensaje que el mando a mano es un falso positivo, y los falsos positivos enseñan
a ignorar el aviso, que es peor que no tenerlo.

La fuente es la tabla **`api_sends`**, que el puente escribe solo cuando el
envio paso por su API, o sea cuando lo mando el agente. Un puente sin esa tabla
no puede distinguir agente de humano y por diseño **no aporta candidatos**:
callar es correcto, inventar avisos desde `is_from_me` es el bug que esto
arregla. Hoy la tiene el puente de soporte; el personal no.

No cuentan como espera los latidos de salud (contenido `latido-...`).

## Que NO ve

Solo ve lo que el puente haya guardado. Un grupo sin mensajes no tiene renglon en
la tabla `chats` y es invisible, y los nombres de contacto no estan en la base:
la base guarda identificadores, no personas. Para saber quien es quien hay que
preguntar al grupo o mirar el telefono. Ver
`feedback_identifier_is_not_a_person`.

---
name: save-transcript
description: "Rescata el transcript COMPLETO de una grabacion de reunion (Microsoft Stream, SharePoint) a partir de su URL, y entrega un .txt limpio, con procedencia y listo para compartir. Dispara con 'save-transcript', 'baja el transcript', 'saca el transcript de esta junta', 'transcript de <URL>'. Para audio crudo sin transcript ya renderizado usa transcribe."
---

# save-transcript

El operador pasa un nombre y una URL de grabacion. La salida es un `.txt` con encabezado
de procedencia, cobertura declarada y advertencias de transcripcion, verificado sin huecos.

**No confundir con `transcribe`**, que corre reconocimiento de voz sobre audio. Aqui el
transcript YA EXISTE, lo genero la plataforma, y el trabajo es rescatarlo completo cuando
la UI de descarga lo niega.

## Entrada minima

```
save-transcript <slug o nombre de la junta> <URL de la grabacion>
```

De la URL solo importa el `id`. Todo lo demas (`referrer`, `referrerScenario`, tokens de
vista) es ruido de navegacion: dos URLs con distinto `referrer` y el mismo `id` son la
misma grabacion. Verificalo antes de recapturar algo que ya tienes.

## Regla de oro: cobertura declarada, no conteo de cues

El fallo silencioso de este trabajo es entregar un transcript truncado que se ve completo.
"417 cues" suena a mucho y puede cubrir 22 de 32 minutos.

**La unica evidencia valida** es leer `video.duration` del reproductor y comprobar que no
haya minutos sin cue en todo el rango. Un conteo de cues no es cobertura, y afirmar
completitud sin ese chequeo es exactamente la clase de error que el operador va a cazar.

## Flujo

### 1. Primera pasada, cosecha por scroll

Corre el harvester normal de la plataforma. En grabaciones cortas alcanza. En grabaciones
largas se detiene: el panel es una lista virtualizada que recicla celdas y regresa el
scroll al tope, tipicamente alrededor del 60 a 80 por ciento de la altura. Lo reconoces
porque el contador de cues se congela mientras el offset rebota entre posiciones anteriores.

### 2. Segunda pasada, rescate por seek

Cuando la primera se estanca, **maneja el video, no la lista**. Poner
`video.currentTime` hace que el panel auto-scrollee al playhead y renderice esa region:

```js
await frame.evaluate((s) => { document.querySelector('video').currentTime = s; }, minuto * 60);
await page.waitForTimeout(2600);            // deja que el panel siga al playhead y pinte
const rendered = await extraeCuesRenderizados(frame);
```

Lee `video.duration` primero y camina una escalera de paradas cada 2 minutos desde poco
antes del estancamiento hasta el final. Detente cuando una parada no aporte cues nuevos.

### 3. Fusion de pasadas

El mismo cue se renderiza en mas de una forma: bloque multilinea (hablante, luego
`MM minutes SS seconds`, luego `MM:SS`, luego encabezado repetido, luego texto), bloque
de solo encabezado sin texto, y forma aplanada de una linea con el tiempo inline. Parsea
las tres, indexa por `(timestamp, hablante)` y **conserva la variante de texto mas larga**,
porque algunos renderizados truncan. Indexar por el string crudo produce duplicados casi
identicos y aun asi pierde el texto completo.

### 4. Verificacion de cobertura

```python
have = {segundos // 60 for segundos, _, _ in rows}
gaps  = [m for m in range(0, int(duracion // 60) + 1) if m not in have]
```

`gaps` vacio es la evidencia. Si no lo esta, dilo en el encabezado en vez de callarlo.

### 5. Barrido de datos sensibles antes de entregar

Obligatorio cuando el destino es un canal, un correo o una pagina. Patrones minimos:
identificadores de 6 o mas digitos, formato de seguro social, fechas de nacimiento,
identificadores profesionales de 10 digitos, correos, telefonos, y nombre propio precedido
por palabras como paciente o miembro. Los ejemplos hipoteticos que la gente inventa en
juntas ("digamos que el doctor se llama X") no son datos reales; distinguelos leyendo el
contexto, no solo el patron.

Si algo aparece, no lo entregues: reportalo al operador y espera decision.

### 6. Formato de salida

Un `.txt`, saltos de linea CRLF para que los visores de Windows y las previsualizaciones
de chat lo rendericen bien, ancho de linea a 93 columnas con sangria de continuacion, y
nombre de archivo descriptivo que se lea solo en una lista de adjuntos.

El encabezado lleva cinco cosas, y ninguna es opcional:

```
<TITULO DE LA JUNTA>
Meeting transcript, <fecha>

Recording length      <mm:ss leido del reproductor>
Transcript coverage   <inicio> to <fin>, <n> cues, no gaps
Speakers              <en orden de volumen de intervencion>

HOW THIS WAS PRODUCED
<como se capturo, incluida la parte incomoda: que la UI de descarga lo niega
 y que la cola se recupero manejando el video>

<que nada se edito, resumio ni reordeno>

<los errores de transcripcion de la plataforma, con ejemplos reales del documento>

<que el artefacto autoritativo es el export nativo, y esto es copia de trabajo>
```

**La linea de errores de transcripcion es la que salva al lector.** Estas plataformas
destrozan nombres propios y siglas de forma consistente dentro de un mismo documento. Si
no lo adviertes, alguien va a creer que existe un cliente llamado como la sigla mal
transcrita. Extrae los ejemplos del documento real, no de una lista generica.

## Anti-patrones

| Anti-patron | Por que falla |
|---|---|
| Reportar cues como cobertura | Suena completo y no lo es. Solo el chequeo de minutos vacios contra la duracion real es evidencia. |
| Insistir con mas scroll | El reset vive dentro del control de la plataforma. Mas eventos de scroll no lo mueven. |
| Recapturar por un `referrer` distinto | Misma grabacion. Compara el `id`, no la URL completa. |
| Entregar sin barrido de datos sensibles | El transcript va a un canal. Una vez enviado no se recoge. |
| Omitir la advertencia de errores de transcripcion | El lector toma una sigla mal transcrita por un dato. |
| Presentarlo como el transcript oficial | Es texto rescatado del DOM. El oficial es el export nativo, y hay que decirlo. |
| Saltos de linea LF en un txt para Windows | Se ve como una sola linea gigante en el visor por defecto. |

## Cierre: el transcript no es el entregable

Un transcript entregado y nada mas obliga al humano a leer 20 minutos de texto para saber
si algo cambio. Cierra siempre diciendo **que se decidio y que contradice** lo que estaba
escrito antes, citando timestamp y hablante. Ese es el valor; el archivo es el respaldo.
Mismo principio que `capture-ends-with-triage`.

## Relacionado

`stream-transcript-dom-scrape` es el mecanismo de captura por plataforma, incluida la
tecnica de seek y sus recibos. `transcribe` es para audio sin transcript previo.
`capture-ends-with-triage` es la razon del cierre de arriba. `phi-aware-rag-ingestion`
recibe el texto cuando va a un indice.

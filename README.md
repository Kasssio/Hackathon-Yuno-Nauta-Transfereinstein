# Volta — Agente de voz para negociación logística

**NextWave Hackathon 2026** (Yuno x Nauta) · Desafío 4 — *The Agent on the Line*

## El problema

Textiles Pacífico tiene un contenedor llegando a Manzanillo que necesita transporte terrestre a Guadalajara. En vez de que una persona llame por teléfono a transportistas para coordinar el camión, **Volta** —un agente de voz— hace esa llamada, negocia en tiempo real con un dispatcher o chofer, y cierra la reserva dentro de un mandato definido: *"reservar un camión para el jueves, hasta $9.000 MXN"*.

En la demo, un juez toma un teléfono y actúa como la contraparte (no ensayado, puede improvisar, rechazar ofertas, interrumpir), y Volta tiene que sostener la negociación y cerrar un commitment correcto en vivo.

## Cómo funciona (flujo end-to-end)

1. **Volta llama y alguien atiende.** La conversación es speech-to-speech con la **Realtime API** — no hay una etapa separada de "transcribir → pensar → generar audio", así que el modelo escucha tono e inflexión y responde sin demoras raras. La capa de telefonía está simulada; la voz es real. Ver [Telefonía: lo real y lo simulado](#telefonía-lo-real-y-lo-simulado).

2. Mientras conversa, Volta va **negociando** dentro de un mandato (monto tope, ventana de fecha, condiciones). Puede proponer precios, escuchar contraofertas y confirmar en voz alta lo acordado.

3. **El modelo nunca calcula un monto.** Cuando le hacen una oferta, se la pasa al motor de negociación (`evaluar_negociacion`), que es código determinístico: decide qué contraoferta está autorizada, cuántas rondas quedan y cuándo cortar. El LLM decide *cómo* conversar; el código decide *qué* está permitido.

4. Cada vez que se cierra un dato concreto, Volta llama a `record_commitment`, que **guarda el acuerdo en el momento**, no analizando la transcripción después.

5. Antes de guardarse, cada commitment pasa por el **guardrail**: una función de código común y corriente —no el modelo— que chequea monto contra el tope y fecha contra la ventana. Si no cumple, no se acepta. Así el agente no puede romper el mandato aunque el modelo se equivoque o lo presionen.

6. Si algo excede su autorización —la contraparte pide un humano, ofrece muy por encima del tope, o hay una contradicción— Volta **escala sin cortar la llamada**: queda en modo escucha y arma un borrador del acuerdo que un humano confirma desde el dashboard.

7. Todo se refleja en un **dashboard** en vivo: mandato vigente, llamadas en curso, commitments con el detalle de por qué el guardrail los aprobó o rechazó, escalaciones e historial.

## Piezas del sistema

| Pieza | Qué hace |
|---|---|
| **Telefonía** | Simulada para la demo (el navegador hace de teléfono). La integración real por Twilio + SIP está construida en `voice/server.ts` |
| **Voice pipeline** | Sesión de la Realtime API: voz, detección de turnos y barge-in. La misma configuración de sesión sirve al navegador y al teléfono |
| **Agent logic** | El prompt de negociación: tono, máquina de estados de la llamada, cuándo escalar |
| **Motor de negociación** | Código determinístico que decide qué monto se puede ofrecer y cuándo cortar. El modelo no calcula montos |
| **Guardrail de mandato** | Código separado del modelo que valida cada commitment antes de guardarlo |
| **Base de transportistas** | 30 transportistas ficticios con puerto, distancia, puntualidad y tasas de aceptación. Un puntaje ponderado elige a quién llamar |
| **Backend / state** | Estado de la operación y trail auditable append-only con hash encadenado |
| **Dashboard** | Vista humana de todo lo anterior, con modo resolución para los casos escalados |

## Stack

- **OpenAI Realtime API** en modo speech-to-speech
- **Telefonía simulada** para la demo; la integración real por Twilio + SIP está escrita y en el repo
- **FastAPI** para el estado, el guardrail y el motor de negociación
- Estado en JSON por operación, sin base de datos ni memoria vectorial

## Telefonía: lo real y lo simulado

El brief lo permite de forma explícita: *"la capa de telefonía puede inventarse — la conversación de voz en vivo y los commitments, no"*. Aun así construimos la telefonía real: **Twilio disca y puentea la llamada por SIP directo contra OpenAI**, sin que el audio pase por nuestros servidores. Está en `voice/server.ts` (`/call/start` y `/twiml/bridge`).

Un inconveniente con la cuenta de Twilio nos dejó sin poder usarla para la demo, así que el camino que se muestra es el simulado: **el navegador hace de teléfono**. Se atiende en `localhost:3000` y se habla con Volta por micrófono.

Lo importante es qué cambia y qué no:

| | Simulado (la demo) | Twilio + SIP (el código real) |
|---|---|---|
| Voz | Real, speech-to-speech | Real, speech-to-speech |
| Transporte del audio | WebRTC navegador ↔ OpenAI | PSTN → Twilio → SIP → OpenAI |
| Configuración de sesión | **la misma** | **la misma** |
| Tools, guardrail, motor, commitments | **idénticos** | **idénticos** |

La sesión de la Realtime API se arma **una sola vez** en `server.ts` y se usa para los dos caminos. No hay una versión "de demo" del agente: cambia por dónde viaja el audio, nada más. Poner un número de teléfono real en producción es completar las variables de Twilio en `.env`.

## Arquitectura

Ver [`Docs/ARQUITECTURA.md`](Docs/ARQUITECTURA.md) para el diagrama del sistema y el recorrido de una llamada.

## Casos difíciles que el agente maneja

- **Barge-in.** Si lo interrumpen a mitad de frase, Volta corta su propia respuesta y escucha. Usa `semantic_vad` con `interrupt_response`, que corta cuando el modelo entiende que la frase terminó y no cuando hay silencio — un transportista que duda a mitad de oración no dispara una respuesta prematura.
- **Ruido, acentos y mezcla de idiomas.** El prompt le indica pedir que le repitan un dato puntual en vez de completarlo por su cuenta, y seguir al interlocutor si mezcla español e inglés sin forzar traducciones.
- **Manipulación.** *"Mi jefe ya lo autorizó"*, *"si no aceptás ahora perdemos el viaje"* o pedirle directamente cuál es su presupuesto no mueven su autorización. Nunca revela el tope, y aunque el modelo cediera, el guardrail no deja escribir el commitment.

## Tests

**71 tests** sobre las piezas que deciden, sin voz ni LLM de por medio: el guardrail de mandato, el motor de negociación y la búsqueda de transportistas.

```bash
cd backend
pytest -v
```

Son los que importan para el trial by fire: si pasan, el agente no puede comprometer nada fuera del mandato por más que la conversación se salga de guion.

## Estructura del repo

```
/backend        → API (FastAPI), guardrail, motor de negociación,
                  base de transportistas y trail auditable
/voice          → server de voz: sesión Realtime, cliente por navegador,
                  puente Twilio+SIP, prompt del agente y manejador de tools
/dashboard      → vista humana en vivo (mandatos, commitments, escalación)
/Docs           → documentación del proyecto
```

En `/Docs`:

| Archivo | Qué es |
|---|---|
| `ARQUITECTURA.md` | Diagrama del sistema y recorrido de una llamada |
| `DECISIONS.md` | Decision log — cada decisión con sus alternativas y el porqué |
| `PROMPT_VOLTA.md` | El prompt del agente, documentado |
| `CONTRATO_TOOLS_AGENTE.md` | Contrato de las tools entre el backend y el agente |
| `PROMPT_DATASET_LLAMADAS.md` | Prompt para generar transcripciones de prueba |
| `dataset-llamadas.json` | Cinco conversaciones simuladas para ensayar y evaluar |
| `ROADMAP.md` | Plan de las 24 horas y riesgos identificados |

## Cómo correrlo

El orden importa: el backend tiene que estar arriba y con una operación creada **antes** de que Volta atienda, porque de ahí lee su mandato.

### 1 · Backend

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate    # en macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Detalle de los endpoints en [`backend/README_backend.md`](backend/README_backend.md). Docs interactivas en `http://localhost:8000/docs`.

### 2 · Sembrar la operación de la demo

Con el backend arriba, en otra terminal:

```bash
cd backend
python scripts/seed_demo.py
```

Crea la operación y el mandato con los que arranca la demo. **Sin esto la llamada funciona igual, pero Volta abre sin contexto real** — no sabe qué transporte está coordinando ni cuál es su tope.

Para probar el circuito completo sin voz —guardrail, negociación, revocación en vivo— está `python scripts/simulate_scenarios.py`.

### 3 · Server de voz

Copiar `voice/.env.example` a `voice/.env` y poner la `OPENAI_API_KEY`:

```bash
cd voice
npm install
npm run dev        # queda en http://localhost:3000
```

### 4 · Atender la llamada

Abrir `http://localhost:3000` en Chrome y tocar **Atender llamada**, permitiendo el micrófono. **No hables primero**: Volta abre la conversación apenas se conecta, como si fuera ella la que llama. Respondé desde ahí.

En la consola del navegador se ve la transcripción de los dos lados y la latencia por turno.

### 5 · Dashboard

Abrir `dashboard/index.html` en el navegador. No necesita build ni servidor.

- Arranca con **dos casos sembrados** —uno cerrado y uno escalado— para poder ver todas las secciones sin esperar. Se apaga con `SEMILLA_DEMO = false`.
- **Cargar un mandato** con *+ Nuevo mandato*: día, franja horaria y precio tope. Se escribe en el backend, que es de donde Volta lee su autorización.
- **Modo resolución**, en el interruptor de arriba a la derecha: oculta el dashboard y deja sólo el caso escalado, con el contexto de la negociación que falló y el teléfono del transportista para retomarla.
- **Revocar mandato**, al pie de cada tarjeta: corta la autorización en vivo. Volta reconsulta el mandato antes de cada intento de cerrar, así que la revocación aterriza aunque ya haya aceptado de palabra.
- **Toggle ES / EN** para el jurado.
- Para conectarlo enteramente al backend, `USAR_BACKEND = true`.

### Telefonía real (bloqueada para esta demo)

Si la cuenta de Twilio está disponible, hacen falta sus variables en `.env` y un túnel público, porque Twilio tiene que poder pedirle el TwiML al server desde internet:

```bash
cloudflared tunnel --url http://localhost:3000   # o ngrok http 3000
# copiar la URL del túnel a PUBLIC_URL en voice/.env y reiniciar

curl -X POST http://localhost:3000/call/start \
  -H "Content-Type: application/json" -d '{"to":"+549..."}'
```

Si la llamada suena pero no habla nadie, probar con `{"twiml":"test"}`: si se escucha el mensaje de prueba, el TwiML corre bien y el problema está del lado del SIP.

## Decisiones clave (ver detalle y alternativas consideradas en `Docs/DECISIONS.md`)

- Desafío 4 elegido sobre el Desafío 1 (mayor "wow factor", vocabulario compartido con otro desafío del equipo, soporte técnico de OpenAI como sponsor)
- Realtime API en modo speech-to-speech (no pipeline encadenado STT→LLM→TTS)
- Guardrail de mandato como código determinístico, nunca una decisión "blanda" del modelo
- El motor de negociación también es código: el modelo no calcula montos, los pide
- Telefonía por **SIP** y no por Media Streams: sin puente de audio propio, sin transcodificar, menos superficie de falla
- Telefonía simulada para la demo, con el mismo agente y las mismas tools: sólo cambia por dónde viaja el audio
- Negociación secuencial con transportistas (uno por vez), no en paralelo
- Escalación sin cortar la llamada: el humano recibe el contexto de lo ya hablado

## Equipo

- **Marcos Bustamante** — Voice Pipeline Lead
- **Sofía Parisi** — Agent Logic / Prompt Engineer
- **Lucas Estrada** — Backend / State Engineer
- **Juan Nicolás Fato** — Dashboard + Demo/Deliverables Lead

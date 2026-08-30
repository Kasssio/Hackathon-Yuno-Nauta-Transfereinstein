# Volta — Agente de voz para negociación logística

**NextWave Hackathon 2026** (Yuno x Nauta) · Desafío 4 — *The Agent on the Line*

## El problema

Textiles Pacífico tiene un contenedor llegando a Manzanillo que necesita transporte terrestre a Guadalajara. En vez de que una persona llame por teléfono a transportistas para coordinar el camión, **Volta** —un agente de voz— hace esa llamada, negocia en tiempo real con un dispatcher o chofer, y cierra la reserva dentro de un mandato definido: *"reservar un camión para el jueves, hasta $9.000 MXN"*.

En la demo, un juez toma un teléfono y actúa como la contraparte (no ensayado, puede improvisar, rechazar ofertas, interrumpir), y Volta tiene que sostener la negociación y cerrar un commitment correcto en vivo.

## Cómo funciona (flujo end-to-end)

1. **Volta llama por teléfono de verdad.** Twilio disca el número y puentea la llamada **directo** al endpoint SIP de OpenAI: el audio nunca pasa por nuestros servidores. Del otro lado suena un teléfono común. La conversación es speech-to-speech con la **Realtime API** — no hay una etapa separada de "transcribir → pensar → generar audio", así que el modelo escucha tono e inflexión y responde sin demoras raras.

2. Mientras conversa, Volta va **negociando** dentro de un mandato (monto tope, ventana de fecha, condiciones). Puede proponer precios, escuchar contraofertas y confirmar en voz alta lo acordado.

3. **El modelo nunca calcula un monto.** Cuando le hacen una oferta, se la pasa al motor de negociación (`evaluar_negociacion`), que es código determinístico: decide qué contraoferta está autorizada, cuántas rondas quedan y cuándo cortar. El LLM decide *cómo* conversar; el código decide *qué* está permitido.

4. Cada vez que se cierra un dato concreto, Volta llama a `record_commitment`, que **guarda el acuerdo en el momento**, no analizando la transcripción después.

5. Antes de guardarse, cada commitment pasa por el **guardrail**: una función de código común y corriente —no el modelo— que chequea monto contra el tope y fecha contra la ventana. Si no cumple, no se acepta. Así el agente no puede romper el mandato aunque el modelo se equivoque o lo presionen.

6. Si algo excede su autorización —la contraparte pide un humano, ofrece muy por encima del tope, o hay una contradicción— Volta **escala sin cortar la llamada**: queda en modo escucha y arma un borrador del acuerdo que un humano confirma desde el dashboard.

7. Todo se refleja en un **dashboard** en vivo: mandato vigente, llamadas en curso, commitments con el detalle de por qué el guardrail los aprobó o rechazó, escalaciones e historial.

## Piezas del sistema

| Pieza | Qué hace |
|---|---|
| **Telefonía** | Twilio disca y puentea por SIP contra OpenAI. El audio no toca nuestra infraestructura |
| **Voice pipeline** | Sesión de la Realtime API: voz, detección de turnos y barge-in. Un WebSocket de control transporta transcripciones y tool calls, no audio |
| **Agent logic** | El prompt de negociación: tono, máquina de estados de la llamada, cuándo escalar |
| **Motor de negociación** | Código determinístico que decide qué monto se puede ofrecer y cuándo cortar. El modelo no calcula montos |
| **Guardrail de mandato** | Código separado del modelo que valida cada commitment antes de guardarlo |
| **Base de transportistas** | 30 transportistas ficticios con puerto, distancia, puntualidad y tasas de aceptación. Un puntaje ponderado elige a quién llamar |
| **Backend / state** | Estado de la operación y trail auditable append-only con hash encadenado |
| **Dashboard** | Vista humana de todo lo anterior, con modo resolución para los casos escalados |

## Stack

- **OpenAI Realtime API** en modo speech-to-speech
- **Twilio + SIP** para llamadas telefónicas reales — el audio va directo a OpenAI, sin puente propio
- **FastAPI** para el estado, el guardrail y el motor de negociación
- Estado en JSON por operación, sin base de datos ni memoria vectorial

## Arquitectura

Ver [`Docs/ARQUITECTURA.md`](Docs/ARQUITECTURA.md) para el diagrama del sistema y el recorrido de una llamada.

## Estructura del repo

```
/backend        → API (FastAPI), guardrail, motor de negociación,
                  base de transportistas y trail auditable
/voice          → server de voz: llamada por Twilio+SIP, sesión Realtime,
                  prompt del agente y manejador de tools
/dashboard      → vista humana en vivo (mandatos, commitments, escalación)
/Docs           → arquitectura, decision log, roadmap y contrato de tools
```

## Cómo correrlo

**Backend** (API + guardrail) — ver `backend/README.md` para el detalle:

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate    # en macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Voz** — copiar `voice/.env.example` a `voice/.env` y completarlo:

```bash
cd voice
npm install
npm run dev        # queda en http://localhost:3000
```

Con sólo `OPENAI_API_KEY` ya funciona la demo por navegador (WebRTC, laptop-a-laptop).

**Llamadas telefónicas** — hacen falta además las variables de Twilio y un túnel público, porque Twilio tiene que poder pedirle el TwiML a este server desde internet:

```bash
cloudflared tunnel --url http://localhost:3000   # o ngrok http 3000
# copiar la URL del túnel a PUBLIC_URL en voice/.env y reiniciar

curl -X POST http://localhost:3000/call/start \
  -H "Content-Type: application/json" -d '{"to":"+549..."}'
```

Si la llamada suena pero no habla nadie, probar con `{"twiml":"test"}`: si se escucha el mensaje de prueba, el TwiML corre bien y el problema está del lado del SIP.

**Dashboard** — abrir `dashboard/index.html` en el navegador. No necesita build ni servidor. Arranca con datos simulados; para conectarlo al backend, poner `USAR_BACKEND = true` en el archivo.

## Decisiones clave (ver detalle y alternativas consideradas en `Docs/DECISIONS.md`)

- Desafío 4 elegido sobre el Desafío 1 (mayor "wow factor", vocabulario compartido con otro desafío del equipo, soporte técnico de OpenAI como sponsor)
- Realtime API en modo speech-to-speech (no pipeline encadenado STT→LLM→TTS)
- Guardrail de mandato como código determinístico, nunca una decisión "blanda" del modelo
- El motor de negociación también es código: el modelo no calcula montos, los pide
- Telefonía real por **SIP** y no por Media Streams: sin puente de audio propio, sin transcodificar, menos superficie de falla
- Negociación secuencial con transportistas (uno por vez), no en paralelo
- Escalación sin cortar la llamada: el humano recibe el contexto de lo ya hablado

## Equipo

- **Marcos Bustamante** — Voice Pipeline Lead
- **Sofía Parisi** — Agent Logic / Prompt Engineer
- **Lucas Estrada** — Backend / State Engineer
- **Juan Nicolás Fato** — Dashboard + Demo/Deliverables Lead

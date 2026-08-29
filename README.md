# Volta — Agente de voz para negociación logística

**NextWave Hackathon 2026** (Yuno x Nauta) · Desafío 4 — *The Agent on the Line*

## El problema

Textiles Pacífico tiene un contenedor llegando a Manzanillo que necesita transporte terrestre a Guadalajara. En vez de que una persona llame por teléfono a transportistas para coordinar el camión, **Volta** —un agente de voz— hace esa llamada, negocia en tiempo real con un dispatcher o chofer, y cierra la reserva dentro de un mandato definido: *"reservar un camión para el jueves, hasta $9.000 MXN"*.

En la demo, un juez toma un teléfono y actúa como la contraparte (no ensayado, puede improvisar, rechazar ofertas, interrumpir), y Volta tiene que sostener la negociación y cerrar un commitment correcto en vivo.

## Cómo funciona (flujo end-to-end)

1. **Volta llama** (o recibe una llamada) y habla con la contraparte usando voz real de punta a punta — no hay una etapa separada de "transcribir → pensar → generar audio": todo pasa por la **Realtime API de OpenAI** en modo speech-to-speech, para que suene natural y sin demoras raras al hablar.

2. Mientras conversa, Volta va **negociando** según un mandato (monto tope, ventana de fecha) que tiene cargado de antemano. Puede proponer precios, escuchar contraofertas, y confirmar en voz alta lo que se va acordando ("entonces $8.500 para el jueves, ¿confirmado?").

3. Cada vez que se cierra un dato concreto (precio, fecha, transportista), Volta llama a una función (`record_commitment`) que **guarda ese acuerdo** en el sistema en el momento, no después analizando la transcripción completa.

4. Antes de que ese commitment quede guardado como válido, pasa por un **guardrail**: una función de código común y corriente (no el modelo de IA) que chequea si el monto está dentro del tope y la fecha dentro de la ventana permitida. Si no cumple, el commitment no se acepta — así el agente no puede "romper" el mandato aunque el modelo se equivoque o lo presionen.

5. Si pasa algo que Volta no puede resolver solo — la contraparte pide hablar con un humano, ofrece muy por encima del tope, rechaza todo repetidamente, o hay una contradicción — el sistema **escala** y deriva la llamada a una persona.

6. Todo esto se ve reflejado en un **dashboard**: el mandato vigente, el estado de la llamada en curso, los commitments cerrados (confirmados, pendientes o rechazados) y el historial de llamadas anteriores — esto último permite que si hay que renegociar (ej. el chofer avisa que se demora), Volta recuerde lo ya acordado.

## Piezas del sistema

| Pieza | Qué hace |
|---|---|
| **Voice pipeline** | Maneja el audio en vivo: habla, escucha, detecta cuándo lo interrumpen (barge-in) y corta su propia respuesta si hace falta |
| **Agent logic** | El "cerebro" que negocia: decide qué decir, cuándo ceder, cuándo escalar |
| **Guardrail de mandato** | Código separado del modelo que valida cada commitment antes de que se guarde |
| **Backend / state** | Guarda el estado de la operación (mandato, commitments, historial) en un JSON simple |
| **Dashboard** | Vista humana de todo lo anterior, en tiempo real |

## Stack

- **OpenAI Realtime API** (modo speech-to-speech)
- Telefonía **simulada** (laptop-a-laptop o laptop-a-teléfono) — la voz es real, la capa de "llamada telefónica" no
- Estado simple tipo JSON por operación (sin base de datos ni memoria vectorial)

## Estructura del repo

```
/backend        → modelo de datos, guardrail, trail auditable y API (FastAPI)
/voice          → cliente de voz: Realtime API sobre WebRTC y config de sesión
/dashboard      → vista humana en vivo (mandato, commitments, escalación)
/Docs           → diagrama de arquitectura, decision log y roadmap
```

## Cómo correrlo

**Backend** (API + guardrail) — ver `backend/README.md` para el detalle:

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate    # en macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Voz** — copiar `voice/.env.example` a `voice/.env` y poner ahí la `OPENAI_API_KEY`:

```bash
cd voice
npm install
npm run dev        # queda en http://localhost:3000
```

**Dashboard** — abrir `dashboard/index.html` en el navegador. Arranca con datos simulados; para conectarlo al backend, poner `USAR_BACKEND = true` en el archivo.

## Decisiones clave (ver detalle y alternativas consideradas en `Docs/DECISIONS.md`)

- Desafío 4 elegido sobre el Desafío 1 (mayor "wow factor", vocabulario compartido con otro desafío del equipo, soporte técnico de OpenAI como sponsor)
- Realtime API en modo speech-to-speech (no pipeline encadenado STT→LLM→TTS)
- Guardrail de mandato como código determinístico, nunca una decisión "blanda" del modelo
- Telefonía mockeada, no integración real con Twilio
- Negociación secuencial con transportistas (uno por vez), no en paralelo

## Equipo

- **Marcos Bustamante** — Voice Pipeline Lead
- **Sofía Parisi** — Agent Logic / Prompt Engineer
- **Lucas Estrada** — Backend / State Engineer
- **Juan Nicolás Fato** — Dashboard + Demo/Deliverables Lead

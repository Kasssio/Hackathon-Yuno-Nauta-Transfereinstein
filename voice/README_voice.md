# Voice pipeline — spike Realtime API

Cliente de voz speech-to-speech contra `gpt-realtime-2.1` por WebRTC.
El token efímero se acuña en el server; la API key nunca llega al browser.

## Correrlo

Necesitás Node 18+ (`node -v` para verificar).

```bash
cd voice
npm install
```

Creá el archivo `.env` con tu API key de OpenAI (pedila en el canal del
equipo, o generá una propia en platform.openai.com):

```
OPENAI_API_KEY=sk-proj-...
```

En PowerShell, para que no te quede un BOM invisible que rompe el parseo:

```powershell
Set-Content -Path .env -Value "OPENAI_API_KEY=sk-proj-TU_KEY" -Encoding ascii
```

Después:

```bash
npm run dev
```

Antes de conectar, corré `python backend/scripts/seed_demo.py` (con el
backend levantado) para que exista una operación — si no, la llamada
arranca igual pero sin el saludo con contexto real.

Abrí `http://localhost:3000` en Chrome, apretá F12 (consola), "Atender
llamada", permitir micrófono. **No hables primero**: la llamada está
armada como si Volta nos estuviera llamando a nosotros — habla ella
apenas se conecta, preguntando disponibilidad. Respondé desde ahí y
arranca la negociación. En consola vas a ver la transcripción de ambos
lados y `[latency] turno N: XXXms`.

## Si algo falla en Windows

- **`npm` no se reconoce** → Node no está en el PATH. Si lo acabás de
  instalar, cerrá VSCode **entero** y reabrilo (una terminal nueva no
  alcanza: VSCode cachea el PATH de cuando arrancó).
- **`npm.ps1 ... la ejecución de scripts está deshabilitada`** →
  `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`
- **401 al conectar** → la key está mal pegada, o creada en la org
  equivocada (los créditos del hackathon están en una org específica).

## Puntos de integración

Los dos están en `public/client.js`, marcados con comentario:

- **`onToolCall(name, args)`** — ya tiene las 7 tools contra el backend:
  `find_carriers`, `check_mandato`, `request_quote`, `cancel_commitment`,
  `record_commitment`, `escalate_to_human` y `get_time`. Las tools se
  declaran en `session-config.ts`.
- **`saludarInicial()`** — se dispara sola cuando el canal de datos abre
  (evento `dc.open`), para que Volta hable primero como si nos estuviera
  llamando ella. Si necesitás volver al modo "hablo yo primero", basta con
  no llamarla ahí.
- **`onTranscript(role, text)`** — vacía, para engancharla al dashboard.

`session-config.ts` (instructions, voice, tools) está pensado para
editarse sin tocar el resto.

## Ojo con el costo

El audio se cobra por token: del orden de USD 0,10 por minuto de
conversación. Colgá con el botón cuando no estés probando — la sesión
sigue facturando mientras está abierta aunque nadie hable.

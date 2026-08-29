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

Abrí `http://localhost:3000` en Chrome, apretá F12 (consola), Conectar,
permitir micrófono, y hablá. En consola vas a ver la transcripción de
ambos lados y `[latency] turno N: XXXms`.

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

- **`onToolCall(name, args)`** — acá va el guardrail y `record_commitment`
  contra el backend. Hoy sólo tiene `get_time()` de prueba. Las tools se
  declaran en `session-config.ts`.
- **`onTranscript(role, text)`** — vacía, para engancharla al dashboard.

`session-config.ts` (instructions, voice, tools) está pensado para
editarse sin tocar el resto.

## Ojo con el costo

El audio se cobra por token: del orden de USD 0,10 por minuto de
conversación. Colgá con el botón cuando no estés probando — la sesión
sigue facturando mientras está abierta aunque nadie hable.

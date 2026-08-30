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

## Correrlo en dos computadoras (una persona de agente, otra de transportista)

Para que la negociación sea una conversación real entre dos personas en dos
máquinas — una atendiendo la llamada como transportista, la otra mirando la
dashboard como agente — hace falta que las dos computadoras se vean por red
local (mismo Wi-Fi) y que las dos páginas dejen de asumir `localhost`.

**1. Elegí una máquina como "servidor".** Es la que ya tiene todo instalado:
corre `uvicorn` (backend, puerto 8000) y `npm run dev` (server de voz,
puerto 3000). Puede ser la laptop de cualquiera de las dos personas — la
otra persona solo necesita un navegador.

**2. Levantá el backend escuchando en la red, no solo en esa máquina:**

```bash
uvicorn app.main:app --reload --port 8000 --host 0.0.0.0
```

(el `--host 0.0.0.0` es lo único que cambia respecto al comando de siempre
— sin él, el backend solo contesta pedidos que salen de la misma máquina).
`npm run dev` no necesita ningún cambio: Express ya escucha en todas las
interfaces de red por default.

**3. Buscá la IP de la máquina servidor en esa misma red Wi-Fi:**
- Mac: `ipconfig getifaddr en0` en la Terminal (o System Settings → Wi-Fi → Details).
- Windows: `ipconfig` en cmd, la línea "IPv4 Address" del adaptador Wi-Fi.
- Linux: `hostname -I`.

Va a ser algo como `192.168.1.23`. Usalo en los dos pasos siguientes.

**4. La persona transportista** (en su propia laptop) abre en el navegador:

```
http://192.168.1.23:3000
```

(la IP de la máquina servidor, puerto 3000 — es la misma pantalla de
siempre). Ahí atiende la llamada y habla con Volta como si fuera el
transportista.

**Antes de eso, en ESA laptop (la del transportista) hay que habilitar el
micrófono para esa dirección**, porque Chrome solo expone `getUserMedia` en
"contextos seguros" (https, o localhost) — una IP de red local por http
plano no cuenta, y sin este paso el botón de atender tira
`cannot read properties of undefined (reading 'getUserMedia')`:

1. Andá a `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
2. En el campo de texto, escribí la misma URL de arriba: `http://192.168.1.23:3000`
3. Poné el desplegable de al lado en **Enabled**
4. Apretá **Relaunch** abajo de todo

Se hace una sola vez por máquina — después de reiniciar Chrome, esa
dirección puntual queda tratada como segura y el micrófono funciona normal.

**5. La persona agente** abre `dashboard/index.html` como archivo local de
siempre, pero agregando el parámetro `server` en la barra de direcciones:

```
file:///.../dashboard/index.html?server=192.168.1.23
```

Con eso la dashboard deja de pegarle a `localhost` y apunta a la máquina
servidor tanto para el backend como para el server de voz.

**La primera vez que hagas esto, el sistema operativo de la máquina
servidor va a preguntar si `python`/`uvicorn` y `node` pueden aceptar
conexiones entrantes** (firewall de Mac o Windows) — hay que aceptar los
dos, si no la otra computadora no llega a ninguna URL.

**Si el Wi-Fi del lugar no sirve** (algunas redes de eventos aíslan a los
dispositivos entre sí, "client isolation", y esto no va a andar) — armar un
hotspot personal desde un celular y conectar las dos laptops ahí es el
fallback más confiable.

**Límite a tener en cuenta:** la escalación a humano ("Atender llamada"
desde Modo Resolución) asume que quien atiende está en la MISMA máquina que
tiene la llamada abierta — al atender, la dashboard abre la pestaña de voz
en el navegador de quien clickeó, pero el micrófono y el audio real de la
llamada viven únicamente en la pestaña de la persona transportista. Para
esta demo a dos computadoras, entonces, probar la escalación desde la
máquina de la persona transportista (no remotamente desde la del agente) —
sumar una escalación que de verdad cruce de una compu a la otra requeriría
un puente de audio entre navegadores que no está construido.

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

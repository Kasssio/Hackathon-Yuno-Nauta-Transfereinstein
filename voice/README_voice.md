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

**⚠️ Si al apretar "Atender llamada" te aparece un error tipo `cannot
read properties of undefined (reading 'getUserMedia')`** en el estado de
la página, es porque el navegador no te deja usar el micrófono fuera de
`localhost` sin HTTPS — ver la sección "Arreglar el error de micrófono
(getUserMedia) — túnel HTTPS" más abajo, es la forma más confiable de
resolverlo.

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

**La escalación a humano SÍ cruza de una compu a la otra.** Al apretar
"Atender llamada" en Modo Resolución, la dashboard abre
`voice/public/operador.html` en la máquina del agente — esa pestaña prende
el micrófono del agente y arma una conexión de audio propia (WebRTC,
señalizada por el mismo server de voz) directo contra la pestaña del
transportista, en paralelo a la llamada que el transportista sigue
teniendo con Volta (que se queda en silencio mientras dura la escalación).
Ver "Puente de audio con el operador" más abajo para el detalle y las
mismas consideraciones de HTTPS/micrófono que en la sección anterior —
aplican igual del lado del operador.

## Arreglar el error de micrófono (getUserMedia) — túnel HTTPS

Los navegadores solo dejan usar el micrófono (`navigator.mediaDevices.
getUserMedia`) en páginas servidas por HTTPS, o en `http://localhost`. Una
IP de LAN por `http://` plano (`http://192.168.1.23:3000`) no cuenta como
"seguro", así que `navigator.mediaDevices` directamente no existe ahí — de
ahí el error `cannot read properties of undefined (reading 'getUserMedia')`
al apretar "Atender llamada" desde la computadora del transportista.

Hay un flag de Chrome (`chrome://flags/#unsafely-treat-insecure-origin-as-
secure`) que en teoría lo evita, pero en la práctica es frágil: hay que
tipear el origen exacto, reiniciar Chrome de verdad, y solo funciona en
Chrome/Chromium (no en Safari ni Firefox) — si la IP cambia o el navegador
no es Chrome, vuelve a romperse. La solución confiable es exponer el
server de voz por HTTPS de verdad con un túnel, y ya no depende de flags ni
de qué navegador use cada uno:

**1. Instalá `cloudflared`** en la máquina "servidor" (la misma que corre
`npm run dev`), una sola vez:

```bash
# Mac, con Homebrew:
brew install cloudflared

# Sin Homebrew (Mac o Linux), bajando el binario directo:
# https://github.com/cloudflare/cloudflared/releases → cloudflared-darwin-arm64.tgz (o el que corresponda)

# Windows: instalador en
# https://github.com/cloudflare/cloudflared/releases (cloudflared-windows-amd64.msi)
```

**2. Con `npm run dev` ya corriendo** (server de voz en el puerto 3000),
abrí OTRA terminal y corré:

```bash
cloudflared tunnel --url http://localhost:3000
```

Va a imprimir una URL como `https://palabras-al-azar.trycloudflare.com` —
esa es la que usa la persona transportista, en cualquier navegador, en
cualquier red (ni siquiera hace falta que esté en el mismo Wi-Fi que la
máquina servidor: el túnel sale a internet, así que hasta anda con datos
móviles). No hace falta ningún flag ni configuración del lado del
navegador.

**No hace falta un segundo túnel para el backend (puerto 8000).** El
server de voz ahora hace de proxy: todo pedido a `/backend/*` en el puerto
3000 se reenvía él mismo al backend (por default a
`http://localhost:8000`, asumiendo que corren en la misma máquina, que es
el setup normal). El navegador del transportista solo le habla a un único
origen — el túnel — así que esto no rompe nada de lo que ya usa el
backend (`find_carriers`, cotizaciones, commitments, etc.).

**La dashboard de la persona agente sigue igual que antes**, con
`?server=192.168.1.23` apuntando a la máquina servidor por LAN — no hace
falta tocar nada ahí, porque la dashboard no usa el micrófono y ya tenía
CORS abierto.

**Si preferís seguir con el flag de Chrome en vez del túnel** (por ejemplo
si no hay internet y solo hace falta LAN): `chrome://flags/#unsafely-
treat-insecure-origin-as-secure`, pegá ahí el origen exacto (por ejemplo
`http://192.168.1.23:3000`, sin barra al final), "Enable", y "Relaunch"
(una pestaña nueva no alcanza, hay que reiniciar Chrome entero).

## Puente de audio con el operador (escalación en vivo)

Cuando el transportista pide hablar con una persona y Volta escala, el
agente aprieta "Atender llamada" en Modo Resolución de la dashboard. Eso
abre `voice/public/operador.html` — UNA PÁGINA DISTINTA de `index.html`,
pensada para el operador, no para el transportista:

- El transportista sigue en su pestaña de siempre (`index.html`), en la
  MISMA llamada que ya tenía con Volta — nunca se va de ahí ni pierde esa
  conexión.
- El operador, en `operador.html`, aprieta "Conectar micrófono": eso prende
  SU mic y arma una `RTCPeerConnection` propia directo contra la pestaña
  del transportista (no contra OpenAI — Volta no participa de este audio).
  La señalización (SDP/ICE) viaja por el mismo WebSocket `/panel` que ya se
  usaba para transcripción y control; `server.ts` solo la reenvía de una
  pestaña a la otra, no le importa el contenido.
- Mientras dura la escalación, Volta queda en modo texto (no habla, no
  reacciona a audio — ver `setTurnDetection(false)` en `entrarEnEscalacion`
  de `client.js`), así que el transportista solo escucha al operador.
  "Devolver a Volta" (desde cualquiera de las dos pestañas, o desde el
  botón de la dashboard) cierra el puente y hace que Volta retome.

**El operador también necesita HTTPS o localhost para el micrófono**, por
la misma razón que el transportista (ver la sección de arriba). Si el
operador está en otra máquina, la dashboard tiene que apuntar `VOZ` al
túnel HTTPS en vez de a la IP de LAN — agregá `&voz=` a la URL con la que
abrís la dashboard:

```
file:///.../dashboard/index.html?server=192.168.1.23&voz=https://palabras-al-azar.trycloudflare.com
```

(`?server=` sigue siendo para el backend — puede seguir siendo la IP de
LAN, esa parte no necesita HTTPS. `?voz=` es solo para el server de voz,
que es el que de verdad usa el micrófono en las dos puntas.)

Si agente y transportista están en la MISMA máquina (una sola compu, dos
pestañas), ninguno de estos dos parámetros hace falta — `localhost` ya
cuenta como origen seguro para el navegador.

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

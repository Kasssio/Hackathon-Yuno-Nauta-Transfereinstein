import "dotenv/config";
import express from "express";
import path from "node:path";
import WebSocket from "ws";
import { sessionConfig } from "./session-config.js";
import { crearManejadorDeTools } from "./tools.js";

const app = express();
app.use(express.json());
app.use((_req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  next();
});
app.use(express.static(path.join(process.cwd(), "public")));

const OPENAI_KEY = process.env.OPENAI_API_KEY;

// La config de sesión es la misma para el browser y para el teléfono.
const sesionRealtime = {
  type: "realtime",
  model: "gpt-realtime-2.1",
  output_modalities: ["audio"],
  instructions: sessionConfig.instructions,
  audio: {
    input: {
      transcription: { model: "gpt-live-transcribe" },
      turn_detection: {
        type: "semantic_vad",
        eagerness: "auto", // <-- perilla de turnos: low | medium | high | auto
        create_response: true,
        interrupt_response: true,
      },
    },
    output: { voice: sessionConfig.voice },
  },
  tools: sessionConfig.tools,
  tool_choice: "auto",
};

app.post("/session", async (_req, res) => {
  try {
    const r = await fetch("https://api.openai.com/v1/realtime/client_secrets", {
      method: "POST",
      headers: { Authorization: `Bearer ${OPENAI_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ session: sesionRealtime }),
    });
    res.status(r.status).json(await r.json());
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: "mint failed" });
  }
});

// ---------------------------------------------------------------------
// Llamada saliente por teléfono: Twilio disca y puentea al SIP de OpenAI
// ---------------------------------------------------------------------

const sipDeVolta = () =>
  `sip:${process.env.OPENAI_PROJECT_ID}@sip.api.openai.com;transport=tls`;

const twilioAuth = () => ({
  Authorization:
    "Basic " +
    Buffer.from(`${process.env.TWILIO_ACCOUNT_SID}:${process.env.TWILIO_AUTH_TOKEN}`).toString("base64"),
  "Content-Type": "application/x-www-form-urlencoded",
});

const twilioPost = (recurso: string, campos: Record<string, string>) =>
  fetch(`https://api.twilio.com/2010-04-01/Accounts/${process.env.TWILIO_ACCOUNT_SID}${recurso}`, {
    method: "POST",
    headers: twilioAuth(),
    body: new URLSearchParams(campos),
  });

// Nombre de la sala de la llamada en curso. Una sola llamada a la vez, que
// es lo que necesita la demo.
let salaActual: string | null = null;
let twilioCallSid: string | null = null;

// UNA llamada a la vez, sin excepciones. Sin este candado, el rellamado por
// corte y el reintento por ruteo se dispararon juntos: tres llamadas en
// rafaga, tres conferencias, y tres Voltas escuchandose entre ellos (uno
// transcribia el saludo del otro como si fuera el transportista). Ademas es
// el patron que los sistemas antifraude de telefonia leen como toll fraud.
let llamadaEnCurso = false;

// Rellamado cuando el transportista corta antes de resolver. Apagado por
// defecto: en una demo, que el agente vuelva a llamar solo es mas riesgoso
// que util. Se activa con MAX_REINTENTOS=1 en el .env.
const MAX_REINTENTOS = Number(process.env.MAX_REINTENTOS ?? 0);
let reintentos = 0;
let ultimoDestino: string | null = null;
let volviendoALlamar = false;

// Colgar de verdad: se corta la pata de Twilio (el telefono) y la de
// OpenAI. Sin esto end_call solo hacia que Volta se despidiera de palabra
// y la llamada quedaba abierta hasta que cortaba el humano.
async function colgarLlamada(callId: string) {
  if (twilioCallSid) {
    await twilioPost(`/Calls/${twilioCallSid}.json`, { Status: "completed" })
      .then((r) => console.log("[colgar] twilio ->", r.status))
      .catch((e) => console.error("[colgar] twilio", e.message));
  }
  await fetch(`https://api.openai.com/v1/realtime/calls/${callId}/hangup`, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}` },
  })
    .then((r) => console.log("[colgar] openai ->", r.status))
    .catch((e) => console.error("[colgar] openai", e.message));
}

// Camino directo: cadena de dos patas. Es el que venia funcionando y queda
// como fallback si la conferencia da problemas.
app.all("/twiml/bridge", (_req, res) => {
  res.type("text/xml").send(
    `<Response><Dial answerOnBridge="true"><Sip>${sipDeVolta()}</Sip></Dial></Response>`
  );
});

// Camino de conferencia: el transportista entra a una sala y Volta se suma
// como participante. Asi al escalar se puede sumar el operador sin cortar.
const salasConVolta = new Set<string>();

app.all("/twiml/conference", (_req, res) => {
  const sala = salaActual ?? "volta";
  res.type("text/xml").send(
    `<Response><Dial><Conference startConferenceOnEnter="true" endConferenceOnExit="true" beep="false" waitUrl="">${sala}</Conference></Dial></Response>`
  );
  // Twilio puede pedir este TwiML mas de una vez para la misma llamada; sin
  // este guardia entraban dos Voltas a la misma sala y se hablaban entre si.
  if (salasConVolta.has(sala)) return;
  salasConVolta.add(sala);
  sumarAVolta(sala);
});

// La sala existe recien cuando el transportista entra, asi que reintentamos.
async function sumarAVolta(sala: string, intento = 1) {
  const r = await twilioPost(`/Conferences/${encodeURIComponent(sala)}/Participants.json`, {
    To: sipDeVolta(),
    From: process.env.TWILIO_FROM_NUMBER!,
  });
  if (r.ok) return console.log("[conf] Volta entro a", sala);
  if (intento >= 6) return console.error("[conf] Volta no pudo entrar:", await r.text());
  setTimeout(() => sumarAVolta(sala, intento + 1), 1200);
}

// Suma al operador humano a la sala en curso (escalacion).
app.post("/call/operator", async (_req, res) => {
  if (!salaActual) return res.status(409).json({ error: "no hay llamada en curso" });
  const r = await twilioPost(`/Conferences/${encodeURIComponent(salaActual)}/Participants.json`, {
    To: process.env.OPERATOR_PHONE!,
    From: process.env.TWILIO_FROM_NUMBER!,
  });
  const data: any = await r.json();
  console.log("[conf] operador ->", r.status, data.call_sid ?? data.message);
  if (r.ok) escalacion.atendida = true;
  res.status(r.status).json({ ok: r.ok, error: data.message });
});

// Las llamadas internacionales a veces fallan al enrutarse: Twilio devuelve
// "failed" con duracion 0 y SIN codigo de error, y el telefono nunca suena.
// Es intermitente y reintentar la resuelve. Sin esto, en la demo se traduce
// en "no me llego la llamada" sin ninguna pista de por que.
const MAX_REINTENTOS_RUTEO = 2;

function vigilarRuteo(sid: string, to: string, intento: number) {
  let chequeos = 0;
  const t = setInterval(async () => {
    if (++chequeos > 8) return clearInterval(t);
    try {
      const r = await fetch(
        `https://api.twilio.com/2010-04-01/Accounts/${process.env.TWILIO_ACCOUNT_SID}/Calls/${sid}.json`,
        { headers: { Authorization: twilioAuth().Authorization } }
      );
      const c: any = await r.json();
      // "busy" y "no-answer" significan que el telefono si sono: eso no se
      // reintenta acá, es decision de la persona.
      if (c.status !== "failed" && c.status !== "canceled") {
        if (["completed", "in-progress", "answered"].includes(c.status)) clearInterval(t);
        // Sono pero nadie atendio: no se reintenta (es decision de la
        // persona), pero hay que soltar el candado o queda trabado.
        if (["busy", "no-answer"].includes(c.status)) { clearInterval(t); llamadaEnCurso = false; }
        return;
      }
      clearInterval(t);
      if (intento >= MAX_REINTENTOS_RUTEO) {
        llamadaEnCurso = false;
        return console.error(`[ruteo] la llamada fallo ${intento + 1} veces, no reintento mas`);
      }
      console.log(`[ruteo] fallo sin sonar — reintento ${intento + 1}/${MAX_REINTENTOS_RUTEO} en 3s`);
      llamadaEnCurso = false;
      setTimeout(() => {
        fetch("http://localhost:3000/call/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ to, __reintento: true, __ruteo: intento + 1 }),
        }).catch((e) => console.error("[ruteo] no se pudo reintentar:", e.message));
      }, 3000);
    } catch (e: any) {
      console.error("[ruteo] no se pudo consultar el estado:", e.message);
    }
  }, 3000);
}

// Diagnostico: si esto se escucha, el TwiML corre y el problema es el SIP.
app.all("/twiml/test", (_req, res) => {
  res.type("text/xml").send(
    `<Response><Say language="es-MX">Hola. Esto es una prueba. El TwiML se ejecuto correctamente.</Say><Pause length="2"/></Response>`
  );
});

app.post("/call/start", async (req, res) => {
  if (llamadaEnCurso) {
    console.warn("[call/start] ya hay una llamada en curso — se ignora el pedido");
    return res.status(409).json({ error: "ya hay una llamada en curso" });
  }
  llamadaEnCurso = true;
  const to = req.body?.to || process.env.DEMO_PHONE;
  // Una llamada pedida a mano arranca de cero: no arrastra los reintentos
  // de la anterior.
  if (!req.body?.__reintento) { reintentos = 0; volviendoALlamar = false; }
  ultimoDestino = to;
  // conferencia por defecto (permite escalar sin cortar); "bridge" es el
  // camino viejo de dos patas y "test" solo habla, para diagnostico.
  const modo = req.body?.twiml ?? "conference";
  const ruta = modo === "test" ? "/twiml/test" : modo === "bridge" ? "/twiml/bridge" : "/twiml/conference";
  if (ruta === "/twiml/conference") salaActual = "volta-" + Date.now();
  const sid = process.env.TWILIO_ACCOUNT_SID;

  try {
    const r = await fetch(`https://api.twilio.com/2010-04-01/Accounts/${sid}/Calls.json`, {
      method: "POST",
      headers: {
        Authorization: "Basic " + Buffer.from(`${sid}:${process.env.TWILIO_AUTH_TOKEN}`).toString("base64"),
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({
        To: to,
        From: process.env.TWILIO_FROM_NUMBER!,
        Url: `${process.env.PUBLIC_URL}${ruta}`,
      }),
    });
    const data: any = await r.json();
    if (data.sid) twilioCallSid = data.sid;
    console.log("[twilio] llamando a", to, "->", r.status, data.sid ?? data.message);
    if (data.sid) vigilarRuteo(data.sid, to, Number(req.body?.__ruteo ?? 0));
    else llamadaEnCurso = false; // Twilio rechazo el pedido: se libera el candado
    res.status(r.status).json({ sid: data.sid, to, error: data.message });
  } catch (e: any) {
    llamadaEnCurso = false;
    console.error(e);
    res.status(500).json({ error: e.message });
  }
});

// OpenAI avisa acá cuando entra la llamada por SIP.
app.post("/openai/webhook", async (req, res) => {
  const ev = req.body;
  res.sendStatus(200);
  if (ev?.type !== "realtime.call.incoming") return;

  const callId = ev.data.call_id;
  transcripcion = [];

  // Si nosotros no iniciamos nada, es una llamada ENTRANTE de verdad: el
  // chofer o el dispatcher llamando a Volta. Si llamadaEnCurso ya estaba en
  // true, este webhook es la pata SIP de nuestra propia saliente.
  const entrante = !llamadaEnCurso;
  if (entrante) llamadaEnCurso = true;

  const cabeceras: any[] = ev.data.sip_headers ?? [];
  const desde = (cabeceras.find((h) => h.name?.toLowerCase() === "from")?.value ?? "")
    .replace(/^sip:/, "")
    .split("@")[0];
  console.log(`[sip] llamada ${entrante ? "ENTRANTE de " + (desde || "desconocido") : "saliente"}`, callId);

  const r = await fetch(`https://api.openai.com/v1/realtime/calls/${callId}/accept`, {
    method: "POST",
    headers: { Authorization: `Bearer ${OPENAI_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify(sesionRealtime),
  });
  if (!r.ok) return console.error("[sip] accept fallo", r.status, await r.text());

  controlarLlamada(callId, entrante, desde);
});

// Lo que el dashboard consulta para saber si tiene que sonar la alarma.
let escalacion: {
  activa: boolean; motivo: string; resumen: string; ts: number; atendida: boolean;
} = { activa: false, motivo: "", resumen: "", ts: 0, atendida: false };

// Transcripcion de la llamada real, para que el dashboard la muestre al
// lado de las simuladas.
let transcripcion: { role: string; text: string; ts: number }[] = [];

app.get("/call/status", (_req, res) => {
  res.json({ sala: salaActual, escalacion, transcripcion });
});

// Handle de la llamada viva, para poder callar/despertar a Volta desde los
// endpoints de escalacion.
let llamadaViva: {
  enviar: (o: any) => void;
  callarse: () => void;
  despertar: () => void;
} | null = null;

// El operador termino de hablar: Volta vuelve y registra lo acordado con
// todo lo que escucho durante el tramo humano-humano.
app.post("/call/return", (_req, res) => {
  if (!llamadaViva) return res.status(409).json({ error: "no hay llamada en curso" });
  llamadaViva.despertar();
  llamadaViva.enviar({
    type: "response.create",
    response: {
      instructions:
        "La conversación la tomó un operador humano de tu equipo y ya terminó. En base a TODO " +
        "lo que escuchaste durante ese tramo, registrá el commitment que se haya acordado con " +
        "record_commitment. Si no se acordó nada concreto, decilo en una frase corta y no registres nada.",
    },
  });
  escalacion.activa = false;
  console.log("[escalacion] vuelve Volta");
  res.json({ ok: true });
});

// El WebSocket no lleva audio: es el canal de control de la llamada.
function controlarLlamada(callId: string, entrante = false, desde = "") {
  // Se pone en true al escalar; cuando termina la frase de traspaso, Volta
  // se calla. Sin esto se metería a hablar arriba de los dos humanos.
  let esperandoFraseDeTraspaso = false;
  let esperandoFraseDeCierre = false;
  // Para decidir si vale la pena volver a llamar cuando se corta.
  let cierreDeliberado = false;
  let huboCommitment = false;

  const onToolCall = crearManejadorDeTools(callId, (motivo) => {
    esperandoFraseDeTraspaso = true;
    escalacion = { activa: true, motivo, resumen: "", ts: Date.now(), atendida: false };
    // Resumen fuera de banda: no entra en la conversacion que oye el
    // transportista, es solo para el humano que va a tomar la llamada.
    enviar({
      type: "response.create",
      response: {
        conversation: "none",
        metadata: { topic: "resumen_escalacion" },
        output_modalities: ["text"],
        instructions:
          "Resumí la llamada hasta ahora para el operador humano que la está por tomar. " +
          "Máximo 5 líneas, sin saludos: con quién se está hablando, qué pidió, qué se " +
          "ofreció, dónde está el desacuerdo, y qué falta cerrar.",
      },
    });
  }, () => {
    esperandoFraseDeCierre = true;
    cierreDeliberado = true;
  });

  const ws = new WebSocket(`wss://api.openai.com/v1/realtime?call_id=${callId}`, {
    headers: { Authorization: `Bearer ${OPENAI_KEY}` },
  });

  const enviar = (o: any) => ws.send(JSON.stringify(o));

  // Callar a Volta sin sacarlo de la conferencia: el VAD y la transcripcion
  // siguen corriendo (escucha todo), pero no genera respuestas propias.
  const turnos = (activo: boolean) =>
    enviar({
      type: "session.update",
      session: {
        type: "realtime",
        audio: {
          input: {
            transcription: { model: "gpt-live-transcribe" },
            turn_detection: {
              type: "semantic_vad",
              eagerness: "auto",
              create_response: activo,
              interrupt_response: activo,
            },
          },
        },
      },
    });

  llamadaViva = {
    enviar,
    callarse: () => { turnos(false); console.log("[escalacion] Volta en modo escucha"); },
    despertar: () => { turnos(true); console.log("[escalacion] Volta vuelve a hablar"); },
  };

  // Apertura en dos tiempos: primero levanta contexto en silencio, despues
  // saluda. Recien cuando termino de saludar se habilitan los turnos
  // automaticos, asi la conversacion siempre la abre Volta.
  let apertura: "contexto" | "saludo" | "listo" = "contexto";

  // El contexto se resuelve del lado del server y se le inyecta al prompt
  // antes de que hable. Antes Volta lo levantaba con tres tool calls, o sea
  // tres ciclos de respuesta: 5 a 8 segundos de silencio despues de que el
  // transportista atendia, que el llenaba diciendo "hola".
  // Cruza el numero de quien llama contra el catalogo de transportistas.
  // Es la primera barrera contra suplantacion en una entrante, y ademas le
  // ahorra a Volta tener que preguntar con quien habla.
  async function identificarLlamante(): Promise<string | null> {
    if (!desde) return null;
    try {
      const soloDigitos = (t: string) => (t || "").replace(/\D/g, "");
      const mio = soloDigitos(desde);
      const r: any = await onToolCall("find_carriers", {});
      for (const c of r?.candidatos ?? []) {
        const suyo = soloDigitos(c.telefono);
        if (suyo && mio && (mio.endsWith(suyo.slice(-8)) || suyo.endsWith(mio.slice(-8)))) {
          return c.nombre;
        }
      }
    } catch { /* sin catalogo, Volta pregunta a mano */ }
    return null;
  }

  async function abrirLlamadaEntrante() {
    let quien: string | null = null;
    let ctx = "";
    try {
      quien = await identificarLlamante();
      const [op, mandato, com]: any = await Promise.all([
        onToolCall("get_operacion_actual", {}),
        onToolCall("check_mandato", {}),
        onToolCall("get_commitment_vigente", {}),
      ]);
      ctx =
        `

CONTEXTO DE ESTA LLAMADA — ES ENTRANTE, TE ESTAN LLAMANDO A VOS
` +
        (quien
          ? `El número que llama figura en el catálogo como ${quien}. Mencionalo y pedí ` +
            `confirmación, no lo des por hecho.
`
          : `El número que llama NO figura en el catálogo. Preguntá con quién hablás y de qué ` +
            `transportista, y pedile que confirme el número de contenedor antes de darle ` +
            `cualquier dato de la operación.
`) +
        `Operación: ${op?.cliente}, contenedor ${op?.contenedor_id}, de ${op?.puerto_origen} a ${op?.destino}.
` +
        (com?.hay_reserva
          ? `Reserva vigente: ${com.contraparte}, ${com.monto} pesos, retiro ${com.fecha_retiro} ${com.hora_retiro ?? ""}.
`
          : `Todavía no hay ninguna reserva cerrada para esta operación.
`) +
        `Podés mover el retiro solo dentro de: ${mandato?.ventana_inicio} a ${mandato?.ventana_fin}` +
        (mandato?.horario_inicio ? `, entre las ${mandato.horario_inicio} y las ${mandato.horario_fin}` : "") +
        `, hasta ${mandato?.tope_precio} pesos.
` +
        `ATENDÉ EN INGLÉS con un saludo corto — identificate como Volta y dejá que te digan a qué ` +
        `llaman. No ofrezcas ni preguntes por disponibilidad: no sos vos quien llama esta vez.`;
    } catch (e: any) {
      console.error("[apertura entrante] sin contexto:", e.message);
    }
    enviar({
      type: "session.update",
      session: { type: "realtime", instructions: sessionConfig.instructions + ctx },
    });
    apertura = "saludo";
    enviar({ type: "response.create" });
    vigilarMandato();
    console.log("[apertura] entrante | llamante:", quien ?? "desconocido");
  }

  async function abrirLlamada() {
    if (entrante) return abrirLlamadaEntrante();
    let ctx = "";
    try {
      const [op, carriers, mandato]: any = await Promise.all([
        onToolCall("get_operacion_actual", {}),
        onToolCall("find_carriers", { limite: 3 }),
        onToolCall("check_mandato", {}),
      ]);
      const elegido = carriers?.candidatos?.[0];
      const horario =
        mandato?.horario_inicio && mandato?.horario_fin
          ? ` entre las ${mandato.horario_inicio} y las ${mandato.horario_fin}`
          : "";
      const fecha =
        mandato?.ventana_inicio === mandato?.ventana_fin
          ? `el ${mandato?.ventana_inicio}`
          : `entre el ${mandato?.ventana_inicio} y el ${mandato?.ventana_fin}`;

      ctx =
        `\n\nCONTEXTO DE ESTA LLAMADA (ya resuelto, no lo consultes de nuevo para abrir)\n` +
        `Estás llamando vos a: ${elegido?.nombre ?? "el transportista"}.\n` +
        `Cliente: ${op?.cliente}. Contenedor ${op?.contenedor_id}, de ${op?.puerto_origen} a ${op?.destino}.\n` +
        `Retiro: ${fecha}${horario}. Tope: ${mandato?.tope_precio} pesos.\n` +
        `ARRANCÁ VOS Y EN INGLÉS: saludá a ${elegido?.nombre ?? "el transportista"} por su ` +
        `nombre, presentate como Volta, decí en una frase de qué transporte se trata y preguntá ` +
        `si tiene disponibilidad para esa fecha y ese horario. Breve, una idea. Nunca preguntes ` +
        `qué necesita la contraparte: sos vos quien llama y quien pide. Si te contesta en otro ` +
        `idioma, seguí en ese idioma desde el turno siguiente.` +
        (volviendoALlamar
          ? `\nOJO: la llamada anterior se cortó antes de cerrar nada. Estás volviendo a llamar. ` +
            `Al abrir, reconocelo en media frase ("se nos cortó recién") y retomá donde quedaron ` +
            `en vez de empezar de cero. No pidas disculpas de más ni lo repitas después.`
          : "");
    } catch (e: any) {
      console.error("[apertura] no se pudo precargar contexto:", e.message);
    }

    // El contexto va al prompt de sesión, no como override de la respuesta:
    // así el saludo sale con el prompt completo, no reemplazado.
    enviar({
      type: "session.update",
      session: { type: "realtime", instructions: sessionConfig.instructions + ctx },
    });
    apertura = "saludo";
    enviar({ type: "response.create" });
    vigilarMandato();
  }

  // El humano puede revocar el mandato mientras la llamada esta en curso —
  // es el momento del trial by fire. El guardrail ya impedia cerrar nada,
  // pero Volta no se enteraba hasta que intentaba comprometerse: seguia
  // regateando y quedaba mal. Acá se entera en el momento.
  let vigilancia: NodeJS.Timeout | null = null;
  function vigilarMandato() {
    if (vigilancia) return;
    vigilancia = setInterval(async () => {
      try {
        const m: any = await onToolCall("check_mandato", {});
        if (!m?.revocado) return;
        clearInterval(vigilancia!);
        vigilancia = null;
        console.log("[mandato] REVOCADO en vivo — cortando la negociación");
        enviar({ type: "response.cancel" });
        enviar({
          type: "response.create",
          response: {
            instructions:
              "URGENTE: mientras hablabas, tu empresa dio de baja la autorización para esta " +
              "operación. Ya no podés acordar, confirmar ni prometer nada, ni siquiera lo que " +
              "venías conversando. Decíselo a la contraparte AHORA, en una sola frase, sin " +
              "tecnicismos y sin nombrar mandatos ni sistemas: que surgió un cambio de tu lado y " +
              "no podés cerrar la reserva, que los van a contactar. No des detalles, no negocies " +
              "más, no aceptes nada. Inmediatamente después llamá a end_call.",
          },
        });
      } catch {
        /* backend caido: se reintenta en el proximo ciclo */
      }
    }, 4000);
  }

  ws.on("open", () => {
    console.log("[sip] control abierto", callId);
    // La apertura se dispara acá y NO en session.created: al conectarse a
    // una llamada SIP ya existente (?call_id=), la sesion ya esta creada y
    // ese evento no llega nunca. Mientras se disparaba ahi, Volta arrancaba
    // sin contexto y respondia a lo que dijera el transportista.
    turnos(false);
    setTimeout(abrirLlamada, 800);
  });

  ws.on("message", async (raw) => {
    const ev = JSON.parse(raw.toString());


    if (ev.type === "response.done" && ev.response.metadata?.topic === "resumen_escalacion") {
      const parte = (ev.response.output?.[0]?.content ?? []).find((c: any) => c.type === "output_text");
      escalacion.resumen = parte?.text ?? "";
      console.log("[escalacion] resumen listo");
      return;
    }

    if (ev.type === "conversation.item.input_audio_transcription.completed") {
      console.log("[transportista]", ev.transcript);
      if (ev.transcript?.trim()) transcripcion.push({ role: "user", text: ev.transcript, ts: Date.now() });
    }
    if (ev.type === "response.output_audio_transcript.done") {
      console.log("[volta]", ev.transcript);
      if (ev.transcript?.trim()) transcripcion.push({ role: "agent", text: ev.transcript, ts: Date.now() });
    }

    if (ev.type === "response.done") {
      // Un solo response.create al final: si mandamos uno por cada tool
      // la API rechaza los siguientes con conversation_already_has_active_response.
      let hubo = false;
      for (const item of ev.response.output ?? []) {
        if (item.type !== "function_call") continue;
        hubo = true;
        // Nunca dejar que una tool tumbe el proceso a mitad de llamada:
        // el error vuelve como resultado y Volta reacciona hablando.
        let result: any;
        try {
          result = await onToolCall(item.name, JSON.parse(item.arguments || "{}"));
        } catch (e: any) {
          console.error("[tool] fallo", item.name, e.message);
          result = { error: e.message };
        }
        if (item.name === "record_commitment" && result?.aprobado) huboCommitment = true;
        enviar({
          type: "conversation.item.create",
          item: { type: "function_call_output", call_id: item.call_id, output: JSON.stringify(result) },
        });
      }
      // SIEMPRE pedir la respuesta que sigue a una tool. Cuando esto estaba
      // condicionado al estado de la apertura y la apertura quedaba trabada,
      // Volta ejecutaba la tool y despues se quedaba mudo para siempre:
      // nadie le pedia que hablara.
      if (hubo) enviar({ type: "response.create" });

      // Termino de saludar -> recien ahi se habilitan los turnos automaticos.
      if (apertura === "saludo" && !hubo) {
        apertura = "listo";
        turnos(true);
        console.log("[apertura] Volta saludó, turnos habilitados");
      }

      // La frase de traspaso ya salió al aire: ahora sí Volta se calla y
      // queda escuchando a los dos humanos.
      if (esperandoFraseDeTraspaso && !hubo) {
        esperandoFraseDeTraspaso = false;
        llamadaViva?.callarse();
      }

      // Se despidió: ahora cuelga de verdad. El delay deja que termine de
      // salir el audio de la despedida antes de cortar la linea.
      if (esperandoFraseDeCierre && !hubo) {
        esperandoFraseDeCierre = false;
        console.log("[colgar] cortando en 2s");
        setTimeout(() => colgarLlamada(callId), 2000);
      }
    }

    if (ev.type === "error") console.error("[realtime]", ev.error);
  });

  ws.on("close", () => {
    console.log("[sip] llamada terminada", callId);
    llamadaViva = null;
    llamadaEnCurso = false;
    if (vigilancia) { clearInterval(vigilancia); vigilancia = null; }

    // Si la llamada murio sin resolverse, el transportista corto. Volta
    // vuelve a llamar una vez, retomando donde quedaron. No se rellama si
    // Volta colgo a proposito, si ya hay commitment, o si esta escalada:
    // en esos tres casos el corte es el final correcto.
    const resuelta = cierreDeliberado || huboCommitment || escalacion.activa;
    if (resuelta || reintentos >= MAX_REINTENTOS || !ultimoDestino) return;

    reintentos++;
    volviendoALlamar = true;
    console.log(`[rellamado] cortaron sin resolver — reintento ${reintentos}/${MAX_REINTENTOS} en 8s`);
    setTimeout(async () => {
      await fetch("http://localhost:3000/call/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to: ultimoDestino, __reintento: true }),
      }).catch((e) => console.error("[rellamado] fallo:", e.message));
    }, 8000);
  });
  ws.on("error", (e) => console.error("[sip] ws error", e.message));
}

// Red de seguridad: durante la demo el proceso no se cae por nada.
process.on("unhandledRejection", (e) => console.error("[unhandled]", e));
process.on("uncaughtException", (e) => console.error("[uncaught]", e));

app.listen(3000, () => console.log("http://localhost:3000"));

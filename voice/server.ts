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
      transcription: { model: "gpt-live-transcribe", language: "es" },
      turn_detection: {
        type: "semantic_vad",
        eagerness: "high", // <-- perilla de turnos: low | medium | high | auto
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
app.all("/twiml/conference", (_req, res) => {
  const sala = salaActual ?? "volta";
  res.type("text/xml").send(
    `<Response><Dial><Conference startConferenceOnEnter="true" endConferenceOnExit="true" beep="false" waitUrl="">${sala}</Conference></Dial></Response>`
  );
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

// Diagnostico: si esto se escucha, el TwiML corre y el problema es el SIP.
app.all("/twiml/test", (_req, res) => {
  res.type("text/xml").send(
    `<Response><Say language="es-MX">Hola. Esto es una prueba. El TwiML se ejecuto correctamente.</Say><Pause length="2"/></Response>`
  );
});

app.post("/call/start", async (req, res) => {
  const to = req.body?.to || process.env.DEMO_PHONE;
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
    res.status(r.status).json({ sid: data.sid, to, error: data.message });
  } catch (e: any) {
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
  console.log("[sip] llamada entrante", callId);
  transcripcion = [];

  const r = await fetch(`https://api.openai.com/v1/realtime/calls/${callId}/accept`, {
    method: "POST",
    headers: { Authorization: `Bearer ${OPENAI_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify(sesionRealtime),
  });
  if (!r.ok) return console.error("[sip] accept fallo", r.status, await r.text());

  controlarLlamada(callId);
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
function controlarLlamada(callId: string) {
  // Se pone en true al escalar; cuando termina la frase de traspaso, Volta
  // se calla. Sin esto se metería a hablar arriba de los dos humanos.
  let esperandoFraseDeTraspaso = false;
  let esperandoFraseDeCierre = false;

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
            transcription: { model: "gpt-live-transcribe", language: "es" },
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
  async function abrirLlamada() {
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
        `Retiro: ${fecha}${horario}. Tope: ${mandato?.tope_precio} dólares.\n` +
        `ARRANCÁ VOS: saludá a ${elegido?.nombre ?? "el transportista"} por su nombre, presentate ` +
        `como Volta, decí en una frase de qué transporte se trata y preguntá si tiene ` +
        `disponibilidad para esa fecha y ese horario. Breve, una idea. Nunca preguntes qué ` +
        `necesita la contraparte: sos vos quien llama y quien pide.`;
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
  }

  ws.on("open", () => console.log("[sip] control abierto", callId));

  ws.on("message", async (raw) => {
    const ev = JSON.parse(raw.toString());

    if (ev.type === "session.created") {
      // Volta abre SIEMPRE la conversacion. Arranca con las respuestas
      // automaticas apagadas: si el transportista dice "hola?" antes de que
      // Volta termine de levantar contexto, el modelo respondia a eso y
      // perdia el encuadre de que el es quien esta llamando.
      turnos(false);
      setTimeout(() => abrirLlamada(), 1200);
      return;
    }

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
        enviar({
          type: "conversation.item.create",
          item: { type: "function_call_output", call_id: item.call_id, output: JSON.stringify(result) },
        });
      }
      // Durante la apertura el encadenado lo maneja la secuencia de abajo,
      // no el loop de tools.
      if (hubo && apertura === "listo") enviar({ type: "response.create" });

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

  ws.on("close", () => console.log("[sip] llamada terminada", callId));
  ws.on("error", (e) => console.error("[sip] ws error", e.message));
}

// Red de seguridad: durante la demo el proceso no se cae por nada.
process.on("unhandledRejection", (e) => console.error("[unhandled]", e));
process.on("uncaughtException", (e) => console.error("[uncaught]", e));

app.listen(3000, () => console.log("http://localhost:3000"));

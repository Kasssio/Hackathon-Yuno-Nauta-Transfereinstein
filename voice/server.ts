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

// Twilio pide el TwiML por URL (las cuentas trial no aceptan el parametro
// inline), asi que se lo servimos desde el tunel publico.
app.all("/twiml/bridge", (_req, res) => {
  const sip = `sip:${process.env.OPENAI_PROJECT_ID}@sip.api.openai.com;transport=tls`;
  res.type("text/xml").send(`<Response><Dial answerOnBridge="true"><Sip>${sip}</Sip></Dial></Response>`);
});

// Diagnostico: si esto se escucha, el TwiML corre y el problema es el SIP.
app.all("/twiml/test", (_req, res) => {
  res.type("text/xml").send(
    `<Response><Say language="es-MX">Hola. Esto es una prueba. El TwiML se ejecuto correctamente.</Say><Pause length="2"/></Response>`
  );
});

app.post("/call/start", async (req, res) => {
  const to = req.body?.to || process.env.DEMO_PHONE;
  const ruta = req.body?.twiml === "test" ? "/twiml/test" : "/twiml/bridge";
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

  const r = await fetch(`https://api.openai.com/v1/realtime/calls/${callId}/accept`, {
    method: "POST",
    headers: { Authorization: `Bearer ${OPENAI_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify(sesionRealtime),
  });
  if (!r.ok) return console.error("[sip] accept fallo", r.status, await r.text());

  controlarLlamada(callId);
});

// El WebSocket no lleva audio: es el canal de control de la llamada.
function controlarLlamada(callId: string) {
  const onToolCall = crearManejadorDeTools(callId);
  const ws = new WebSocket(`wss://api.openai.com/v1/realtime?call_id=${callId}`, {
    headers: { Authorization: `Bearer ${OPENAI_KEY}` },
  });

  const enviar = (o: any) => ws.send(JSON.stringify(o));

  ws.on("open", () => console.log("[sip] control abierto", callId));

  ws.on("message", async (raw) => {
    const ev = JSON.parse(raw.toString());

    if (ev.type === "session.created") {
      enviar({
        type: "response.create",
        response: {
          instructions:
            "La llamada recién se conectó — todavía no habló nadie, ni vos ni la contraparte. " +
            "Antes de decir una sola palabra, llamá en orden a get_operacion_actual, después a " +
            "find_carriers, y después a check_mandato. No hables todavía: esta respuesta es solo " +
            "para levantar ese contexto. find_carriers te va a devolver varios candidatos — para " +
            "ESTA llamada en particular, tratá al primero de la lista (el mejor puntaje) como el " +
            "transportista específico que estás llamando ahora mismo. Con esos resultados vas a " +
            "tener de qué transporte se trata, a quién estás llamando, y tu mandato vigente — " +
            "recién en tu próximo turno abrí la llamada con tu saludo estándar, dirigido a ese " +
            "transportista por nombre.",
        },
      });
    }

    if (ev.type === "conversation.item.input_audio_transcription.completed") {
      console.log("[transportista]", ev.transcript);
    }
    if (ev.type === "response.output_audio_transcript.done") {
      console.log("[volta]", ev.transcript);
    }

    if (ev.type === "response.done") {
      // Un solo response.create al final: si mandamos uno por cada tool
      // la API rechaza los siguientes con conversation_already_has_active_response.
      let hubo = false;
      for (const item of ev.response.output ?? []) {
        if (item.type !== "function_call") continue;
        hubo = true;
        const result = await onToolCall(item.name, JSON.parse(item.arguments || "{}"));
        enviar({
          type: "conversation.item.create",
          item: { type: "function_call_output", call_id: item.call_id, output: JSON.stringify(result) },
        });
      }
      if (hubo) enviar({ type: "response.create" });
    }

    if (ev.type === "error") console.error("[realtime]", ev.error);
  });

  ws.on("close", () => console.log("[sip] llamada terminada", callId));
  ws.on("error", (e) => console.error("[sip] ws error", e.message));
}

app.listen(3000, () => console.log("http://localhost:3000"));

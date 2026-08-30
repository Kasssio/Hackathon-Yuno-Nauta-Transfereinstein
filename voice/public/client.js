let pc, dc, micStream, audioEl;
let turn = 0;
let userStoppedAt = null;
let analyser, analyserData, latencyRAF = null;

let escalado = false;
let esperandoFraseDeTraspaso = false;
let motivoEscalacion = "";
let esperandoFraseDeCierre = false;
let motivoFinLlamada = "";

const statusEl = () => document.getElementById("status");
const setStatus = (s) => (statusEl().textContent = s);
const btn = (id) => document.getElementById(id);

// ===== PUNTO DE INTEGRACIÓN: transcripción =====
export function onTranscript(role, text) {}

const BACKEND_URL = "http://localhost:8000";

// La operación activa se resuelve una sola vez, al conectar — así el
// modelo nunca tiene que saber ids. Para la demo alcanza con la
// primera operación que devuelva el backend (la que crea seed_demo.py).
let operacionActual = null;

async function resolverOperacionActual() {
  if (operacionActual) return operacionActual;
  const ops = await (await fetch(`${BACKEND_URL}/operaciones`)).json();
  if (!ops.length) throw new Error("no hay ninguna operación creada — correr seed_demo.py primero");
  const operacion = ops[0];
  const mandato = await (await fetch(`${BACKEND_URL}/operaciones/${operacion.id}/mandato`)).json();
  operacionActual = { operacion, mandato };
  return operacionActual;
}

// ===== PUNTO DE INTEGRACIÓN: tool calls (guardrail + record_commitment van acá) =====
export async function onToolCall(name, args) {
  console.log("[tool]", name, args);

  if (name === "get_time") return { time: new Date().toISOString() };

  if (name === "get_operacion_actual") {
    try {
      const { operacion } = await resolverOperacionActual();
      return {
        cliente: operacion.cliente,
        contenedor_id: operacion.contenedor_id,
        puerto_origen: operacion.puerto_origen,
        destino: operacion.destino,
        eta: operacion.eta,
      };
    } catch (e) {
      // Sin operación seedeada (seed_demo.py no corrió) no hay nada que
      // devolver — que Volta lo sepa y reaccione, en vez de que se rompa
      // la llamada entera por una excepción sin capturar.
      return { error: "no hay ninguna operación cargada todavía" };
    }
  }

  if (name === "find_carriers") {
    const { operacion } = await resolverOperacionActual();
    const params = new URLSearchParams({ puerto: operacion.puerto_origen });
    if (args.max_distancia_km != null) params.set("max_distancia_km", args.max_distancia_km);
    if (args.limite != null) params.set("limite", args.limite);
    const candidatos = await (await fetch(`${BACKEND_URL}/transportistas?${params}`)).json();
    return { candidatos };
  }

  if (name === "check_mandato") {
    const { operacion } = await resolverOperacionActual();
    // refresca el mandato por si se revocó desde que arrancó la llamada
    const fresco = await (await fetch(`${BACKEND_URL}/operaciones/${operacion.id}/mandato`)).json();
    return {
      tope_precio: fresco.tope_precio,
      ventana_inicio: fresco.ventana_inicio,
      ventana_fin: fresco.ventana_fin,
      revocado: fresco.revocado,
      vigente_hasta: fresco.vigente_hasta,
    };
  }

  if (name === "request_quote") {
    const { operacion } = await resolverOperacionActual();
    await fetch(`${BACKEND_URL}/cotizaciones`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operacion_id: operacion.id,
        call_id: "call-" + Date.now(),
        contraparte: args.contraparte,
        monto: args.monto,
        fecha_retiro: args.fecha_retiro,
        detalle: args.detalle ?? "",
      }),
    });
    return { registrada: true };
  }

  if (name === "cancel_commitment") {
    const { operacion } = await resolverOperacionActual();
    const commitments = await (await fetch(`${BACKEND_URL}/operaciones/${operacion.id}/commitments`)).json();
    const vigente = commitments.find((c) => c.tipo === "reserva" && c.aprobado && !c.cancelado);
    if (!vigente) return { error: "no hay ninguna reserva vigente para cancelar" };
    const res = await fetch(`${BACKEND_URL}/commitments/${vigente.id}/cancelar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ motivo: args.motivo ?? "" }),
    });
    const data = await res.json();
    return { cancelado: true, era: { contraparte: data.contraparte, monto: data.monto } };
  }

  if (name === "record_commitment") {
    const { operacion, mandato } = await resolverOperacionActual();
    const res = await fetch(`${BACKEND_URL}/commitments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operacion_id: operacion.id,
        mandato_id: mandato.id,
        call_id: "call-" + Date.now(), // reemplazar por el call_id real de la sesión cuando exista
        contraparte: args.contraparte,
        tipo: args.tipo,
        monto: args.monto,
        fecha_retiro: args.fecha_retiro,
        detalle: args.detalle ?? "",
      }),
    });
    const data = await res.json();
    // esto es lo que el modelo va a "leer" como resultado de la tool —
    // si aprobado=false, Volta tiene que decirle a la contraparte que
    // no puede cerrar eso, nunca confirmar igual.
    return { aprobado: data.aprobado, motivo: data.motivo };
  }

  if (name === "escalate_to_human") {
    motivoEscalacion = args.motivo || "";
    esperandoFraseDeTraspaso = true;
    return {
      ok: true,
      instruccion:
        "Decile a la contraparte, en UNA sola frase, que la pasás con una persona del equipo. Nada más.",
    };
  }

  if (name === "end_call") {
    motivoFinLlamada = args.motivo || "";
    esperandoFraseDeCierre = true;
    console.log("[end_call]", motivoFinLlamada);
    return {
      ok: true,
      instruccion:
        "Decile a la contraparte, en UNA sola frase breve y cordial, que listo, gracias, y que cortás. Nada más — no reabras el tema.",
    };
  }

  return { error: `tool desconocida: ${name}` };
}

// Simulamos una llamada ENTRANTE: Volta ya tiene un mandato y nos llama
// para arrancar la negociación — el botón dice "Atender llamada", no
// "Conectar". En WebRTC no existe un "quién marcó a quién" real (la
// telefonía está 100% mockeada, per Docs/DECISIONS.md), así que lo que
// hacemos es forzar a que Volta hable primero apenas el canal de datos
// abre, en vez de esperar a que hablemos nosotros.
//
// OJO con esto: `response.create` con un `instructions` propio NO se
// SUMA al prompt de sesión (el fat prompt de Sofía) — lo REEMPLAZA para
// esa respuesta puntual. La primera versión de esta función le pasaba
// ahí mismo el saludo completo, y el resultado era exactamente el bug
// que encontró Lucas: esa respuesta usaba solo mi texto corto, no las
// ~660 líneas de reglas de Sofía (evaluación de mandato, máquina de
// estados, etc.) — Volta "olvidaba" su propio prompt en ese turno.
//
// La solución es no usar `instructions` para el saludo en sí. En vez de
// eso, esta primera respuesta NO habla — solo le pide a Volta que llame
// a sus propias tools (get_operacion_actual, find_carriers, check_mandato)
// para levantar el contexto real. Recién la respuesta SIGUIENTE (la que
// sale después de esos resultados, ver el loop de tool calls más abajo en
// handleEvent) es la que efectivamente saluda — y esa sí se genera con
// `response.create` sin ningún override, o sea con el fat prompt entero
// disponible, tal como cualquier otra respuesta de la llamada.
function saludarInicial() {
  dc.send(JSON.stringify({
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
  }));
}

function armLatencyProbe() {
  if (escalado) return;
  userStoppedAt = performance.now();
  if (latencyRAF || !analyser) return;
  const tick = () => {
    if (escalado) { latencyRAF = null; return; }
    analyser.getByteTimeDomainData(analyserData);
    let peak = 0;
    for (let i = 0; i < analyserData.length; i++) {
      const v = Math.abs(analyserData[i] - 128);
      if (v > peak) peak = v;
    }
    if (peak > 4) {
      turn++;
      console.log(`[latency] turno ${turn}: ${Math.round(performance.now() - userStoppedAt)}ms`);
      latencyRAF = null;
      userStoppedAt = null;
      return;
    }
    latencyRAF = requestAnimationFrame(tick);
  };
  latencyRAF = requestAnimationFrame(tick);
}

function setTurnDetection(activo) {
  dc.send(JSON.stringify({
    type: "session.update",
    session: {
      type: "realtime",
      audio: {
        input: {
          transcription: { model: "gpt-live-transcribe" },
          turn_detection: {
            type: "semantic_vad",
            create_response: activo,
            interrupt_response: activo,
          },
        },
      },
    },
  }));
}

function entrarEnEscalacion() {
  escalado = true;
  setTurnDetection(false);
  dc.send(JSON.stringify({
    type: "response.create",
    response: {
      conversation: "none",
      metadata: { topic: "resumen_escalacion" },
      output_modalities: ["text"],
      instructions:
        "Resumí la llamada hasta ahora para el humano del equipo que la está por tomar. " +
        "Máximo 6 líneas, sin saludos: con quién se está hablando, qué pidió, qué se ofreció, " +
        "dónde está el desacuerdo, y qué falta cerrar.",
    },
  }));
  setStatus("ESCALADO — Volta escucha, hablá vos");
  btn("escalar").disabled = true;
  btn("devolver").disabled = false;
  console.log("[escalacion] inicio. motivo:", motivoEscalacion);
}

function volverAVolta() {
  escalado = false;
  setTurnDetection(true);
  dc.send(JSON.stringify({
    type: "response.create",
    response: {
      instructions:
        "La conversación la tomó un humano de tu equipo y ya terminó. En base a TODO lo que " +
        "escuchaste durante ese tramo, registrá el commitment que se haya acordado. " +
        "Si no se acordó nada concreto, decilo en una frase corta y no registres nada.",
    },
  }));
  setStatus("en llamada");
  btn("escalar").disabled = false;
  btn("devolver").disabled = true;
  console.log("[escalacion] fin, vuelve Volta");
}

function escalarManual() {
  motivoEscalacion = "escalación manual desde el panel";
  esperandoFraseDeTraspaso = true;
  dc.send(JSON.stringify({
    type: "response.create",
    response: {
      instructions:
        "Decile a la contraparte, en UNA sola frase, que la pasás con una persona del equipo. Nada más.",
    },
  }));
}

function mostrarResumen(texto) {
  btn("resumen").textContent = texto;
  console.log("[resumen para el humano]\n" + texto);
  onTranscript("resumen", texto);
}

async function handleEvent(ev) {
  if (ev.type === "input_audio_buffer.speech_stopped") armLatencyProbe();

  if (ev.type === "conversation.item.input_audio_transcription.completed") {
    console.log(escalado ? "[user/escalado]" : "[user]", ev.transcript);
    onTranscript("user", ev.transcript);
  }

  if (ev.type === "response.output_audio_transcript.done") {
    console.log("[agent]", ev.transcript);
    onTranscript("agent", ev.transcript);
  }

  if (ev.type === "response.done") {
    if (ev.response.metadata?.topic === "resumen_escalacion") {
      const parte = (ev.response.output?.[0]?.content ?? []).find((c) => c.type === "output_text");
      mostrarResumen(parte?.text ?? "(sin resumen)");
      return;
    }

    // Un mismo response.output puede traer VARIOS function_call (ej. Volta
    // pidiendo check_mandato y find_carriers juntos) — hay que despachar
    // los resultados de todos antes de pedir la respuesta siguiente. Antes
    // esto mandaba un response.create POR CADA tool call dentro del mismo
    // loop, y la Realtime API solo permite una respuesta activa a la vez:
    // el segundo response.create llegaba mientras el primero todavía
    // estaba en curso y volvía el error "conversation_already_has_active_response".
    let huboToolCall = false;
    for (const item of ev.response.output ?? []) {
      if (item.type !== "function_call") continue;
      huboToolCall = true;
      const result = await onToolCall(item.name, JSON.parse(item.arguments || "{}"));
      dc.send(JSON.stringify({
        type: "conversation.item.create",
        item: { type: "function_call_output", call_id: item.call_id, output: JSON.stringify(result) },
      }));
    }
    if (huboToolCall) {
      dc.send(JSON.stringify({ type: "response.create" }));
    }

    if (esperandoFraseDeTraspaso && !huboToolCall) {
      esperandoFraseDeTraspaso = false;
      entrarEnEscalacion();
    }

    if (esperandoFraseDeCierre && !huboToolCall) {
      esperandoFraseDeCierre = false;
      setStatus("cortando — la llamada no servía (" + motivoFinLlamada + ")");
      // Le damos un momento a la frase de cierre para que termine de
      // reproducirse antes de cortar de verdad — no hay (todavía) un
      // evento del lado del cliente que avise "el audio ya terminó de
      // sonar", así que esto es un heurístico corto, no una garantía.
      setTimeout(() => hangup(), 2500);
    }
  }

  if (ev.type === "error") console.error("[realtime error]", ev.error);
}

async function connect() {
  setStatus("atendiendo...");
  try {
    const key = (await (await fetch("/session", { method: "POST" })).json()).value;

    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    pc = new RTCPeerConnection();

    audioEl = document.createElement("audio");
    audioEl.autoplay = true;
    pc.ontrack = (e) => {
      audioEl.srcObject = e.streams[0];
      const ctx = new AudioContext();
      analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      analyserData = new Uint8Array(analyser.fftSize);
      ctx.createMediaStreamSource(e.streams[0]).connect(analyser);
    };

    pc.addTrack(micStream.getTracks()[0]);

    dc = pc.createDataChannel("oai-events");
    dc.addEventListener("message", (e) => handleEvent(JSON.parse(e.data)));
    dc.addEventListener("open", () => {
      setStatus("en llamada");
      btn("escalar").disabled = false;
      saludarInicial();
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    const sdp = await fetch("https://api.openai.com/v1/realtime/calls", {
      method: "POST",
      body: offer.sdp,
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/sdp" },
    }).then((r) => r.text());

    await pc.setRemoteDescription({ type: "answer", sdp });
    // el estado pasa a "en llamada" y se dispara el saludo cuando el canal
    // de datos abre de verdad (evento "open" de arriba), no acá — todavía
    // puede faltar un instante de negociación ICE/DTLS en este punto.
  } catch (e) {
    console.error(e);
    setStatus("error: " + e.message);
  }
}

function hangup() {
  if (latencyRAF) cancelAnimationFrame(latencyRAF);
  latencyRAF = null;
  pc?.close();
  micStream?.getTracks().forEach((t) => t.stop());
  pc = dc = analyser = null;
  escalado = false;
  esperandoFraseDeTraspaso = false;
  setStatus("sonando — Volta te está llamando");
  btn("escalar").disabled = true;
  btn("devolver").disabled = true;
}

function interrupt() {
  dc?.send(JSON.stringify({ type: "response.cancel" }));
  console.log("[barge-in] response.cancel enviado");
}

btn("connect").onclick = connect;
btn("hangup").onclick = hangup;
btn("interrupt").onclick = interrupt;
btn("escalar").onclick = escalarManual;
btn("devolver").onclick = volverAVolta;

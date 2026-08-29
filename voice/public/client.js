let pc, dc, micStream, audioEl;
let turn = 0;
let userStoppedAt = null;
let analyser, analyserData, latencyRAF = null;

const statusEl = () => document.getElementById("status");
const setStatus = (s) => (statusEl().textContent = s);

// ===== PUNTO DE INTEGRACIÓN: transcripción =====
export function onTranscript(role, text) {}

// ===== PUNTO DE INTEGRACIÓN: tool calls (guardrail + record_commitment van acá) =====
export async function onToolCall(name, args) {
  console.log("[tool]", name, args);
  if (name === "get_time") return { time: new Date().toISOString() };
  return { error: `tool desconocida: ${name}` };
}

function armLatencyProbe() {
  userStoppedAt = performance.now();
  if (latencyRAF || !analyser) return;
  const tick = () => {
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

async function handleEvent(ev) {
  if (ev.type === "input_audio_buffer.speech_stopped") armLatencyProbe();

  if (ev.type === "conversation.item.input_audio_transcription.completed") {
    console.log("[user]", ev.transcript);
    onTranscript("user", ev.transcript);
  }

  if (ev.type === "response.output_audio_transcript.done") {
    console.log("[agent]", ev.transcript);
    onTranscript("agent", ev.transcript);
  }

  if (ev.type === "response.done") {
    for (const item of ev.response.output ?? []) {
      if (item.type !== "function_call") continue;
      const result = await onToolCall(item.name, JSON.parse(item.arguments || "{}"));
      dc.send(JSON.stringify({
        type: "conversation.item.create",
        item: { type: "function_call_output", call_id: item.call_id, output: JSON.stringify(result) },
      }));
      dc.send(JSON.stringify({ type: "response.create" }));
    }
  }

  if (ev.type === "error") console.error("[realtime error]", ev.error);
}

async function connect() {
  setStatus("conectando...");
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

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    const sdp = await fetch("https://api.openai.com/v1/realtime/calls", {
      method: "POST",
      body: offer.sdp,
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/sdp" },
    }).then((r) => r.text());

    await pc.setRemoteDescription({ type: "answer", sdp });
    setStatus("conectado");
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
  setStatus("desconectado");
}

function interrupt() {
  dc?.send(JSON.stringify({ type: "response.cancel" }));
  console.log("[barge-in] response.cancel enviado");
}

document.getElementById("connect").onclick = connect;
document.getElementById("hangup").onclick = hangup;
document.getElementById("interrupt").onclick = interrupt;

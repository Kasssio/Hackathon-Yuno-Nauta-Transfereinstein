// Puente de audio del operador humano con el transportista — la contraparte
// de conectarConOperador() en client.js. Esta pestaña NO habla con OpenAI en
// absoluto: es una RTCPeerConnection directa contra la pestaña del
// transportista, señalizada por el mismo server de voz (WebSocket /panel,
// acá con ?rol=operador para que server.ts sepa reenviar los mensajes al
// otro lado en vez de tratarlos como transcripción/control de la llamada).
//
// La abre el dashboard con window.open() al apretar "Atender llamada" en
// Modo Resolución — ver controlLlamadaReal() en dashboard/index.html.

const statusEl = document.getElementById("status");
const setStatus = (s) => { statusEl.textContent = s; actualizarOrbe(s); };
const orbe = document.getElementById("orbe");
const btnConectar = document.getElementById("conectar");
const btnVolver = document.getElementById("volver");

function actualizarOrbe(s) {
  const t = (s || "").toLowerCase();
  orbe.classList.remove("orbe--live", "orbe--esperando");
  if (t.includes("hablá") || t.includes("conectado con")) orbe.classList.add("orbe--live");
  else if (t.includes("esperando") || t.includes("pidiendo")) orbe.classList.add("orbe--esperando");
}

// Necesario para que este navegador y el del transportista se encuentren
// cuando están en redes distintas (dos NATs separados) — ver el mismo
// comentario en client.js, junto a conectarConOperador().
const ICE_SERVERS = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
  ],
};

let ws = null;
let pc = null;
let micStream = null;
let audioEl = null;

function abrirWs() {
  ws = new WebSocket(`ws://${location.host}/panel?rol=operador`);
  ws.addEventListener("message", async (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch { return; }
    if (data.type === "webrtc-offer" && pc) {
      try {
        await pc.setRemoteDescription({ type: "offer", sdp: data.sdp });
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        ws.send(JSON.stringify({ type: "webrtc-answer", sdp: answer.sdp }));
      } catch (err) { console.error("[operador] no se pudo responder la oferta", err); }
    } else if (data.type === "webrtc-ice" && data.candidate && pc) {
      pc.addIceCandidate(data.candidate).catch((err) => console.error("[operador] ICE", err));
    } else if (data.type === "volver_a_volta") {
      // Alguien devolvió la llamada desde OTRO lado (el botón del dashboard,
      // o el propio transportista) — cerramos acá también.
      setStatus("Volta retomó la conversación");
      colgar();
    }
  });
  ws.addEventListener("close", () => {
    if (pc) setStatus("se perdió la conexión con el server de voz");
  });
}

async function conectar() {
  btnConectar.disabled = true;
  setStatus("pidiendo micrófono…");
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    console.error(e);
    setStatus("error de micrófono: " + e.message);
    btnConectar.disabled = false;
    return;
  }

  const miTrack = micStream.getTracks()[0];
  console.log("[operador] mi mic:", miTrack.readyState, "| enabled:", miTrack.enabled, "| muted:", miTrack.muted);
  pc = new RTCPeerConnection(ICE_SERVERS);
  pc.addTrack(miTrack);
  audioEl = document.createElement("audio");
  audioEl.autoplay = true;
  pc.ontrack = (e) => {
    console.log("[operador] track remoto recibido:", e.track.kind, "| muted:", e.track.muted, "| streams:", e.streams.length);
    audioEl.srcObject = e.streams[0];
    audioEl.play().catch((err) => console.error("[operador] audio.play() bloqueado:", err));
  };
  pc.onicecandidate = (e) => {
    if (e.candidate && ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "webrtc-ice", candidate: e.candidate }));
    }
  };
  pc.onconnectionstatechange = () => {
    console.log("[operador] conexión:", pc?.connectionState);
    if (pc?.connectionState === "connected") setStatus("conectado con el transportista — hablá");
    if (pc && ["failed", "disconnected"].includes(pc.connectionState)) setStatus("se cortó la conexión de audio");
  };

  abrirWs();
  setStatus("esperando al transportista…");
  btnVolver.disabled = false;
}

function colgar() {
  pc?.close();
  pc = null;
  micStream?.getTracks().forEach((t) => t.stop());
  micStream = null;
  ws?.close();
  ws = null;
  btnConectar.disabled = false;
  btnVolver.disabled = true;
}

btnConectar.onclick = conectar;
btnVolver.onclick = async () => {
  btnVolver.disabled = true;
  try { await fetch("/call/return", { method: "POST" }); } catch (e) { /* server de voz abajo */ }
  colgar();
  setStatus("devolviste la llamada a Volta");
};

// Las mismas tools que public/client.js, del lado del server, para las
// llamadas por teléfono (Twilio + SIP). La lógica es idéntica: lo único
// que cambia es que acá no hay browser.
//
// ===== PUNTO DE INTEGRACIÓN: tool calls (guardrail + record_commitment) =====

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export function crearManejadorDeTools(callId: string, alEscalar?: (motivo: string) => void) {
  let operacionActual: any = null;
  let candidatoActual: any = null;
  let candidatosRestantes: number | null = null;
  const cotizacionesRegistradas: { contraparte: string; monto: number }[] = [];

  function mejorAlternativaMonto() {
    const otras = cotizacionesRegistradas.filter((c) => c.contraparte !== candidatoActual?.nombre);
    return otras.length ? Math.min(...otras.map((c) => c.monto)) : null;
  }

  async function resolverOperacionActual() {
    if (operacionActual) return operacionActual;
    const ops = await (await fetch(`${BACKEND_URL}/operaciones`)).json();
    if (!ops.length) throw new Error("no hay ninguna operación creada");
    const operacion = ops[0];
    const mandato = await (await fetch(`${BACKEND_URL}/operaciones/${operacion.id}/mandato`)).json();
    operacionActual = { operacion, mandato };
    return operacionActual;
  }

  return async function onToolCall(name: string, args: any) {
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
      } catch {
        return { error: "no hay ninguna operación cargada todavía" };
      }
    }

    if (name === "find_carriers") {
      const { operacion } = await resolverOperacionActual();
      const params = new URLSearchParams({ puerto: operacion.puerto_origen });
      if (args.max_distancia_km != null) params.set("max_distancia_km", args.max_distancia_km);
      if (args.limite != null) params.set("limite", args.limite);
      const candidatos = await (await fetch(`${BACKEND_URL}/transportistas?${params}`)).json();
      if (!candidatoActual && candidatos.length) {
        candidatoActual = { id: candidatos[0].id, nombre: candidatos[0].nombre };
        candidatosRestantes = Math.max(0, candidatos.length - 1);
      }
      return { candidatos };
    }

    if (name === "check_mandato") {
      const { operacion } = await resolverOperacionActual();
      const fresco = await (await fetch(`${BACKEND_URL}/operaciones/${operacion.id}/mandato`)).json();
      return {
        tope_precio: fresco.tope_precio,
        ventana_inicio: fresco.ventana_inicio,
        ventana_fin: fresco.ventana_fin,
        horario_inicio: fresco.horario_inicio ?? null,
        horario_fin: fresco.horario_fin ?? null,
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
          call_id: callId,
          contraparte: args.contraparte,
          monto: args.monto,
          fecha_retiro: args.fecha_retiro,
          hora_retiro: args.hora_retiro ?? null,
          detalle: args.detalle ?? "",
        }),
      });
      cotizacionesRegistradas.push({ contraparte: args.contraparte, monto: args.monto });
      return { registrada: true };
    }

    if (name === "evaluar_negociacion") {
      const { operacion } = await resolverOperacionActual();
      const res = await fetch(`${BACKEND_URL}/negociacion/evaluar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operacion_id: operacion.id,
          call_id: callId,
          contraparte: candidatoActual?.nombre ?? "",
          candidato_id: candidatoActual?.id ?? null,
          tipo_respuesta: args.tipo_respuesta,
          monto: args.monto,
          variable_condicion: args.variable_condicion,
          condicion_propuesta: args.condicion_propuesta,
          candidatos_restantes: candidatosRestantes,
          mejor_alternativa_monto: mejorAlternativaMonto(),
        }),
      });
      if (!res.ok) {
        const detalle: any = await res.json().catch(() => ({}));
        return { error: detalle.detail ?? "no se pudo evaluar la negociación" };
      }
      return await res.json();
    }

    if (name === "cancel_commitment") {
      const { operacion } = await resolverOperacionActual();
      const commitments = await (await fetch(`${BACKEND_URL}/operaciones/${operacion.id}/commitments`)).json();
      const vigente = commitments.find((c: any) => c.tipo === "reserva" && c.aprobado && !c.cancelado);
      if (!vigente) return { error: "no hay ninguna reserva vigente para cancelar" };
      const res = await fetch(`${BACKEND_URL}/commitments/${vigente.id}/cancelar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ motivo: args.motivo ?? "" }),
      });
      const data: any = await res.json();
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
          call_id: callId,
          contraparte: args.contraparte,
          tipo: args.tipo,
          monto: args.monto,
          fecha_retiro: args.fecha_retiro,
          hora_retiro: args.hora_retiro,
          detalle: args.detalle ?? "",
        }),
      });
      const data: any = await res.json();
      return { aprobado: data.aprobado, motivo: data.motivo };
    }

    if (name === "escalate_to_human") {
      console.log("[escalacion]", args.motivo);
      alEscalar?.(args.motivo || "");
      return {
        ok: true,
        instruccion:
          "Decile a la contraparte, en UNA sola frase, que la pasás con una persona del equipo. Nada más.",
      };
    }

    if (name === "end_call") {
      console.log("[end_call]", args.motivo);
      return {
        ok: true,
        instruccion:
          "Decile a la contraparte, en UNA sola frase breve y cordial, que listo, gracias, y que cortás. Nada más — no reabras el tema.",
      };
    }

    return { error: `tool desconocida: ${name}` };
  };
}

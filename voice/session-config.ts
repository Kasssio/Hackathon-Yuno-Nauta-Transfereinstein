export const sessionConfig = {
  instructions: `Sos Volta, un agente de voz que coordina transporte terrestre de contenedores por teléfono.
Hablás español rioplatense neutro, claro y breve. Frases cortas, tono de operador logístico.
Confirmás en voz alta los datos clave (monto, fecha, contraparte) antes de darlos por acordados.
Si te interrumpen, parás y escuchás.
Cuando negociás con más de un transportista: usá request_quote para anotar cada oferta que
te den, SIN comprometerte. Recién cuando compares y elijas la mejor opción, cerrala con
record_commitment. Nunca llames record_commitment por cada oferta — solo por la ganadora.
Si ya cerraste con un transportista y después otro te ofrece algo mejor dentro del mandato:
llamá a cancel_commitment (explicando el motivo), avisale al primero en la llamada que
corresponda que ya no sigue en pie, y recién ahí cerrá con record_commitment el nuevo trato.
Nunca dejes dos reservas vigentes al mismo tiempo para la misma operación.
Antes de arrancar la ronda de llamadas salientes, usá find_carriers con limite: 3 para saber a quién llamar — te da los 3 mejores transportistas para el puerto de esta operación (no todos los que hay, pueden ser más de 10), elegidos por un puntaje que combina cercanía, cuánto suelen negociar, su puntualidad y sus tasas de aceptación (tasa_aceptacion_general y tasa_aceptacion_corto_plazo, 0 a 1). Negociá con esos 3, en orden. Priorizá negociar más con los que tienen disposicion_a_negociar alta, tené en cuenta la puntualidad al elegir entre ofertas parecidas, y si la ventana del mandato es ajustada (pocos días de anticipación), priorizá al que tenga tasa_aceptacion_corto_plazo más alta — te ahorra llamadas que probablemente terminen en rechazo.`,
// TODO (Sofía): esto es un piso mínimo para que la tool se use bien — el resto del
// prompt de negociación (cómo pedir precio, cómo comparar, tono ante objeciones) es tuyo.

  voice: "marin",

  tools: [
    {
      type: "function",
      name: "find_carriers",
      description: "Devuelve la lista de transportistas candidatos para el puerto de esta operación. Incluye disposicion_a_negociar y puntualidad (1-5), y tasa_aceptacion_general y tasa_aceptacion_corto_plazo (0-1, esta última es la tasa de aceptación cuando se pide con pocos días de anticipación) de cada uno. Usá limite para no recibir una lista larga de un mismo puerto: con limite, deja de ordenar por cercanía y devuelve los mejores N por un puntaje combinado (distancia + disposición a negociar + puntualidad + las dos tasas de aceptación) — para una negociación en vivo, pedí limite: 3. Llamala al arrancar, antes de la ronda de llamadas salientes.",
      parameters: {
        type: "object",
        properties: {
          max_distancia_km: {
            type: "number",
            description: "Si se pasa, descarta transportistas a más de esta distancia del puerto (en km). Opcional — dejalo afuera si no hace falta filtrar por distancia.",
          },
          limite: {
            type: "number",
            description: "Cuántos candidatos como máximo querés recibir, elegidos por el mejor puntaje combinado (no solo por cercanía). Usá esto para acotar la ronda de negociación, ej. limite: 3.",
          },
        },
        required: [],
      },
    },
    {
      type: "function",
      name: "get_time",
      description: "Devuelve la hora actual. Usala si el usuario pregunta la hora.",
      parameters: {
        type: "object",
        properties: {},
        required: [],
      },
    },
    {
      type: "function",
      name: "check_mandato",
      description: "Consulta el mandato vigente antes de negociar o cerrar un acuerdo. Llamala al arrancar la llamada y de nuevo antes de cualquier record_commitment, porque el mandato puede haber sido revocado en el medio.",
      parameters: { type: "object", properties: {}, required: [] },
    },
    {
      type: "function",
      name: "request_quote",
      description: "Registra una cotización recibida de un transportista, SIN comprometerse todavía. Usala para cada oferta que te den al negociar con varios transportistas, antes de elegir la mejor — no corre el guardrail de mandato, es solo para poder comparar. Recién cuando elijas con quién cerrar, llamá a record_commitment con esos datos.",
      parameters: {
        type: "object",
        properties: {
          contraparte: { type: "string", description: "Nombre del transportista" },
          monto: { type: "number", description: "Monto cotizado, en MXN" },
          fecha_retiro: { type: "string", description: "Fecha de retiro ofrecida, formato YYYY-MM-DD" },
          detalle: { type: "string", description: "Breve descripción de la oferta" },
        },
        required: ["contraparte", "monto", "fecha_retiro"],
      },
    },
    {
      type: "function",
      name: "cancel_commitment",
      description: "Cancela el commitment vigente de esta operación (la reserva actual) porque apareció una mejor oferta con otro transportista y decidiste cambiar. Llamala ANTES de cerrar el nuevo trato con record_commitment — nunca dejes dos reservas vigentes a la vez.",
      parameters: {
        type: "object",
        properties: {
          motivo: { type: "string", description: "Por qué se cancela, ej. 'apareció una oferta mejor con Transportes Express'" },
        },
        required: ["motivo"],
      },
    },
    {
      type: "function",
      name: "record_commitment",
      description: "Registra un acuerdo cerrado en la llamada (reserva de camión, reprogramación, u otro). Se valida contra el mandato vigente antes de confirmarse — puede volver rechazado, en cuyo caso hay que avisarle a la contraparte y no dar el trato por cerrado.",
      parameters: {
        type: "object",
        properties: {
          tipo: { type: "string", enum: ["reserva", "reprogramacion", "otro"] },
          contraparte: { type: "string", description: "Nombre del transportista o chofer" },
          monto: { type: "number", description: "Monto acordado, en MXN" },
          fecha_retiro: { type: "string", description: "Fecha del retiro, formato YYYY-MM-DD" },
          detalle: { type: "string", description: "Breve descripción de lo acordado" },
        },
        required: ["tipo", "contraparte", "monto", "fecha_retiro"],
      },
    },
  ],
};


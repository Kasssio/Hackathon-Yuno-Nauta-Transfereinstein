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
Antes de arrancar la ronda de llamadas salientes, usá find_carriers para saber a quién llamar — te da la lista de transportistas que sirven el puerto de esta operación, ordenada por cercanía, con cuánto suelen negociar y su puntualidad. Priorizá negociar más con los que tienen disposicion_a_negociar alta, y tené en cuenta la puntualidad al elegir entre ofertas parecidas — un precio un poco más alto con mejor puntualidad puede ser la mejor opción.

Escalás a un humano con escalate_to_human cuando: te piden algo fuera de tu mandato y el
interlocutor insiste, te piden hablar con una persona, detectás una contradicción que no
podés resolver, o te presionan con urgencia para saltarte una regla. Escalar no es fallar.`,
// TODO (Sofía): esto es un piso mínimo para que la tool se use bien — el resto del
// prompt de negociación (cómo pedir precio, cómo comparar, tono ante objeciones) es tuyo.

  voice: "marin",

  tools: [
    {
      type: "function",
      name: "find_carriers",
      description: "Devuelve la lista de transportistas candidatos para el puerto de esta operación, ordenados por cercanía al puerto — así sabés a quién llamar primero. Incluye disposicion_a_negociar y puntualidad (1-5) de cada uno para priorizar con quién negociar de más. Llamala al arrancar, antes de la ronda de llamadas salientes.",
      parameters: {
        type: "object",
        properties: {
          max_distancia_km: {
            type: "number",
            description: "Si se pasa, descarta transportistas a más de esta distancia del puerto (en km). Opcional — dejalo afuera si no hace falta filtrar por distancia.",
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
    {
      type: "function",
      name: "escalate_to_human",
      description:
        "Pasa la llamada en curso a un humano del equipo, sin cortar. Usala cuando el pedido " +
        "queda fuera de tu mandato y el interlocutor insiste, cuando te piden hablar con una " +
        "persona, o cuando detectás una contradicción que no podés resolver.",
      parameters: {
        type: "object",
        properties: {
          motivo: {
            type: "string",
            description: "Por qué escalás, en una frase corta. Queda en el trail auditable.",
          },
        },
        required: ["motivo"],
      },
    },
  ],
};

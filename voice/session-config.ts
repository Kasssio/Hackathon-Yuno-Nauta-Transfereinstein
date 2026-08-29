export const sessionConfig = {
  instructions: `Sos Volta, un agente de voz que coordina transporte terrestre de contenedores por teléfono.
Hablás español rioplatense neutro, claro y breve. Frases cortas, tono de operador logístico.
Confirmás en voz alta los datos clave (monto, fecha, contraparte) antes de darlos por acordados.
Si te interrumpen, parás y escuchás.`,

  voice: "marin",

  tools: [
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
  ],
};

# Contrato de tools para Volta — backend ↔ agente

Para que Sofía y Marcos no tengan que inventar el formato hablando
conmigo por chat: acá están las dos tools listas para pegar en
`voice/session-config.ts`, y la implementación de `onToolCall` lista
para pegar en `voice/public/client.js`. Pegar y probar — si algo no
encaja, es más rápido avisarme que yo diga bien el formato de nuevo.

Principio de diseño: **el modelo nunca maneja ids técnicos**
(`operacion_id`, `mandato_id`, `call_id`) — eso lo completa el código
del cliente, no el LLM. Así se reduce el riesgo de que alucine un id
que no existe. El modelo solo produce los datos de negocio (monto,
fecha, contraparte).

## 1. Tools para `session-config.ts`

**Actualizado:** la consigna original del challenge pide explícitamente
*"several negotiations, one best choice"* — Volta tiene que poder
cotizar con varios transportistas y recién comprometerse con el
mejor. Por eso son 3 tools, no 2: `request_quote` (cotizar, sin
comprometerse) es un paso previo y separado de `record_commitment`
(cerrar). **Importante:** no uses `record_commitment` para "anotar"
cada oferta que te dan — el guardrail rechaza una segunda reserva para
la misma operación (es la defensa contra partir la compra), así que
si lo usás para cotizar en vez de cerrar, la segunda cotización se va
a rechazar como si fuera un error, cuando en realidad el guardrail
está haciendo lo correcto ante un uso incorrecto de la tool.

Agregar estos tres objetos al array `tools`, junto al de `get_time`:

```ts
{
  type: "function",
  name: "check_mandato",
  description: "Consulta el mandato vigente antes de negociar o cerrar un acuerdo. Llamala al arrancar la llamada y de nuevo antes de cualquier record_commitment, porque el mandato puede haber sido revocado en el medio.",
  parameters: { type: "object", properties: {}, required: [] },
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
```

Y antes de `record_commitment` en el array (el orden en el doc no
importa, pero así queda agrupado con su explicación):

```ts
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
```

## 2. Implementación para `client.js`

Reemplaza el `onToolCall` de prueba (el que solo maneja `get_time`) por
esto — mantiene `get_time` y suma las dos tools nuevas:

```js
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

export async function onToolCall(name, args) {
  console.log("[tool]", name, args);

  if (name === "get_time") return { time: new Date().toISOString() };

  if (name === "check_mandato") {
    const { operacion, mandato } = await resolverOperacionActual();
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

  return { error: `tool desconocida: ${name}` };
}
```

## 3. Reconsideración: cancelar un commitment por una oferta mejor

Si Volta ya cerró con un transportista y otro le ofrece algo mejor
dentro del mandato, **primero cancela, después cierra el nuevo** —
nunca puede haber dos reservas vigentes para la misma operación (el
guardrail lo bloquea a propósito). Tool + endpoint:

```ts
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
```

```js
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
```

Un commitment cancelado se guarda con `cancelado: true` — nunca se
borra, así el trail auditable y el decision log pueden mostrar la
historia completa (cerró con A, encontró algo mejor, canceló A,
cerró con B).

## 4. A quién llama Volta: `find_carriers`

Resuelve el problema de "con quién negocio" antes de arrancar la
ronda de llamadas salientes. Hay un catálogo ficticio de 30
transportistas en `backend/app/carriers_data.py` (puerto que
atienden, ubicación, disposición a negociar 1-5, puntualidad 1-5,
tarifa de referencia, y dos tasas de aceptación 0-1: general y a
corto plazo, ver más abajo) — `find_carriers` devuelve los candidatos
para el puerto de la operación actual, ordenados por cercanía. El
puerto sale de `operacion.puerto_origen`, no lo tiene que decir el
modelo (mismo principio: nada de ids ni datos que el cliente ya sabe).

Las dos tasas de aceptación miden cosas distintas: `tasa_aceptacion_general`
es qué tan seguido el transportista dice que sí a tomar el trabajo, y
`tasa_aceptacion_corto_plazo` es lo mismo pero pidiéndole con pocos
días de anticipación — un transportista puede ser rígido para
negociar precio y aun así aceptar casi siempre si le avisan con
tiempo, o viceversa. Por diseño del fixture, la segunda nunca es
mayor que la primera. Sirve para que Volta priorice a quién llamar
primero cuando la ventana del mandato está ajustada.

```ts
{
  type: "function",
  name: "find_carriers",
  description: "Devuelve la lista de transportistas candidatos para el puerto de esta operación. Incluye disposicion_a_negociar y puntualidad (1-5), y tasa_aceptacion_general y tasa_aceptacion_corto_plazo (0-1, esta última es la tasa de aceptación cuando se pide con pocos días de anticipación) de cada uno. Usá limite para no recibir una lista larga de un mismo puerto: con limite, deja de ordenar por cercanía y devuelve los mejores N por un puntaje combinado — para una negociación en vivo, pedí limite: 3. Llamala al arrancar, antes de la ronda de llamadas salientes.",
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
```

```js
if (name === "find_carriers") {
  const { operacion } = await resolverOperacionActual();
  const params = new URLSearchParams({ puerto: operacion.puerto_origen });
  if (args.max_distancia_km != null) params.set("max_distancia_km", args.max_distancia_km);
  if (args.limite != null) params.set("limite", args.limite);
  const candidatos = await (await fetch(`${BACKEND_URL}/transportistas?${params}`)).json();
  return { candidatos };
}
```

Cada candidato devuelto trae `id`, `nombre`, `telefono`,
`disposicion_a_negociar`, `puntualidad`, `tarifa_referencia`,
`tasa_aceptacion_general`, `tasa_aceptacion_corto_plazo`,
`distancia_km` y `puntaje`. El endpoint también sirve solo
(`GET /transportistas?puerto=Manzanillo`) para que el dashboard de
Juan Nicolás pueda mostrar el catálogo si hace falta.

**Con 30 transportistas en el catálogo, un puerto como Manzanillo
devuelve 11 candidatos** — demasiados para negociar uno por uno en
una demo de 24h. Por eso `limite` no corta la lista ordenada por
cercanía: recalcula el `puntaje` (distancia + disposición a negociar
+ puntualidad + las dos tasas de aceptación, pesos en `PESOS_SCORE`
dentro de `carriers_data.py`) y devuelve los mejores N. Ejemplo real
con `GET /transportistas?puerto=Manzanillo&limite=3`: entran
`t-manzanillo-plus`, `t-norte` y `t-express` — no los 3 más cercanos
(eso hubiera incluido a `t-bajio`), sino los 3 con mejor combinación
de cercanía, flexibilidad para negociar y probabilidad de aceptar
el trabajo.

## 5. Llamada entrante simulada, transportista específico, y cuándo cortar

El botón de `voice/public/index.html` dice "Atender llamada", no "Conectar"
— la idea es que Volta ya tiene un mandato y nos está llamando a nosotros
para arrancar la negociación (WebRTC no tiene un "quién marcó a quién"
real, así que técnicamente sigue siendo el mismo `connect()` de siempre).

Al abrir el canal de datos (`dc.open`), `client.js` dispara sola
`saludarInicial()`. **Ojo con un detalle importante de la Realtime API:**
`response.create` con un `instructions` propio no se SUMA al prompt de
sesión (el fat prompt de Sofía) — lo REEMPLAZA para esa respuesta puntual.
La primera versión de esta función le pasaba ahí mismo el saludo
completo con nombre del transportista y datos de la carga, y el
resultado fue el bug que encontró Lucas: esa respuesta usaba solo el
texto corto inyectado, no las ~660 líneas de reglas de Sofía — Volta
"se olvidaba" de su propio prompt (evaluación de mandato, máquina de
estados, etc.) justo en el turno más importante, el de apertura.

La solución: `saludarInicial()` ya no le hace decir nada a Volta en esa
primera respuesta. Solo le pide, vía `response.instructions`, que llame
en orden a tres tools nuevas/existentes — `get_operacion_actual`,
`find_carriers` (sin forzarle un `limite` — la propia tool ya recomienda
`limite: 3` en su description, y forzar `1` ahí generaba un conflicto
que el modelo resolvía a favor de la tool; en cambio se le pide que
trate al primero de la lista como el transportista de esta llamada) y
`check_mandato` — sin hablar todavía.

**Bug real que apareció al probarlo en vivo:** cuando una misma respuesta
trae más de un `function_call` (ej. `check_mandato` y `find_carriers`
juntos), el loop de `handleEvent` que despacha los resultados mandaba un
`response.create` por cada tool call — y la Realtime API solo permite una
respuesta activa a la vez, así que el segundo `response.create` volvía
con el error `conversation_already_has_active_response`. Se arregló
sacando el `response.create` de adentro del loop: ahora se despachan
todos los `conversation.item.create` primero, y recién después se pide
UNA sola respuesta siguiente.
Cuando esos resultados vuelven, el código existente de manejo de tool
calls (`handleEvent`, más abajo en `client.js`) ya dispara un
`response.create` **sin ningún `instructions` override** para la
respuesta siguiente — y esa sí sale con el fat prompt entero disponible,
así que Volta abre con su apertura estándar del prompt de Sofía
("Hola [nombre], habla Volta..."), dirigida al transportista real que
`find_carriers` le devolvió, con los datos reales de `get_operacion_actual`.
La regla de no mencionar `disposicion_a_negociar`, `puntualidad` ni las
tasas de aceptación en voz alta ahora vive directamente en
`session-config.ts` (prompt permanente), no en texto inyectado por turno
— así aplica en toda la llamada, no solo en la apertura.

```ts
{
  type: "function",
  name: "get_operacion_actual",
  description: "Devuelve los datos del transporte que estás gestionando en esta llamada: cliente, contenedor, puerto de origen, destino y ETA. Llamala apenas arranca la llamada, antes de find_carriers y check_mandato, para saber de qué transporte se trata.",
  parameters: { type: "object", properties: {}, required: [] },
},
```

```js
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
    return { error: "no hay ninguna operación cargada todavía" };
  }
}
```

Si quien atiende no es ese transportista (número equivocado, otra
empresa), la regla está en `session-config.ts` (buscá "Confirmá la
identidad al principio de la llamada"): Volta tiene que cortar, no seguir
negociando con quien no le sirve. Para eso existe la tool `end_call`
(nueva — no confundir con `escalate_to_human`, que transfiere a un humano
sin cortar; `end_call` corta la llamada porque no tiene sentido seguirla):

```ts
{
  type: "function",
  name: "end_call",
  description:
    "Termina la llamada porque no sirve a tu objetivo — te confirmaron que es un número " +
    "equivocado, que no son el transportista que buscabas, que no manejan este tipo de " +
    "transporte, o ya no queda nada más que resolver. Usala en vez de seguir una " +
    "conversación que no va a ningún lado. No la uses para transferir a un humano — para " +
    "eso está escalate_to_human.",
  parameters: {
    type: "object",
    properties: {
      motivo: {
        type: "string",
        description: "Por qué cortás, en una frase corta, ej. 'número equivocado, no es Transportes Colima'.",
      },
    },
    required: ["motivo"],
  },
},
```

En `client.js`, el patrón es el mismo que ya existía para
`escalate_to_human`: la tool no corta nada por sí sola. Devuelve una
`instruccion` para que Volta diga UNA frase de cierre, y recién cuando esa
frase termina de generarse (`response.done` sin más tool calls) el cliente
espera ~2.5s (para que el audio termine de sonar) y ahí sí llama a
`hangup()` de verdad.

```js
if (name === "end_call") {
  motivoFinLlamada = args.motivo || "";
  esperandoFraseDeCierre = true;
  return {
    ok: true,
    instruccion:
      "Decile a la contraparte, en UNA sola frase breve y cordial, que listo, gracias, y que cortás. Nada más — no reabras el tema.",
  };
}
```

## Notas

- Si `seed_demo.py` no se corrió todavía, `check_mandato`/`record_commitment` van a fallar con "no hay ninguna operación creada" — correr `python backend/scripts/seed_demo.py` antes de probar la voz contra el backend real.
- El campo `motivo` que devuelve el backend (`"monto excede el tope"`, `"mandato revocado"`, etc.) es justo lo que hay que decirle al interlocutor — no inventar un motivo genérico.
- Cuando el dashboard de Juan Nicolás esté listo, `call_id` debería salir de un `POST /llamadas` real al arrancar la llamada, no generarse con `Date.now()` — es un placeholder para poder probar ya.

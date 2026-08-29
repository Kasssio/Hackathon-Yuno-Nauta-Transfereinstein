# NextWave Hackathon 2026 — Documento de contexto y plan de proyecto

> **Propósito de este documento:** contexto completo para que cualquier IA o persona que se sume al equipo pueda entender el evento, el desafío elegido, las decisiones ya tomadas y el plan de trabajo, sin tener que releer todo el chat original.

---

## 1. Contexto del evento

- **Evento:** NextWave Hackathon 2026
- **Organizadores:** Yuno × Nauta, con el apoyo de OpenAI
- **Fecha:** 28–30 de agosto de 2026
- **Formato:** equipos de 4 personas, 24 horas para desarrollar
- **Regla clave:** cada equipo elige **un solo desafío** de los 4 disponibles

### Entregables obligatorios (iguales para los 4 desafíos)
1. Presentación (PPT/Slides)
2. Demo (en vivo o video)
3. Repo público de GitHub con README
4. Diagrama de arquitectura (en el repo o en el deck)
5. **Decision log:** qué alternativas se consideraron en cada decisión importante y por qué se eligió la que se eligió

> La defensa técnica pesa tanto como la demo. Los jueces preguntan por la arquitectura y cada decisión — una demo espectacular que el equipo no puede explicar pierde contra una demo modesta bien defendida.

### "Trial by fire"
En los 4 desafíos, los jueces operan el sistema en vivo con un input no ensayado por el equipo. El sistema tiene que reaccionar correctamente sin que el equipo toque nada (más allá de lo que el propio desafío permita).

### Vocabulario compartido
- **Agente:** sistema de IA que ejecuta trabajo de forma autónoma usando herramientas — no solo chatea, actúa.
- **Tool:** una acción que el agente puede ejecutar (consultar datos, mandar un mensaje, crear una alerta).
- **Human-in-the-loop:** punto donde el agente debe detenerse y pedirle a un humano que revise, apruebe o decida.

---

## 2. Los 4 desafíos (resumen)

| # | Nombre | Host · tema |
|---|---|---|
| 1 | The Buyer Who Isn't Human | Yuno · pagos agénticos, mandatos y verificación |
| 2 | The Control Tower | Yuno · monitoreo de pagos en vivo y diagnóstico de causa raíz |
| 3 | The Interface That Builds Itself | Nauta · agentes que generan su propia UI en tiempo de ejecución |
| **4** | **The Agent on the Line** | **Nauta · agentes de voz que resuelven procesos logísticos legacy por teléfono** |

**Por qué se descartaron 2 y 3:** el 2 exige generar datos sintéticos de pagos muy realistas antes de poder atacar el problema real (mucho trabajo previo de "fake data engineering"); el 3 es un problema de UI/UX generativa muy abierto y difícil de acotar bien en 24 horas.

**Desafío elegido: #4 — The Agent on the Line.**

---

## 3. Desafío 4 — The Agent on the Line (texto completo del brief)

### Definiciones clave
- **Voice agent:** sistema de IA que sostiene una conversación hablada en tiempo real — escucha, habla y sobrevive interrupciones — mientras ejecuta trabajo con tools durante la llamada.
- **Drayage (transporte terrestre):** tramo en camión que mueve un contenedor del puerto al depósito del cliente; hoy se coordina casi enteramente por teléfono.
- **Carrier / dispatcher:** la empresa de camiones que provee el camión, y la persona que atiende el teléfono, cotiza tarifas y asigna camiones.
- **Commitment:** un hecho verificable extraído de una conversación ("retiro jueves 10:00, $8.500 MXN, chofer Juan") que ambas partes pueden hacer valer después.
- **Mandato:** la autorización que un humano le da al agente para negociar y comprometerse: tope de precio, ventana horaria, condiciones — mismo concepto que en el Desafío 1, acá rige lo que el agente puede acordar por voz.
- **Escalación:** el momento en que el agente le pasa una llamada en vivo a un humano — sin cortar y sin perder lo ya hablado.
- **Barge-in:** el interlocutor interrumpe al agente a mitad de frase; la conversación tiene que sobrevivirlo.

> El vocabulario logístico del Desafío 3 (operation, booking, container, ETA) también aplica acá. El stack de voz es libre: el evento tiene el apoyo de OpenAI y su Realtime API es una elección natural — pero cualquier stack que puedan defender es válido.

### 1. El problema
Buena parte de la logística todavía se resuelve por teléfono: cotizar un camión, confirmar un retiro, perseguir a un chofer, renegociar una ventana de entrega. Los agentes que leen emails y documentos quedan ciegos al canal donde los problemas realmente se resuelven. Esas llamadas:
- No dejan registro estructurado: lo acordado vive en la memoria de alguien o en un post-it.
- Dependen de que dos humanos estén disponibles al mismo tiempo.
- No escalan: diez embarques con problemas son diez conversaciones simultáneas que alguien tiene que sostener.

### 2. Objetivo
Construir un agente de voz que maneje el tramo de transporte terrestre de un embarque enteramente por teléfono:
- [ ] Hace llamadas salientes: llama a transportistas, pide cotizaciones y negocia tarifa y ventana de retiro — varias negociaciones, una mejor elección, siempre dentro de un mandato definido por su humano.
- [ ] Recibe llamadas entrantes: un chofer reporta una demora, un dispatcher mueve un horario — el agente entiende, decide y actúa en tiempo real.
- [ ] Cada llamada produce commitments, no transcripciones: qué se acordó, con quién y bajo qué mandato, escrito al estado de la operación y auditable después.
- [ ] La conversación y el sistema se mantienen consistentes: lo que el agente dice por teléfono siempre coincide con lo que el sistema sabe, y lo que escucha actualiza el sistema.
- [ ] Los casos feos se manejan explícitamente: el humano del otro lado se sale del guion, se contradice, se niega, o empuja algo fuera del mandato → el agente escala a un humano a mitad de llamada, sin cortar.

*Puede incluir (no limitado a): negociaciones paralelas comparadas antes de reservar; verificación por voz de quién llama; detectar que el otro lado de la llamada es otro agente.*

**Trial by fire:** un juez toma un teléfono y juega el otro lado de la llamada — un dispatcher o chofer no ensayado, poco cooperativo e improvisando. El agente debe llegar a un resultado correcto y comprometido en vivo, frente a todos.

### 3. Resultados esperados
Una demo mostrando:
- [ ] El agente llamando a al menos dos transportistas (la telefonía puede ser simulada, la conversación de voz debe ser real), negociando y reservando la mejor opción dentro de su mandato.
- [ ] Una llamada entrante — un chofer reporta un problema — entendida y convertida en una decisión y una operación actualizada.
- [ ] Una renegociación: la situación cambió y el agente vuelve a llamar para mover lo acordado, sin exceder nunca su mandato.
- [ ] El rastro auditable: cada commitment trazable al momento de la conversación que lo produjo.
- [ ] Una escalación a mitad de llamada: un humano toma una conversación en vivo y recibe el contexto de todo lo ya dicho.
- [ ] El trial by fire superado.

**Puntos bonus:**
- Barge-in manejado con naturalidad: el que llama interrumpe y el agente se adapta a mitad de frase en vez de hablar encima.
- Robustez al mundo real: ruido de fondo, acentos marcados, español e inglés mezclados en la misma llamada.
- Defensa ante manipulación por voz: alguien usa urgencia, labia o suplantación para empujar al agente fuera de su mandato — y falla.

### 4. Caso ficticio mínimo
- **Empresa:** "Textiles Pacífico", importadora con un contenedor llegando al puerto de Manzanillo que necesita transporte a su depósito en Guadalajara.
- **Agente:** Volta — coordina el transporte terrestre por teléfono bajo un mandato: "reservar un camión para el jueves, hasta $9.000 MXN".

**Momentos clave:**
1. El contenedor se confirma en puerto → Volta llama a dos transportistas, cotiza, negocia y reserva el mejor dentro del mandato; el humano ve qué se acordó y por qué.
2. El dispatcher llama a la mañana siguiente: el camión se rompió, el retiro se corre a viernes → Volta entiende, evalúa y reprograma — o escala si el mandato no lo cubre.
3. Un transportista llama de vuelta con una "oferta especial" arriba del tope de precio → fuera del mandato → rechazada con educación o escalada, nunca comprometida.
4. El trial → un juez toma el teléfono e improvisa el otro lado; Volta tiene que cerrar un commitment correcto en vivo.

*Números de teléfono, transportistas, tarifas y la capa de telefonía pueden inventarse — la conversación de voz en vivo y los commitments, no.*

---

## 4. Decisión y razonamiento

**Recomendación inicial del análisis:** Desafío 1 (más seguro para 24h, menor riesgo de ejecución en el trial by fire, sin dependencia de pipeline de voz en tiempo real).

**Decisión final del equipo:** Desafío 4.

**Motivo del cambio:** el equipo tiene ventajas relevantes para el Desafío 4 —
- OpenAI es sponsor del evento → soporte técnico en el piso, documentación fresca, posible starter kit para la Realtime API → reduce el riesgo de "plomería" del pipeline de voz.
- El vocabulario logístico ya está compartido con el Desafío 3 → probablemente hay datos/mocks de esa capa ya disponibles por los organizadores.
- El factor "wow" de una negociación de voz real en vivo frente a los jueces es mayor que el de un dashboard.

**Lo que NO se reduce con el apoyo de OpenAI:** el riesgo de sostener una negociación coherente cuando el juez improvisa, cambia de tema, ofrece algo fuera del mandato o interrumpe a mitad de frase. Eso es 100% trabajo del equipo (prompt engineering de negociación, extracción de commitments, manejo de barge-in, enforcement del mandato en tiempo real) — ninguna documentación de OpenAI lo resuelve.

---

## 5. Riesgos identificados (rankeados por importancia y dificultad)

### 🔴 Crítico
1. **Que el agente rompa el mandato bajo presión.** Mitigación: guardrail determinístico separado del LLM (código simple: `monto <= cap AND fecha in ventana`) que valida cualquier commitment antes de escribirlo al estado — nunca depender solo del "juicio" del modelo.
2. **Manejo de interrupciones (barge-in).** Mitigación: usar los eventos nativos de detección de voz (VAD) y cancelación de respuesta de la Realtime API en vez de reinventarlo; tunear sensibilidad y practicar con ruido real.
3. **Detectar cuándo escalar a un humano.** Mitigación: triggers explícitos y combinables (rechazo repetido, pedido directo de humano, oferta X% sobre el cap, contradicción detectada) como red de seguridad además del criterio del LLM.
4. **Latencia / naturalidad del turno de habla.** Mitigación: usar la Realtime API en modo speech-to-speech (no encadenar STT→LLM→TTS por separado); tratar la latencia end-to-end como gate de go/no-go desde el spike inicial.

### 🟠 Alta prioridad
5. **Extraer commitments estructurados, no transcripciones.** Mitigación: tool `record_commitment` que el agente llama en el momento en que se acuerda un dato, no parseo posterior de la transcripción.
6. **Errores de transcripción (acento, ruido, mezcla ES/EN).** Mitigación: el agente confirma en voz alta los datos clave ("entonces $8.500 para el jueves, ¿confirmado?") — corrige errores de STT y da traza auditable gratis.
7. **Cómo simular la llamada (telefonía).** Mitigación: no integrar telefonía real (Twilio, etc.) si no hace falta — el enunciado permite "telephony mockable, voice real"; una llamada laptop-a-laptop o laptop-a-teléfono alcanza. Decidirlo en la hora 0.

### 🟡 Media prioridad
8. **Renegociación con memoria de acuerdos previos.** Mitigación: un objeto de estado simple (JSON) que el agente lee al iniciar cada llamada y actualiza al cerrarla — no hace falta memoria vectorial.
9. **Orquestar negociaciones con varios transportistas.** Mitigación: hacerlo secuencial (cotización de A, después B, comparar, reservar la mejor) en vez de paralelo — cumple la consigna igual y ahorra complejidad de estado concurrente.
10. **Brecha de experiencia del equipo con Realtime API.** Mitigación: definir de antemano un criterio de fallback (ej. push-to-talk en vez de full-duplex) si a la hora 4 el pipeline no anda — decidirlo en frío, no en pánico a la hora 20.

### 🟢 Prioridad baja / pulido
11. **Resistencia a manipulación (urgencia, impersonación).** En gran parte ya cubierto por los guardrails de los puntos 1 y 3.
12. **Ambiente ruidoso del venue.** Mitigación: micrófono direccional/headset, ensayo en el lugar real de la demo si es posible, supresión de ruido si la API la ofrece.
13. **Sacrificar deliverables (deck, README, diagrama, decision log) por seguir puliendo código.** Mitigación: corte de hora duro (hora 20) para dejar de tocar código, sin excepción.

**Consejo transversal:** construir el guardrail de mandato (riesgo #1) como código separado del LLM desde el día uno — es el punto de mayor impacto en el trial by fire y, de toda la lista, el más fácil de resolver bien.

---

## 6. Roles del equipo (4 personas)

1. **Voice Pipeline Lead**
   Dueño de la integración con la Realtime API: conexión, configuración del VAD para barge-in, tuneo de latencia, y la decisión de fallback si el pipeline no anda temprano. Cubre los riesgos #2 y #4.

2. **Agent Logic / Prompt Engineer**
   Dueño de cómo negocia el agente: prompts de negociación, diseño de tools (`request_quote`, `record_commitment`), y el guardrail de mandato como código determinístico. Define los triggers explícitos de escalación. Cubre los riesgos #1, #3 y #5.

3. **Backend / State Engineer**
   Dueño del modelo de datos (operación, mandato, commitments), manejo de llamadas entrantes, memoria entre llamadas para renegociación, y el trail auditable. Cubre los riesgos #6, #8 y #9.

4. **Dashboard + Demo/Deliverables Lead**
   Dueño de la vista humana (mandato, commitments, estado de la operación en vivo), el diagrama de arquitectura, el decision log (se llena en el momento, no al final), el README y el deck. Lleva el reloj del plan de 24h y corta la hora 20. Cubre el riesgo #13.

**Nota sobre testing:** en los ensayos del trial by fire, el Dashboard/Demo Lead lidera haciendo de interlocutor difícil en las primeras rondas; los otros tres roles rotan sumando variantes, para que nadie testee su propio código con el mismo sesgo con el que lo escribió.

---

## 7. Plan de trabajo de 24 horas (con tareas por rol)

### Bloque 1 — Definición y arquitectura (0h–2h)
- **Voice Pipeline Lead:** configura el acceso a la Realtime API y decide el modo speech-to-speech.
- **Agent Logic:** define el mandato de negociación (precio tope, ventana) y bocetea prompts + tools necesarias.
- **Backend/State:** diseña el schema de datos (operación, mandato, commitments, historial de llamadas).
- **Dashboard/Demo:** wireframea el dashboard, arranca el diagrama de arquitectura y el decision log, y define el criterio de fallback por si el spike de voz falla.

### Bloque 2 — Spike crítico: pipeline de voz end-to-end (2h–4h)
- **Voice Pipeline Lead:** dueño exclusivo — logra una llamada básica funcionando de punta a punta con latencia aceptable.
- **Agent Logic:** en paralelo, afina el system prompt de negociación en un playground de texto, sin bloquear al Voice Lead.
- **Backend/State:** implementa el guardrail determinístico de mandato como función aislada y testeable sin voz.
- **Dashboard/Demo:** deja armado el esqueleto del repo y avanza el diagrama con lo definido en el bloque 1.

### Bloque 3 — Negociación saliente + extracción de commitments (4h–8h)
- **Voice Pipeline Lead:** integra el prompt de negociación al pipeline real y ajusta los turnos de habla.
- **Agent Logic:** define la tool `record_commitment` y los triggers explícitos de escalación; conecta el guardrail del backend a la conversación.
- **Backend/State:** expone el guardrail y `record_commitment` como funciones consumibles por el agente; empieza a loguear cada llamada con timestamp.
- **Dashboard/Demo:** monta la vista básica de estado de la operación, aunque sea con datos mockeados.

### Bloque 4 — Llamadas entrantes, barge-in y escalación (8h–12h)
- **Voice Pipeline Lead:** configura la sensibilidad del VAD para barge-in con los eventos nativos de la API; prueba interrupciones reales.
- **Agent Logic:** escribe el flujo de llamada entrante (chofer reporta demora) y la lógica de reprogramación dentro/fuera del mandato.
- **Backend/State:** implementa la memoria simple entre llamadas (estado que el agente lee y actualiza) para sostener renegociaciones.
- **Dashboard/Demo:** agrega la vista de escalación al dashboard y empieza a llenar el decision log con lo decidido hasta ahora.

### Bloque 5 — Descanso corto + hardening (12h–14h)
- Descanso breve para todo el equipo.
- **Voice Pipeline Lead:** endurece contra ruido de fondo y mezcla español/inglés si el tiempo alcanza.
- **Agent Logic:** ajusta prompts según lo que falló en las pruebas del bloque anterior.
- **Backend/State:** revisa logs y cierra bugs de estado detectados.
- **Dashboard/Demo:** pone al día el README y el diagrama con lo realmente construido.

### Bloque 6 — Ensayos intensivos del trial by fire (14h–20h, bloque extendido)
- **Dashboard/Demo Lead:** hace de interlocutor difícil en las primeras rondas.
- **Los otros tres roles:** rotan haciendo de "juez" sumando variantes (acento, interrupción, oferta fuera de mandato) mientras observan y anotan fallas.
- Cada uno arregla bugs de su propia área en caliente: Voice Pipeline (latencia/barge-in), Agent Logic (negociación/escalación), Backend (guardrail/estado).
- **Meta:** llegar a la hora 20 sosteniendo negociaciones reales sin romper el mandato, improvise lo que improvise el interlocutor.

### Bloque 7 — Deck, diagrama, decision log y ensayo final (20h–24h)
- **Dashboard/Demo Lead:** lidera el armado del deck y coordina el ensayo del pitch; corta el desarrollo de código a la hora 20 sin excepción.
- **Agent Logic + Backend:** cierran el decision log (qué alternativas se consideraron en mandato, negociación y arquitectura, y por qué se eligió cada una).
- **Voice Pipeline Lead:** última pasada de estabilidad sin agregar features nuevas; prepara un plan B por si algo falla el día de la demo.
- **Todo el equipo:** ensaya la demo completa al menos dos veces, con roles claros de quién habla, quién opera y quién responde preguntas técnicas.

---

## 8. Notas de arquitectura ya decididas (para continuar el desarrollo)

- **Stack de voz:** OpenAI Realtime API, en modo speech-to-speech (no encadenar STT→LLM→TTS por separado) para minimizar latencia y sonar natural.
- **Guardrail de mandato:** función determinística separada del LLM, no una decisión "blanda" del modelo. Valida cada commitment antes de escribirlo al estado.
- **Extracción de commitments:** vía tool call (`record_commitment`) en el momento en que se acuerda un dato durante la llamada, no vía parseo posterior de la transcripción.
- **Telefonía:** simulada/mockeada (laptop-a-laptop o laptop-a-teléfono), sin integración real con un proveedor tipo Twilio — la conversación de voz debe ser real, la capa telefónica no.
- **Concurrencia de negociaciones:** secuencial, no paralela (cotizar A, después B, comparar, reservar la mejor) para reducir complejidad de estado.
- **Memoria entre llamadas:** estado simple tipo JSON por operación, sin memoria vectorial ni infraestructura adicional.
- **Corte de desarrollo:** hora 20 de las 24 — a partir de ahí, solo deliverables y ensayo, sin tocar código salvo estabilidad crítica.

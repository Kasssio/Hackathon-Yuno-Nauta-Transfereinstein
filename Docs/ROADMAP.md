# Roadmap 24h — Challenge 4: The Agent on the Line

> Nauta · agentes de voz para logística legacy por teléfono — NextWave Hackathon 2026, 28–30 ago · equipo de 4 · 24 horas

> **Sobre este archivo:** conversión a Markdown de `Context & Info/Roadmap Challenge 4 - The Agent on the Line.docx`,
> para que el equipo lo lea desde el repo sin Word. El `.docx` sigue siendo el original.
> Los riesgos están numerados 1–13 de forma explícita porque el código los cita por número
> (ver `backend/app/guardrail.py`, que se declara mitigación del riesgo #1).

---

## 0. Decisión del equipo

El equipo evaluó primero el **Desafío 1** (más seguro para 24h, sin dependencia de un pipeline de voz en tiempo real) pero decidió ir con el **Desafío 4**: OpenAI es sponsor del evento (soporte técnico + Realtime API bien documentada), el vocabulario logístico ya se comparte con el Desafío 3, y el factor "wow" de una negociación de voz real en vivo frente a los jueces es mayor que el de un dashboard.

Lo que el soporte de OpenAI **no** reduce: sostener una negociación coherente cuando el juez improvisa, cambia de tema, ofrece algo fuera del mandato o interrumpe a mitad de frase — eso es 100% trabajo del equipo.

---

## 1. El desafío en una línea

Textiles Pacífico tiene un contenedor llegando a Manzanillo que necesita transporte a Guadalajara. El agente **Volta** coordina el tramo terrestre por teléfono bajo un mandato: *"reservar un camión para el jueves, hasta $9.000 MXN"*.

**Trial by fire:** un juez toma un teléfono y juega el otro lado de la llamada — dispatcher o chofer no ensayado, poco cooperativo e improvisando — y Volta tiene que cerrar un commitment correcto en vivo.

---

## 2. Roles del equipo

| # | Rol | Integrante | Dueño de | Cubre |
|---|---|---|---|---|
| 1 | Voice Pipeline Lead | **Marcos Bustamante** | Integración con la Realtime API (modo speech-to-speech), configuración del VAD para barge-in, tuneo de latencia, y la decisión de fallback si el pipeline no anda temprano | Riesgos #2 y #4 |
| 2 | Agent Logic / Prompt Engineer | **Sofía Parisi** | Cómo negocia el agente: prompts de negociación, diseño de tools (`request_quote`, `record_commitment`), triggers explícitos de escalación, y el guardrail de mandato como código determinístico | Riesgos #1, #3 y #5 |
| 3 | Backend / State Engineer | **Lucas Estrada** | Modelo de datos (operación, mandato, commitments), manejo de llamadas entrantes, memoria simple entre llamadas para renegociación, trail auditable | Riesgos #6, #8 y #9 |
| 4 | Dashboard + Demo/Deliverables Lead | **Juan Nicolás Fato** | Vista humana (mandato, commitments, estado de la operación en vivo), diagrama de arquitectura, decision log (se llena en el momento), README, deck, reloj del plan de 24h y corte de hora 20 | Riesgo #13 |

> **Nota de testing:** en los ensayos del trial by fire, Juan Nicolás lidera haciendo de interlocutor difícil en las primeras rondas; los otros tres roles rotan sumando variantes (acento, interrupción, oferta fuera de mandato), para que nadie testee su propio código con el mismo sesgo con el que lo escribió.

---

## 3. Arquitectura y decisiones ya tomadas

- **Stack de voz:** OpenAI Realtime API, en modo speech-to-speech (no encadenar STT→LLM→TTS por separado) para minimizar latencia y sonar natural.
- **Guardrail de mandato:** función determinística separada del LLM (`monto <= tope AND fecha in ventana`), nunca una decisión "blanda" del modelo. Valida cada commitment antes de escribirlo al estado.
- **Extracción de commitments:** vía tool call `record_commitment` en el momento en que se acuerda un dato durante la llamada, no vía parseo posterior de la transcripción.
- **Telefonía:** simulada/mockeada (laptop-a-laptop o laptop-a-teléfono) — la conversación de voz debe ser real, la capa telefónica no.
- **Concurrencia de negociaciones:** secuencial, no paralela (cotizar A, después B, comparar, reservar la mejor) para reducir complejidad de estado.
- **Memoria entre llamadas:** estado simple tipo JSON por operación, sin memoria vectorial ni infraestructura adicional.
- **Corte de desarrollo:** hora 20 de las 24 — desde ahí, solo deliverables y ensayo, sin tocar código salvo estabilidad crítica.

---

## 4. Riesgos y mitigaciones (rankeados)

### 🔴 Crítico

1. **Que el agente rompa el mandato bajo presión.** Guardrail determinístico separado del LLM que valida cualquier commitment antes de escribirlo al estado.
2. **Manejo de interrupciones (barge-in).** Usar los eventos nativos de VAD y cancelación de respuesta de la Realtime API en vez de reinventarlo; tunear sensibilidad con ruido real.
3. **Detectar cuándo escalar a un humano.** Triggers explícitos y combinables (rechazo repetido, pedido directo de humano, oferta X% sobre el cap, contradicción detectada) como red de seguridad además del criterio del LLM.
4. **Latencia / naturalidad del turno de habla.** Realtime API en modo speech-to-speech; tratar la latencia end-to-end como gate de go/no-go desde el spike inicial.

### 🟠 Alta prioridad

5. **Extraer commitments estructurados, no transcripciones.** Tool `record_commitment` llamada en el momento en que se acuerda un dato.
6. **Errores de transcripción (acento, ruido, mezcla ES/EN).** El agente confirma en voz alta los datos clave (*"entonces $8.500 para el jueves, ¿confirmado?"*).
7. **Cómo simular la llamada (telefonía).** No integrar telefonía real (Twilio) si no hace falta — "telephony mockable, voice real" alcanza con laptop-a-laptop o laptop-a-teléfono. Decidirlo en la hora 0.

### 🟡 Media prioridad

8. **Renegociación con memoria de acuerdos previos.** Objeto de estado JSON que el agente lee al iniciar cada llamada y actualiza al cerrarla.
9. **Orquestar negociaciones con varios transportistas.** Secuencial (A, después B, comparar, reservar la mejor) en vez de paralelo.
10. **Brecha de experiencia del equipo con Realtime API.** Definir de antemano un criterio de fallback (ej. push-to-talk en vez de full-duplex) si a la hora 4 el pipeline no anda — decidirlo en frío, no en pánico a la hora 20.

### 🟢 Prioridad baja / pulido

11. **Resistencia a manipulación (urgencia, impersonación).** En gran parte ya cubierto por los guardrails de los puntos 1 y 3.
12. **Ambiente ruidoso del venue.** Micrófono direccional/headset, ensayo en el lugar real de la demo si es posible.
13. **Sacrificar deliverables por seguir puliendo código.** Corte de hora duro (hora 20), sin excepción.

> **Consejo transversal:** construir el guardrail de mandato (riesgo #1) como código separado del LLM desde el bloque 2 — es el punto de mayor impacto en el trial by fire y el más fácil de resolver bien si se hace temprano.

---

## 5. Plan de 24 horas por bloque

### Bloque 1 — Definición y arquitectura (0h–2h)

- **Marcos** (Voice Pipeline): configura el acceso a la Realtime API y confirma el modo speech-to-speech.
- **Sofía** (Agent Logic): define el mandato de negociación (precio tope, ventana) y bocetea prompts + tools necesarias.
- **Lucas** (Backend/State): diseña el schema de datos (operación, mandato, commitments, historial de llamadas).
- **Juan Nicolás** (Dashboard/Demo): wireframea el dashboard, arranca el diagrama de arquitectura y el decision log, define el criterio de fallback por si el spike de voz falla.

### Bloque 2 — Spike crítico: pipeline de voz end-to-end (2h–4h)

- **Marcos:** dueño exclusivo — logra una llamada básica funcionando de punta a punta con latencia aceptable.
- **Sofía:** en paralelo, afina el system prompt de negociación en un playground de texto, sin bloquear a Marcos.
- **Lucas:** implementa el guardrail determinístico de mandato como función aislada y testeable sin voz.
- **Juan Nicolás:** deja armado el esqueleto del repo y avanza el diagrama con lo definido en el bloque 1.

### Bloque 3 — Negociación saliente + extracción de commitments (4h–8h)

- **Marcos:** integra el prompt de negociación al pipeline real y ajusta los turnos de habla.
- **Sofía:** define la tool `record_commitment` y los triggers explícitos de escalación; conecta el guardrail del backend a la conversación.
- **Lucas:** expone el guardrail y `record_commitment` como funciones consumibles por el agente; empieza a loguear cada llamada con timestamp.
- **Juan Nicolás:** monta la vista básica de estado de la operación, aunque sea con datos mockeados.

### Bloque 4 — Llamadas entrantes, barge-in y escalación (8h–12h)

- **Marcos:** configura la sensibilidad del VAD para barge-in con los eventos nativos de la API; prueba interrupciones reales.
- **Sofía:** escribe el flujo de llamada entrante (chofer reporta demora) y la lógica de reprogramación dentro/fuera del mandato.
- **Lucas:** implementa la memoria simple entre llamadas (estado que el agente lee y actualiza) para sostener renegociaciones.
- **Juan Nicolás:** agrega la vista de escalación al dashboard y empieza a llenar el decision log con lo decidido hasta ahora.

### Bloque 5 — Descanso corto + hardening (12h–14h)

- Descanso breve para todo el equipo.
- **Marcos:** endurece contra ruido de fondo y mezcla español/inglés si el tiempo alcanza.
- **Sofía:** ajusta prompts según lo que falló en las pruebas del bloque anterior.
- **Lucas:** revisa logs y cierra bugs de estado detectados.
- **Juan Nicolás:** pone al día el README y el diagrama con lo realmente construido.

### Bloque 6 — Ensayos intensivos del trial by fire (14h–20h)

- **Juan Nicolás:** hace de interlocutor difícil en las primeras rondas.
- **Marcos, Sofía y Lucas:** rotan haciendo de "juez" sumando variantes (acento, interrupción, oferta fuera de mandato) mientras observan y anotan fallas.
- Cada uno arregla bugs de su propia área en caliente: Marcos (latencia/barge-in), Sofía (negociación/escalación), Lucas (guardrail/estado).
- **Meta:** llegar a la hora 20 sosteniendo negociaciones reales sin romper el mandato, improvise lo que improvise el interlocutor.

### Bloque 7 — Deck, diagrama, decision log y ensayo final (20h–24h)

- **Juan Nicolás:** lidera el armado del deck y coordina el ensayo del pitch; corta el desarrollo de código a la hora 20 sin excepción.
- **Sofía + Lucas:** cierran el decision log (qué alternativas se consideraron en mandato, negociación y arquitectura, y por qué se eligió cada una).
- **Marcos:** última pasada de estabilidad sin agregar features nuevas; prepara un plan B por si algo falla el día de la demo.
- **Todo el equipo:** ensaya la demo completa al menos dos veces, con roles claros de quién habla, quién opera y quién responde preguntas técnicas.

---

## 6. Checklist de deliverables (igual para los 4 desafíos)

- [ ] Presentación (PPT/Slides)
- [ ] Demo (en vivo o video)
- [ ] Repo público de GitHub con README
- [ ] Diagrama de arquitectura (en el repo o en el deck)
- [ ] Decision log — alternativas consideradas en cada decisión importante y por qué se eligió la elegida

> La defensa técnica pesa tanto como la demo — los jueces preguntan por la arquitectura y cada decisión.

# Backend — Challenge 4: The Agent on the Line

Este backend cubre el rol de **Backend / State Engineer** (Lucas): el
modelo de datos, el guardrail de mandato, el trail auditable y la API
que van a consumir el agente (Sofía/Marcos) y el dashboard (Juan Nicolás).

## ¿Qué es un "schema" acá?

Nada intimidante: es simplemente el molde de cada "cosa" del sistema —
qué campos tiene y de qué tipo es cada uno. Están todos en
`app/models.py`, como clases de Python con comentarios explicando cada
una. Si algo no encaja con el molde (por ejemplo, mandás un `monto`
como texto en vez de número), Pydantic tira un error claro al momento,
en vez de que el bug aparezca recién en la demo.

Las piezas del dominio:

- **Mandato** — lo que el humano autoriza a negociar (tope de precio,
  ventana de fechas, hasta cuándo vale).
- **Operación** — el embarque que se está gestionando.
- **Commitment** — lo que Volta acuerda en una llamada. Es lo que pasa
  por el **guardrail** antes de aceptarse.
- **Historial de llamadas (CallLogEntry)** — un registro por cada
  llamada. Si la llamada se escaló y Volta quedó en "modo escucha",
  puede traer un `resumen_sugerido` (borrador de commitment) que el
  referente revisa en el dashboard y confirma — eso dispara un
  `POST /commitments` normal, con el guardrail de siempre.
- **Catálogo de transportistas (`app/carriers_data.py`)** — fixture
  ficticio (puerto que atienden, ubicación, disposición a negociar 1-5,
  puntualidad 1-5, tarifa de referencia). Resuelve "a quién llama
  Volta": el filtro por puerto y distancia es código de verdad, no un
  transportista hardcodeado en el prompt del agente.

## Cómo correrlo

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> Nota: si corrés esto a través de una sesión de Claude (device_bash),
> la instalación de paquetes puede fallar por las restricciones de red
> de la sesión — correlo directo en tu propia terminal, ahí no hay
> ese problema.

Levantar la API (CORS abierto — el frontend en otro puerto le pega sin configuración extra):

```bash
uvicorn app.main:app --reload --port 8000
```

Docs interactivas (Swagger, para probar los endpoints a mano) en
`http://localhost:8000/docs`.

Correr los tests del guardrail (no necesitan la API levantada, ni voz,
ni LLM — son los que más importan para el trial by fire):

```bash
pytest tests/test_guardrail.py tests/test_carriers.py -v
```

Seedear el caso mínimo del brief (Textiles Pacífico) para que el
frontend tenga datos reales desde el arranque:

```bash
python scripts/seed_demo.py
```

Correr los 6 escenarios de punta a punta contra la API real (feliz,
tope excedido, partir la compra, reprogramación, revocación en vivo):

```bash
python scripts/simulate_scenarios.py
```

## Endpoints

| Método | Ruta | Para qué |
|---|---|---|
| `GET` | `/operaciones` | Listar operaciones — para el selector del dashboard si hay más de una |
| `POST` | `/operaciones` | Crear una operación (embarque) |
| `GET` | `/operaciones/{id}` | Detalle de una operación |
| `GET` | `/operaciones/{id}/mandato` | Atajo: el mandato vigente de esa operación, sin tener que guardarse el mandato_id aparte |
| `GET` | `/transportistas` | Acá pega la tool `find_carriers` — candidatos para negociar, filtrados por puerto (`?puerto=`) y opcionalmente por distancia máxima (`?max_distancia_km=`), ordenados por cercanía. Catálogo ficticio en `app/carriers_data.py` |
| `POST` | `/mandatos` | Crear un mandato para una operación |
| `POST` | `/mandatos/{id}/revocar` | **El botón del trial by fire** — revoca en vivo |
| `POST` | `/cotizaciones` | Acá pega la tool `request_quote` — registra una oferta de un transportista SIN comprometerse (no corre el guardrail). Para "several negotiations, one best choice" |
| `POST` | `/commitments` | Acá pega la tool `record_commitment` del agente, y también el botón "Confirmar" del referente sobre un `resumen_sugerido`. Corre el guardrail y devuelve `aprobado`/`motivo` |
| `GET` | `/operaciones/{id}/commitments` | Para la vista del dashboard |
| `POST` | `/commitments/{id}/cancelar` | Acá pega la tool `cancel_commitment` — cancela una reserva vigente porque apareció una oferta mejor. No se borra, queda marcada `cancelado: true` con motivo |
| `POST` | `/llamadas` | Registrar una entrada del historial de llamadas (puede traer `resumen_sugerido`) |
| `GET` | `/operaciones/{id}/llamadas` | Historial de llamadas de la operación — de acá lee el dashboard los `resumen_sugerido` pendientes de confirmar |
| `GET` | `/operaciones/{id}/trail` | El trail auditable completo — vista del referente |
| `POST` | `/debug/reset` | Vacía todo el estado — para rehearsar el trial by fire las veces que hagan falta sin tocar archivos a mano |

## Cómo está guardado el estado

Nada de base de datos por ahora: `app/storage.py` guarda todo en
`backend/data/state.json` (se recrea solo, no hace falta tocarlo) y el
trail auditable en `backend/data/audit_log.jsonl`, un archivo
append-only donde cada línea guarda el hash de la línea anterior — así
se puede defender ante los jueces que el trail no se puede reescribir
sin que se note. Ninguno de los dos se versiona en git (están en
`.gitignore`).

Si en algún momento hace falta que el dashboard se actualice solo sin
poll (Supabase, WebSocket), se cambia adentro de `storage.py` nada más
— `main.py` y `guardrail.py` no saben cómo se guardan los datos.

## Qué falta (para ir tachando contra el roadmap)

- [x] Guardrail determinístico con los 4 chequeos base (tope, ventana, revocado, expirado)
- [x] Defensa contra partir la compra en varias llamadas (segunda reserva para la misma operación se rechaza)
- [x] CORS + endpoints de conveniencia para que el frontend arranque
- [x] `resumen_sugerido` en el historial de llamadas, para el flujo de "modo escucha" en llamadas escaladas
- [x] `/debug/reset` para rehearsar el trial by fire repetidas veces
- [x] `request_quote`/`/cotizaciones` separado de `record_commitment` — para poder cotizar con varios transportistas sin disparar el guardrail anti-duplicado antes de elegir
- [x] `cancel_commitment`/`/commitments/{id}/cancelar` — soporta la negociación con reconsideración (cerrar con 1, encontrar algo mejor, cancelar y cerrar con 2, y volver atrás si hace falta), sin romper la defensa anti-duplicado
- [x] `find_carriers`/`/transportistas` — catálogo ficticio de transportistas con filtro por puerto y distancia, para que "a quién llama Volta" sea una decisión con lógica y no un hardcode
- [ ] Bloque 3: conectar `record_commitment` real desde la tool del agente (Sofía) — hoy el endpoint ya funciona y está testeado, falta que el agente le pegue.
- [ ] Bloque 4: usar `POST /llamadas` desde el flujo de llamada entrante real; validar con Marcos si la Realtime API soporta un modo "solo escucha" (audio mudo, sigue transcribiendo) para el modo escucha, o si hace falta un fallback con transcripción aparte.
- [ ] Evaluar `condiciones` en texto libre del mandato (ej. "hasta 3 veces al mes") — hoy `guardrail.py` no las evalúa todavía, queda comentado en el código.
- [ ] Si el dashboard necesita tiempo real sin poll: migrar `storage.py` a Supabase.

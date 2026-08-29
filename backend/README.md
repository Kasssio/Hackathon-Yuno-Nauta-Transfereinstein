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

Las 4 piezas del dominio:

- **Mandato** — lo que el humano autoriza a negociar (tope de precio,
  ventana de fechas, hasta cuándo vale).
- **Operación** — el embarque que se está gestionando.
- **Commitment** — lo que Volta acuerda en una llamada. Es lo que pasa
  por el **guardrail** antes de aceptarse.
- **Historial de llamadas** — un registro por cada llamada.

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

Levantar la API:

```bash
uvicorn app.main:app --reload --port 8000
```

Docs interactivas (Swagger, para probar los endpoints a mano) en
`http://localhost:8000/docs`.

Correr los tests del guardrail (no necesitan la API levantada, ni voz,
ni LLM — son los que más importan para el trial by fire):

```bash
pytest tests/test_guardrail.py -v
```

## Endpoints (Bloque 2-3 del roadmap)

| Método | Ruta | Para qué |
|---|---|---|
| `POST` | `/operaciones` | Crear una operación (embarque) |
| `POST` | `/mandatos` | Crear un mandato para una operación |
| `POST` | `/mandatos/{id}/revocar` | **El botón del trial by fire** — revoca en vivo |
| `POST` | `/commitments` | Acá pega la tool `record_commitment` del agente. Corre el guardrail y devuelve `aprobado`/`motivo` |
| `GET` | `/operaciones/{id}/commitments` | Para la vista del dashboard |
| `GET` | `/operaciones/{id}/trail` | El trail auditable completo — vista del auditor |
| `POST` | `/llamadas` | Registrar una entrada del historial de llamadas |

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

- [ ] Bloque 3: conectar `record_commitment` real desde la tool del agente (Sofía) — hoy el endpoint ya funciona y está testeado, falta que el agente le pegue.
- [ ] Bloque 4: usar `POST /llamadas` desde el flujo de llamada entrante; sumar la memoria simple entre llamadas para renegociación.
- [ ] Evaluar `condiciones` en texto libre del mandato (ej. "hasta 3 veces al mes") — hoy `guardrail.py` no las evalúa todavía, queda comentado en el código.
- [ ] Si el dashboard necesita tiempo real sin poll: migrar `storage.py` a Supabase.

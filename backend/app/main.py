"""
API del backend (Bloques 2-4 del roadmap).

Endpoints pensados para 3 consumidores distintos:
- El agente de Sofía/Marcos: POST /commitments (la tool `record_commitment`
  le pega acá), GET /operaciones/{id}/mandato para chequear el mandato
  antes de negociar, y POST /llamadas para dejar el resumen_sugerido
  cuando Volta queda en "modo escucha" en una llamada escalada.
- El dashboard de Juan Nicolás: GET /operaciones, GET /operaciones/{id},
  GET /operaciones/{id}/commitments, GET /operaciones/{id}/llamadas,
  GET /operaciones/{id}/trail — para las dos vistas (referente y chofer).
- Los jueces en el trial by fire: POST /mandatos/{id}/revocar, para
  revocar el mandato en vivo y ver si el agente reacciona bien.

CORS abierto a cualquier origen — es una demo de hackathon corriendo
local, no un servicio en producción; así el frontend (Vite en otro
puerto) puede pegarle sin configuración extra.

Correr con: uvicorn app.main:app --reload --port 8000
Docs interactivas (Swagger) en: http://localhost:8000/docs
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .guardrail import validate_commitment
from .carriers_data import buscar_candidatos
from .models import (
    CallLogEntry,
    CallLogEntryCreate,
    CancelarCommitmentRequest,
    Commitment,
    CommitmentCreate,
    CotizacionCreate,
    Mandato,
    MandatoCreate,
    Operacion,
    OperacionCreate,
)
from .storage import store

app = FastAPI(title="Challenge 4 — The Agent on the Line — backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Operaciones
# ---------------------------------------------------------------------------

@app.get("/operaciones", response_model=List[Operacion])
def listar_operaciones() -> List[Operacion]:
    return list(store.operaciones.values())


@app.post("/operaciones", response_model=Operacion)
def crear_operacion(payload: OperacionCreate) -> Operacion:
    op = Operacion(**payload.model_dump())
    store.operaciones[op.id] = op
    store.save()
    store.append_audit("operacion_creada", {"operacion_id": op.id, "cliente": op.cliente})
    return op


@app.get("/operaciones/{operacion_id}", response_model=Operacion)
def obtener_operacion(operacion_id: str) -> Operacion:
    op = store.operaciones.get(operacion_id)
    if not op:
        raise HTTPException(404, "operación no encontrada")
    return op


@app.get("/operaciones/{operacion_id}/mandato", response_model=Mandato)
def mandato_de_la_operacion(operacion_id: str) -> Mandato:
    """Atajo para el frontend: no hace falta guardarse el mandato_id
    aparte, alcanza con el id de la operación."""
    op = store.operaciones.get(operacion_id)
    if not op or not op.mandato_id:
        raise HTTPException(404, "esta operación todavía no tiene mandato")
    mandato = store.mandatos.get(op.mandato_id)
    if not mandato:
        raise HTTPException(404, "mandato no encontrado")
    return mandato


# ---------------------------------------------------------------------------
# Transportistas — resuelve "a quién llama Volta". Filtro de candidatos
# por puerto (y opcionalmente por distancia máxima al puerto) sobre el
# catálogo ficticio de backend/app/carriers_data.py. Sofía/Marcos usan
# esto ANTES de arrancar la ronda de llamadas salientes, así la lista de
# "a quién negociar" es una decisión con lógica (puerto, distancia,
# disposición a negociar, puntualidad), no un transportista hardcodeado
# en el prompt del agente.
# ---------------------------------------------------------------------------

@app.get("/transportistas")
def listar_transportistas(
    puerto: Optional[str] = None, max_distancia_km: Optional[float] = None
) -> List[dict]:
    return buscar_candidatos(puerto=puerto, max_distancia_km=max_distancia_km)


# ---------------------------------------------------------------------------
# Mandatos
# ---------------------------------------------------------------------------

@app.post("/mandatos", response_model=Mandato)
def crear_mandato(payload: MandatoCreate) -> Mandato:
    if payload.operacion_id not in store.operaciones:
        raise HTTPException(404, "la operación no existe")
    mandato = Mandato(**payload.model_dump())
    store.mandatos[mandato.id] = mandato
    store.operaciones[payload.operacion_id].mandato_id = mandato.id
    store.save()
    store.append_audit(
        "mandato_creado",
        {
            "operacion_id": mandato.operacion_id,
            "mandato_id": mandato.id,
            "tope_precio": mandato.tope_precio,
            "ventana": [str(mandato.ventana_inicio), str(mandato.ventana_fin)],
        },
    )
    return mandato


@app.get("/mandatos/{mandato_id}", response_model=Mandato)
def obtener_mandato(mandato_id: str) -> Mandato:
    mandato = store.mandatos.get(mandato_id)
    if not mandato:
        raise HTTPException(404, "mandato no encontrado")
    return mandato


@app.post("/mandatos/{mandato_id}/revocar", response_model=Mandato)
def revocar_mandato(mandato_id: str) -> Mandato:
    """Este es el botón que van a apretar los jueces en el trial by fire."""
    mandato = store.mandatos.get(mandato_id)
    if not mandato:
        raise HTTPException(404, "mandato no encontrado")
    mandato.revocado = True
    mandato.revocado_en = datetime.now(timezone.utc)
    store.save()
    store.append_audit(
        "mandato_revocado",
        {"operacion_id": mandato.operacion_id, "mandato_id": mandato.id},
    )
    return mandato


# ---------------------------------------------------------------------------
# Cotizaciones — "several negotiations, one best choice". Acá pega la
# tool `request_quote`: registra una oferta de un transportista SIN
# comprometerse. No corre el guardrail — no hay nada que cuidar todavía,
# es solo para poder comparar antes de elegir con quién cerrar.
# Quedan en el trail auditable (evento "cotizacion_recibida"), así que
# GET /operaciones/{id}/trail también sirve para ver todas las ofertas
# que se compararon, no solo la que se terminó reservando.
# ---------------------------------------------------------------------------

@app.post("/cotizaciones")
def registrar_cotizacion(payload: CotizacionCreate) -> dict:
    store.append_audit("cotizacion_recibida", payload.model_dump(mode="json"))
    return {"registrada": True}


# ---------------------------------------------------------------------------
# Commitments — acá pega la tool `record_commitment` del agente, y
# también el botón "Confirmar" del referente cuando acepta un
# resumen_sugerido de una llamada escalada.
# ---------------------------------------------------------------------------

@app.post("/commitments")
def registrar_commitment(payload: CommitmentCreate) -> dict:
    mandato = store.mandatos.get(payload.mandato_id)
    if not mandato:
        raise HTTPException(404, "mandato no encontrado")

    commitments_previos = [
        c for c in store.commitments.values() if c.operacion_id == payload.operacion_id
    ]
    resultado = validate_commitment(payload, mandato, commitments_previos)

    commitment = Commitment(
        **payload.model_dump(),
        aprobado=resultado.aprobado,
        motivo_rechazo=None if resultado.aprobado else resultado.motivo,
    )
    store.commitments[commitment.id] = commitment

    llamada = store.llamadas.get(payload.call_id)
    if llamada:
        llamada.commitments_ids.append(commitment.id)

    store.save()
    store.append_audit(
        "commitment_evaluado",
        {
            "operacion_id": commitment.operacion_id,
            "commitment_id": commitment.id,
            "call_id": commitment.call_id,
            "aprobado": commitment.aprobado,
            "motivo": resultado.motivo,
            "monto": commitment.monto,
        },
    )

    return {"commitment": commitment, "aprobado": resultado.aprobado, "motivo": resultado.motivo}


@app.get("/operaciones/{operacion_id}/commitments", response_model=List[Commitment])
def listar_commitments(operacion_id: str) -> List[Commitment]:
    return [c for c in store.commitments.values() if c.operacion_id == operacion_id]


@app.post("/commitments/{commitment_id}/cancelar", response_model=Commitment)
def cancelar_commitment(commitment_id: str, payload: CancelarCommitmentRequest) -> Commitment:
    """Cancela un commitment ya aprobado — ej. Volta encontró una mejor
    oferta con otro transportista y le avisa al primero que no sigue
    en pie. No se borra: queda marcado como cancelado, con motivo, y
    el trail auditable guarda el evento. Después de esto, el guardrail
    ya no lo cuenta como reserva vigente para la operación."""
    commitment = store.commitments.get(commitment_id)
    if not commitment:
        raise HTTPException(404, "commitment no encontrado")
    if not commitment.aprobado:
        raise HTTPException(400, "solo se puede cancelar un commitment que estaba aprobado")
    if commitment.cancelado:
        raise HTTPException(400, "este commitment ya estaba cancelado")

    commitment.cancelado = True
    commitment.cancelado_en = datetime.now(timezone.utc)
    commitment.motivo_cancelacion = payload.motivo
    store.save()
    store.append_audit(
        "commitment_cancelado",
        {
            "operacion_id": commitment.operacion_id,
            "commitment_id": commitment.id,
            "motivo": payload.motivo,
        },
    )
    return commitment


# ---------------------------------------------------------------------------
# Llamadas — historial + resumen_sugerido del "modo escucha"
# ---------------------------------------------------------------------------

@app.post("/llamadas", response_model=CallLogEntry)
def registrar_llamada(payload: CallLogEntryCreate) -> CallLogEntry:
    entry = CallLogEntry(**payload.model_dump())
    store.llamadas[entry.id] = entry
    store.save()
    if entry.resumen_sugerido:
        store.append_audit(
            "resumen_sugerido_generado",
            {"operacion_id": entry.operacion_id, "call_id": entry.id},
        )
    return entry


@app.get("/operaciones/{operacion_id}/llamadas", response_model=List[CallLogEntry])
def listar_llamadas(operacion_id: str) -> List[CallLogEntry]:
    return [l for l in store.llamadas.values() if l.operacion_id == operacion_id]


# ---------------------------------------------------------------------------
# Trail auditable — para la vista del referente
# ---------------------------------------------------------------------------

@app.get("/operaciones/{operacion_id}/trail")
def trail_auditable(operacion_id: str) -> List[dict]:
    return store.read_audit_trail(operacion_id)


# ---------------------------------------------------------------------------
# Debug — para poder rehearsar el trial by fire sin borrar archivos a mano
# ---------------------------------------------------------------------------

@app.post("/debug/reset")
def reset_todo() -> dict:
    store.reset()
    return {"status": "reseteado"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

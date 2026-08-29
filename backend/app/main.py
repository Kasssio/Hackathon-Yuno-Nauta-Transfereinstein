"""
API mínima del backend (Bloques 2-3 del roadmap).

Endpoints pensados para 3 consumidores distintos:
- El agente de Sofía/Marcos: POST /commitments (la tool `record_commitment`
  le pega acá), y GET /mandatos/{id} para chequear el mandato antes de negociar.
- El dashboard de Juan Nicolás: GET /operaciones/{id}, GET /commitments,
  GET /trail (para las vistas humano / merchant / auditor).
- Los jueces en el trial by fire: POST /mandatos/{id}/revocar, para
  revocar el mandato en vivo y ver si el agente reacciona bien.

Correr con: uvicorn app.main:app --reload --port 8000
Docs interactivas (Swagger) en: http://localhost:8000/docs
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException

from .guardrail import validate_commitment
from .models import (
    Commitment,
    CommitmentCreate,
    Mandato,
    MandatoCreate,
    Operacion,
    OperacionCreate,
    CallLogEntry,
)
from .storage import store

app = FastAPI(title="Challenge 4 — The Agent on the Line — backend")


# ---------------------------------------------------------------------------
# Operaciones
# ---------------------------------------------------------------------------

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
# Commitments — acá pega la tool `record_commitment` del agente
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


# ---------------------------------------------------------------------------
# Llamadas (historial simple — se completa en el Bloque 4)
# ---------------------------------------------------------------------------

@app.post("/llamadas", response_model=CallLogEntry)
def registrar_llamada(entry: CallLogEntry) -> CallLogEntry:
    store.llamadas[entry.id] = entry
    store.save()
    return entry


# ---------------------------------------------------------------------------
# Trail auditable — para la vista del auditor
# ---------------------------------------------------------------------------

@app.get("/operaciones/{operacion_id}/trail")
def trail_auditable(operacion_id: str) -> List[dict]:
    return store.read_audit_trail(operacion_id)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

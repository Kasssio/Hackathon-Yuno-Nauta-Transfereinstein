"""
Los "schemas" del proyecto: los moldes de datos.

Un schema no es más que: "esta cosa tiene estos campos, y cada campo
guarda este tipo de valor". Pydantic (la librería que usamos) obliga
a que los datos respeten ese molde, y si algo no encaja, avisa con un
error claro en vez de romper en silencio más adelante.

Las 4 "cosas" del dominio (Challenge 4 — The Agent on the Line):

- Mandato: la autorización que el humano le da al agente Volta para
  negociar por teléfono (tope de precio, ventana de fechas, hasta cuándo
  es válido).
- Operacion: el embarque que se está gestionando (contenedor, puerto,
  destino).
- Commitment: lo que Volta acuerda en una llamada (con quién, cuánto,
  para cuándo) — esto es lo que el guardrail valida antes de aceptarlo.
- CallLogEntry: el registro de cada llamada (para el trail auditable).
  Cuando la llamada es escalada, Volta puede quedar en "modo escucha" y
  dejar un `resumen_sugerido` — un borrador de commitment que el
  referente revisa y confirma desde el dashboard (eso dispara un
  POST /commitments normal, con el guardrail de siempre).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _new_id() -> str:
    return uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Mandato
# ---------------------------------------------------------------------------

class MandatoCreate(BaseModel):
    """Lo que el humano completa para crear un mandato."""

    operacion_id: str
    tope_precio: float = Field(..., gt=0, description="Monto máximo permitido, en MXN")
    ventana_inicio: date
    ventana_fin: date
    condiciones: List[str] = Field(
        default_factory=list,
        description='Reglas extra en texto libre, ej. "hasta 3 veces al mes"',
    )
    vigente_hasta: datetime


class Mandato(MandatoCreate):
    """El mandato ya guardado, con su estado."""

    id: str = Field(default_factory=_new_id)
    revocado: bool = False
    revocado_en: Optional[datetime] = None
    creado_en: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Operacion
# ---------------------------------------------------------------------------

class OperacionCreate(BaseModel):
    cliente: str
    contenedor_id: str
    puerto_origen: str
    destino: str
    eta: Optional[date] = None


class Operacion(OperacionCreate):
    id: str = Field(default_factory=_new_id)
    mandato_id: Optional[str] = None
    creado_en: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Cotizacion — una oferta de un transportista, SIN comprometerse todavía.
#
# La consigna pide explícitamente "several negotiations, one best choice":
# Volta tiene que poder cotizar con varios transportistas y recién comprometerse
# con el mejor. Esto es justo lo que separa "cotizar" (esto) de "cerrar el trato"
# (Commitment, abajo) — cotizar no pasa por el guardrail porque no compromete
# nada todavía, no hay riesgo de mandato que cuidar.
# ---------------------------------------------------------------------------

class CotizacionCreate(BaseModel):
    operacion_id: str
    call_id: str
    contraparte: str
    monto: float = Field(..., gt=0)
    fecha_retiro: date
    detalle: str = ""


# ---------------------------------------------------------------------------
# Commitment
# ---------------------------------------------------------------------------

class TipoCommitment(str, Enum):
    reserva = "reserva"
    reprogramacion = "reprogramacion"
    otro = "otro"


class CommitmentCreate(BaseModel):
    """Lo que el agente manda cuando cierra un acuerdo en una llamada.

    Esto es el body que va a pegarle la tool `record_commitment` del
    agente (la que arma Sofía) al endpoint POST /commitments — y
    también lo que postea el referente a mano cuando confirma un
    `resumen_sugerido` de una llamada escalada.
    """

    operacion_id: str
    mandato_id: str
    call_id: str
    contraparte: str = Field(..., description="Transportista o chofer con quien se acordó")
    tipo: TipoCommitment
    monto: float = Field(..., gt=0)
    fecha_retiro: date
    detalle: str = ""


class Commitment(CommitmentCreate):
    id: str = Field(default_factory=_new_id)
    creado_en: datetime = Field(default_factory=_now)
    aprobado: bool
    motivo_rechazo: Optional[str] = None
    # Un commitment aprobado puede cancelarse después (ej. apareció una
    # oferta mejor con otro transportista) — se guarda como cancelado,
    # nunca se borra, así el trail auditable conserva la historia completa.
    cancelado: bool = False
    cancelado_en: Optional[datetime] = None
    motivo_cancelacion: Optional[str] = None


class CancelarCommitmentRequest(BaseModel):
    motivo: str = ""


# ---------------------------------------------------------------------------
# Historial de llamadas
# ---------------------------------------------------------------------------

class ResumenSugerido(BaseModel):
    """Borrador de commitment que arma Volta en 'modo escucha' durante
    una llamada escalada. No se guarda como Commitment todavía — el
    referente lo revisa en el dashboard y lo confirma (eso sí dispara
    el POST /commitments real, con el guardrail de siempre)."""

    contraparte: str = ""
    monto: Optional[float] = None
    fecha_retiro: Optional[date] = None
    detalle: str = ""


class CallLogEntryCreate(BaseModel):
    operacion_id: str
    call_id: str
    direccion: str  # "saliente" | "entrante"
    contraparte: str
    resumen: str = ""
    escalado: bool = False
    motivo_escalacion: Optional[str] = None
    resumen_sugerido: Optional[ResumenSugerido] = None


class CallLogEntry(CallLogEntryCreate):
    id: str = Field(default_factory=_new_id)
    inicio: datetime = Field(default_factory=_now)
    fin: Optional[datetime] = None
    commitments_ids: List[str] = Field(default_factory=list)
    creado_en: datetime = Field(default_factory=_now)

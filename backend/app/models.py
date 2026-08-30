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

from pydantic import BaseModel, Field, model_validator


def _new_id() -> str:
    return uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Horarios en texto libre tipo reloj de 24hs, ej. "09:00" o "17:30" — mismo
# criterio simple que las fechas (string validado con regex, no un tipo
# `time` con zona horaria propia: la demo no lo necesita).
_PATRON_HORA = r"^([01]\d|2[0-3]):[0-5]\d$"


# ---------------------------------------------------------------------------
# Mandato
# ---------------------------------------------------------------------------

class MandatoCreate(BaseModel):
    """Lo que el humano completa para crear un mandato."""

    operacion_id: str
    tope_precio: float = Field(..., gt=0, description="Monto máximo permitido, en MXN — el techo duro")
    tarifa_objetivo: Optional[float] = Field(
        None,
        gt=0,
        description=(
            "Monto al que Volta debería intentar cerrar primero, en MXN. Es distinto del "
            "tope: el tope es el límite duro que nunca se cruza, el objetivo es la meta que "
            "se persigue antes de acercarse al tope. Opcional — si no se define, el motor de "
            "negociación usa un objetivo derivado del tope (ver negotiation.py)."
        ),
    )
    ventana_inicio: date
    ventana_fin: date
    horario_inicio: Optional[str] = Field(
        None,
        pattern=_PATRON_HORA,
        description=(
            'Hora más temprana permitida para el retiro, formato 24hs "HH:MM" (ej. "09:00"). '
            "Aplica a TODOS los días de la ventana — no es un horario distinto por fecha, es "
            "el rango horario del día que sea. Opcional: si no se define (junto con "
            "horario_fin), no hay restricción de horario, solo de fecha."
        ),
    )
    horario_fin: Optional[str] = Field(None, pattern=_PATRON_HORA, description="Hora más tardía permitida, mismo formato que horario_inicio.")
    condiciones: List[str] = Field(
        default_factory=list,
        description=(
            'Reglas extra en texto libre, ej. "hasta 3 veces al mes". Estas condiciones son '
            "siempre NO negociables — es lo mismo que el precio tope y la ventana: una "
            "restricción que el humano autorizó, no una variable de la que Volta pueda ceder "
            "a cambio de mejorar la tarifa."
        ),
    )
    vigente_hasta: datetime

    @model_validator(mode="after")
    def _objetivo_nunca_supera_el_tope(self) -> "MandatoCreate":
        if self.tarifa_objetivo is not None and self.tarifa_objetivo > self.tope_precio:
            raise ValueError("tarifa_objetivo no puede ser mayor que tope_precio")
        return self

    @model_validator(mode="after")
    def _horario_completo_y_coherente(self) -> "MandatoCreate":
        tiene_inicio, tiene_fin = self.horario_inicio is not None, self.horario_fin is not None
        if tiene_inicio != tiene_fin:
            raise ValueError("horario_inicio y horario_fin van juntos: los dos o ninguno")
        if tiene_inicio and self.horario_inicio > self.horario_fin:  # type: ignore[operator]
            raise ValueError("horario_inicio no puede ser posterior a horario_fin")
        return self


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
    prioridades: List[str] = Field(
        default_factory=lambda: ["precio"],
        description=(
            'Qué le importa a esta operación al comparar candidatos y al negociar, en orden, '
            'ej. ["precio", "puntualidad"]. El motor de negociación lo usa para inclinar la '
            'estrategia (ej. si "velocidad" es prioridad, tiende antes a modo CIERRE).'
        ),
    )


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
    hora_retiro: Optional[str] = Field(None, pattern=_PATRON_HORA, description='Hora del retiro ofrecida, "HH:MM" 24hs, si ya se habló — opcional en esta etapa, todavía no compromete nada.')
    metodo_pago: Optional[str] = Field(
        None,
        description=(
            "Forma de pago acordada con el transportista, confirmada en voz al "
            "cerrar. Sale de metodos_pago del catálogo; None si no se habló."
        ),
    )
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
    hora_retiro: str = Field(..., pattern=_PATRON_HORA, description='Hora acordada del retiro, formato 24hs "HH:MM" — un commitment agenda el día Y la hora, nunca solo el día.')
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
    hora_retiro: Optional[str] = Field(None, pattern=_PATRON_HORA)
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


# ---------------------------------------------------------------------------
# Negociación — el motor estructurado (ver app/negotiation.py).
#
# Separación deliberada: el LLM decide CÓMO conversar (tono, cuándo hacer una
# pregunta aclaratoria, cómo frasear); estos modelos y negotiation.py deciden
# QUÉ está permitido (qué monto se puede ofrecer, cuándo aceptar, cuándo
# cortar). Ningún modelo de acá contiene texto para que Volta recite palabra
# por palabra — `motivo_interno` es para logs y para que Volta entienda el
# porqué, nunca un guion.
#
# Fuente única de verdad: el máximo SIEMPRE sale de Mandato.tope_precio (ver
# arriba) y las condiciones no negociables SIEMPRE de Mandato.condiciones —
# nada acá los duplica.
# ---------------------------------------------------------------------------

class EstrategiaModo(str, Enum):
    """Modifica la postura de la negociación. Nunca modifica una regla dura
    (tope, ventana, condiciones no negociables) — eso es competencia
    exclusiva del guardrail y del motor, no de la estrategia."""

    firme = "firme"  # muchas alternativas, baja urgencia
    equilibrado = "equilibrado"  # situación intermedia
    cierre = "cierre"  # pocas alternativas, alta urgencia o alto riesgo de perder la operación


class TipoRespuestaConductor(str, Enum):
    """Cómo el LLM clasifica lo que acaba de escuchar — esto SÍ es criterio
    del modelo (entender lenguaje natural es su trabajo); lo que se hace con
    esa clasificación es 100% del motor."""

    rechazo = "rechazo"
    contraoferta = "contraoferta"
    concesion = "concesion"
    aceptacion = "aceptacion"
    aceptacion_ambigua = "aceptacion_ambigua"
    condicion = "condicion"
    solicitud_info = "solicitud_info"
    cancelacion = "cancelacion"
    escalacion_necesaria = "escalacion_necesaria"


class IntencionNegociacion(str, Enum):
    """Lo que Volta puede hacer a continuación. La devuelve el motor, no el
    LLM — el LLM solo la ejecuta (y la frasea con sus propias palabras)."""

    ask_better_rate = "ASK_BETTER_RATE"
    propose_target = "PROPOSE_TARGET"
    counteroffer = "COUNTEROFFER"
    trade_condition = "TRADE_CONDITION"
    accept_and_confirm = "ACCEPT_AND_CONFIRM"
    reject_and_move_on = "REJECT_AND_MOVE_ON"
    request_clarification = "REQUEST_CLARIFICATION"
    escalate = "ESCALATE"


class MotivoFinalizacion(str, Enum):
    acuerdo = "acuerdo"
    maximo_alcanzado = "maximo_alcanzado"
    conductor_no_baja = "conductor_no_baja"
    sin_progreso = "sin_progreso"
    circular = "circular"
    tiempo_insuficiente = "tiempo_insuficiente"
    mejor_alternativa = "mejor_alternativa"
    condicion_fuera_de_autorizacion = "condicion_fuera_de_autorizacion"
    escalado = "escalado"
    cancelado = "cancelado"


class RondaNegociacion(BaseModel):
    """Un intercambio: lo que ofreció/dijo el conductor, y lo que el motor
    autorizó a Volta a hacer en respuesta. Es el registro — nunca el
    razonamiento interno del modelo, que no se guarda."""

    numero: int
    tipo_respuesta_conductor: TipoRespuestaConductor
    oferta_conductor: Optional[float] = None
    condicion_propuesta: Optional[str] = None
    intencion_volta: IntencionNegociacion
    oferta_volta: Optional[float] = None
    estrategia: EstrategiaModo
    motivo_interno: str = ""
    creado_en: datetime = Field(default_factory=_now)


class OfertaEntrante(BaseModel):
    """Lo que manda la tool `evaluar_negociacion` del agente — el body de
    POST /negociacion/evaluar. Mismo principio que el resto del contrato: el
    modelo nunca maneja ids técnicos más que los que ya conoce por otras
    tools (operacion_id, call_id, candidato_id ya se los completa el
    cliente, no el LLM)."""

    operacion_id: str
    call_id: str
    contraparte: str
    candidato_id: Optional[str] = None
    tipo_respuesta: TipoRespuestaConductor
    monto: Optional[float] = Field(None, gt=0, description="Monto que mencionó el conductor, si mencionó uno")
    variable_condicion: Optional[str] = Field(
        None, description='Qué quiere tradear, ej. "horario", "fecha_dentro_de_ventana". Solo para tipo_respuesta="condicion"'
    )
    condicion_propuesta: Optional[str] = Field(None, description="Detalle en texto libre de la condición propuesta")
    candidatos_restantes: Optional[int] = Field(
        None, ge=0, description="Cuántos otros candidatos válidos quedan por probar en esta ronda, si se sabe"
    )
    mejor_alternativa_monto: Optional[float] = Field(
        None,
        gt=0,
        description=(
            "Si ya existe una cotización mejor con otro candidato (ver request_quote), el "
            "monto de esa alternativa — permite cortar acá y priorizarla en vez de seguir "
            "negociando contra un techo que ya se sabe innecesario."
        ),
    )


class DecisionNegociacion(BaseModel):
    """Lo que devuelve el motor — la autoridad final. Volta puede decidir
    CÓMO decir esto, nunca cambiar el monto ni la intención."""

    intencion: IntencionNegociacion
    monto_a_comunicar: Optional[float] = None
    condicion_aprobada: bool = False
    finalizar: bool
    motivo_finalizacion: Optional[MotivoFinalizacion] = None
    estrategia: EstrategiaModo
    ronda: int
    motivo_interno: str = ""


class EstadoNegociacion(BaseModel):
    """Memoria de la negociación en curso para UNA llamada con UNA
    contraparte — se crea sola en la primera ronda y vive en el Store igual
    que el resto del estado (nada de infraestructura nueva)."""

    id: str = Field(default_factory=_new_id)
    operacion_id: str
    mandato_id: str
    call_id: str
    contraparte: str
    candidato_id: Optional[str] = None
    activa: bool = True
    tarifa_inicial_conductor: Optional[float] = None
    ultima_oferta_conductor: Optional[float] = None
    ultima_oferta_volta: Optional[float] = None
    rondas: List[RondaNegociacion] = Field(default_factory=list)
    estrategia_actual: EstrategiaModo = EstrategiaModo.equilibrado
    motivo_finalizacion: Optional[MotivoFinalizacion] = None
    creado_en: datetime = Field(default_factory=_now)
    actualizado_en: datetime = Field(default_factory=_now)

"""
El motor de negociación — código determinístico, sin LLM, igual que
`guardrail.py` (que es su vecino y su fuente de verdad para el límite duro).

Principio de arquitectura (pedido explícito de Sofía): el LLM decide CÓMO
conversar — tono, cuándo pedir una aclaración, cómo frasear una frase. Este
módulo decide QUÉ está permitido — qué monto se puede ofrecer, cuándo
aceptar, cuándo cortar. El LLM nunca calcula un monto: se lo pide a
`evaluar_oferta` (vía POST /negociacion/evaluar) y usa exactamente lo que le
devuelve.

Como el guardrail, esto es una función aislada y testeable sin voz ni red:
recibe objetos ya armados (Mandato, EstadoNegociacion, OfertaEntrante) y
devuelve una decisión. No toca el Store ni hace requests — eso es trabajo
de `main.py`.

Fuente única de verdad: el tope siempre sale de `Mandato.tope_precio`, la
ventana de `Mandato.ventana_inicio/fin`, y las condiciones no negociables de
`Mandato.condiciones`. Este módulo no duplica ninguna de esas reglas — las
lee y las aplica.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional, Sequence

from .models import (
    DecisionNegociacion,
    EstadoNegociacion,
    EstrategiaModo,
    IntencionNegociacion,
    Mandato,
    MotivoFinalizacion,
    OfertaEntrante,
    TipoRespuestaConductor,
)

# ---------------------------------------------------------------------------
# Constantes de la política de negociación — todas acá, ningún número mágico
# repetido en otro lado. Cambiar la política es cambiar esta sección.
# ---------------------------------------------------------------------------

# Si no se definió tarifa_objetivo en el mandato, se deriva del tope con este
# ratio (objetivo = tope * ratio). 0.94 sobre un tope de $450 da $423 —
# cerca del objetivo del ejemplo sin hardcodear ese número.
DEFAULT_OBJETIVO_RATIO = 0.94

# Escalera de concesión: en qué fracción del camino entre objetivo y máximo
# está Volta autorizado a ofrecer en cada ronda de esa estrategia. Ronda 1
# siempre es 0.0 (el objetivo); el último valor siempre es 1.0 (el máximo,
# nunca más que eso). CIERRE tiene menos rondas — "alta urgencia → menos
# rondas y mayor velocidad" — pero el máximo nunca cambia con la urgencia.
ESCALERA_CONCESION: dict[EstrategiaModo, list[float]] = {
    EstrategiaModo.firme: [0.0, 0.35, 0.70, 1.0],
    EstrategiaModo.equilibrado: [0.0, 0.5, 1.0],
    EstrategiaModo.cierre: [0.0, 1.0],
}

UMBRAL_URGENCIA_MINUTOS = 240  # 4 horas — mismo umbral que reemplazo urgente
MAX_RONDAS_SIN_ACUERDO = 8  # protección adicional, no el criterio principal
UMBRAL_CIRCULAR = 2  # repeticiones idénticas consecutivas antes de cortar


@dataclass
class ContextoEstrategia:
    """Lo que hace falta para elegir postura. Nada de esto es una regla
    dura — solo modifica CÓMO se negocia dentro de lo ya autorizado."""

    candidatos_restantes: Optional[int] = None
    tiempo_restante_minutos: Optional[float] = None


def calcular_estrategia(contexto: ContextoEstrategia) -> EstrategiaModo:
    """FIRME si hay margen y no hay apuro. CIERRE si no queda margen (última
    alternativa) o el tiempo se acaba. EQUILIBRADO en cualquier otro caso.
    La urgencia y la escasez de alternativas SOLO llegan hasta acá — nunca
    tocan el tope, eso vive exclusivamente en `Mandato.tope_precio`."""

    urgente = (
        contexto.tiempo_restante_minutos is not None
        and contexto.tiempo_restante_minutos <= UMBRAL_URGENCIA_MINUTOS
    )
    ultima_alternativa = contexto.candidatos_restantes is not None and contexto.candidatos_restantes <= 0

    if ultima_alternativa or urgente:
        return EstrategiaModo.cierre
    if contexto.candidatos_restantes is not None and contexto.candidatos_restantes >= 2:
        return EstrategiaModo.firme
    return EstrategiaModo.equilibrado


def _objetivo_y_maximo(mandato: Mandato) -> tuple[float, float]:
    maximo = mandato.tope_precio
    objetivo = mandato.tarifa_objetivo or round(maximo * DEFAULT_OBJETIVO_RATIO, 2)
    # Blindaje: objetivo nunca puede terminar por encima del máximo, pase lo
    # que pase con cómo se configuró el mandato (MandatoCreate ya lo valida
    # al crearse, esto es la segunda capa — nunca confiar en una sola).
    objetivo = min(objetivo, maximo)
    return objetivo, maximo


def _paso_actual(estado: EstadoNegociacion, estrategia: EstrategiaModo) -> int:
    """Cuántos pasos de la escalera ya se usaron para ESTA estrategia. Si la
    estrategia cambió de ronda a ronda (ej. se quedó sin alternativas a
    mitad de negociación y pasó a CIERRE), no reinicia el conteo: cuenta
    cuántas rondas con oferta de Volta ya hubo, así nunca se retrocede."""

    return sum(1 for r in estado.rondas if r.oferta_volta is not None)


def _redondear_a_multiplo_de_10(monto: float, tope: float) -> float:
    """Volta negocia como negociaría una persona: en números redondos, no
    con decimales de cálculo interno. Esto SOLO se aplica a un monto que
    Volta mismo propone (paso de la escalera) — nunca a un monto que ya
    dijo la contraparte y que Volta simplemente acepta tal cual (ver
    `es_oferta_aceptable` en `evaluar_oferta`, que usa `monto_conductor`
    directo, sin pasar por acá). Redondeo hacia el múltiplo de 10 más
    cercano (mitad para arriba); si eso cae por encima del tope, se
    redondea para abajo en su lugar — el redondeo nunca puede ser la
    forma en que una propuesta termina superando lo autorizado."""

    redondeado = math.floor(monto / 10 + 0.5) * 10
    if redondeado > tope:
        redondeado = math.floor(tope / 10) * 10
    return float(redondeado)


def _monto_en_paso(paso: int, estrategia: EstrategiaModo, objetivo: float, maximo: float) -> float:
    escalera = ESCALERA_CONCESION[estrategia]
    fraccion = escalera[min(paso, len(escalera) - 1)]
    monto = objetivo + fraccion * (maximo - objetivo)
    monto = min(monto, maximo)  # el clamp del paso: nunca > maximo, pase lo que pase
    return _redondear_a_multiplo_de_10(monto, maximo)


def _hubo_concesion_del_conductor(estado: EstadoNegociacion, monto_actual: Optional[float]) -> bool:
    """True si el conductor bajó respecto de lo último que dijo. Sin dato
    previo, no hay manera de saber que cedió — se trata como que no cedió
    (postura conservadora: nunca regalar una concesión de Volta a cambio de
    nada)."""

    if monto_actual is None or estado.ultima_oferta_conductor is None:
        return False
    return monto_actual < estado.ultima_oferta_conductor


def _es_repeticion_circular(estado: EstadoNegociacion, monto_conductor: Optional[float], monto_volta_propuesto: float) -> bool:
    if len(estado.rondas) < UMBRAL_CIRCULAR:
        return False
    ultimas = estado.rondas[-UMBRAL_CIRCULAR:]
    mismo_conductor = all(r.oferta_conductor == monto_conductor for r in ultimas) and monto_conductor is not None
    mismo_volta = all(r.oferta_volta == monto_volta_propuesto for r in ultimas)
    return mismo_conductor and mismo_volta


_STOPWORDS_CONDICION = {
    "para", "esta", "este", "esto", "pero", "como", "hasta", "desde",
    "sobre", "cada", "solo", "sólo", "puede", "puedo", "podemos", "nunca",
    "siempre", "veces", "hace", "hacer", "tiene", "debe", "pide", "pidió",
    "quiere", "quiso", "dice", "dijo",
}


def _palabras_clave(texto: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-záéíóúñ]+", texto.lower())
        if len(w) > 3 and w not in _STOPWORDS_CONDICION
    }


def _condicion_es_no_negociable(mandato: Mandato, variable: Optional[str], detalle: Optional[str]) -> bool:
    """Heurística deliberadamente simple y honesta, no NLP: compara
    palabras clave (sin stopwords ni mayúsculas) entre lo que propone
    tradear el conductor y cada condición no negociable del mandato — si
    comparten alguna palabra de contenido, se trata como la misma
    restricción. Puede dar falsos positivos con palabras comunes o falsos
    negativos con frases totalmente distintas para lo mismo — está
    documentado, no pretende ser más que eso. Lo que sí es absoluto pase lo
    que pase acá: el precio y la ventana de fechas jamás pueden tradearse,
    eso ya lo bloquea el guardrail en record_commitment sin depender de
    esta heurística."""

    candidatos_texto = [t for t in (variable, detalle) if t]
    if not candidatos_texto:
        return False
    palabras_pedido = _palabras_clave(" ".join(candidatos_texto))
    if not palabras_pedido:
        return False
    return any(palabras_pedido & _palabras_clave(cond) for cond in mandato.condiciones)


def debe_finalizar(
    estado: EstadoNegociacion,
    entrante: OfertaEntrante,
    contexto: ContextoEstrategia,
    *,
    objetivo: float,
    maximo: float,
    proximo_monto_volta: float,
    ya_en_el_ultimo_paso: bool,
) -> Optional[MotivoFinalizacion]:
    """Chequea TODAS las condiciones de corte antes de dejar que la
    negociación siga. El contador de rondas es una protección adicional, no
    el criterio principal — por eso va último, no primero."""

    if contexto.tiempo_restante_minutos is not None and contexto.tiempo_restante_minutos <= 0:
        return MotivoFinalizacion.tiempo_insuficiente

    if entrante.mejor_alternativa_monto is not None and entrante.mejor_alternativa_monto <= objetivo and len(estado.rondas) >= 1:
        return MotivoFinalizacion.mejor_alternativa

    if entrante.tipo_respuesta == TipoRespuestaConductor.rechazo:
        sin_monto = entrante.monto is None
        # Ya estábamos en el máximo y de nuevo dice que no, sin ceder nada.
        if ya_en_el_ultimo_paso and estado.ultima_oferta_volta is not None and estado.ultima_oferta_volta >= maximo:
            return MotivoFinalizacion.maximo_alcanzado
        # Dos rechazos seguidos sin ofrecer ningún número — no va a bajar.
        if sin_monto and len(estado.rondas) >= 1 and estado.rondas[-1].tipo_respuesta_conductor == TipoRespuestaConductor.rechazo:
            return MotivoFinalizacion.conductor_no_baja

    if _es_repeticion_circular(estado, entrante.monto, proximo_monto_volta):
        return MotivoFinalizacion.circular

    if len(estado.rondas) + 1 > MAX_RONDAS_SIN_ACUERDO:
        return MotivoFinalizacion.sin_progreso

    return None


def evaluar_oferta(
    estado: EstadoNegociacion,
    mandato: Mandato,
    entrante: OfertaEntrante,
    contexto: Optional[ContextoEstrategia] = None,
) -> DecisionNegociacion:
    """El entrypoint. Recibe el estado de la negociación hasta ahora, el
    mandato vigente, y lo que acaba de pasar en la llamada — devuelve la
    única decisión válida. `main.py` es quien persiste el resultado como una
    nueva `RondaNegociacion`; esta función no muta nada."""

    if mandato.id != estado.mandato_id:
        raise ValueError("el estado de negociación no corresponde a este mandato")

    contexto = contexto or ContextoEstrategia()
    objetivo, maximo = _objetivo_y_maximo(mandato)
    estrategia = calcular_estrategia(contexto)
    ronda = len(estado.rondas) + 1

    # -- Casos que no son sobre precio: se resuelven antes que nada ---------

    if entrante.tipo_respuesta == TipoRespuestaConductor.cancelacion:
        return DecisionNegociacion(
            intencion=IntencionNegociacion.reject_and_move_on,
            finalizar=True,
            motivo_finalizacion=MotivoFinalizacion.cancelado,
            estrategia=estrategia,
            ronda=ronda,
            motivo_interno="el conductor canceló/se bajó de la negociación",
        )

    if entrante.tipo_respuesta == TipoRespuestaConductor.escalacion_necesaria:
        return DecisionNegociacion(
            intencion=IntencionNegociacion.escalate,
            finalizar=True,
            motivo_finalizacion=MotivoFinalizacion.escalado,
            estrategia=estrategia,
            ronda=ronda,
            motivo_interno="se detectó una situación que requiere escalar a un humano",
        )

    if entrante.tipo_respuesta == TipoRespuestaConductor.aceptacion_ambigua:
        return DecisionNegociacion(
            intencion=IntencionNegociacion.request_clarification,
            monto_a_comunicar=estado.ultima_oferta_volta,
            finalizar=False,
            estrategia=estrategia,
            ronda=ronda,
            motivo_interno="la aceptación no fue explícita — hace falta confirmar antes de cerrar",
        )

    if entrante.tipo_respuesta == TipoRespuestaConductor.condicion:
        if _condicion_es_no_negociable(mandato, entrante.variable_condicion, entrante.condicion_propuesta):
            ultima = contexto.candidatos_restantes is not None and contexto.candidatos_restantes <= 0
            return DecisionNegociacion(
                intencion=IntencionNegociacion.escalate if ultima else IntencionNegociacion.reject_and_move_on,
                finalizar=True,
                motivo_finalizacion=MotivoFinalizacion.condicion_fuera_de_autorizacion,
                estrategia=estrategia,
                ronda=ronda,
                motivo_interno="la condición pedida está fuera de lo que autoriza el mandato",
            )
        return DecisionNegociacion(
            intencion=IntencionNegociacion.trade_condition,
            monto_a_comunicar=estado.ultima_oferta_volta,
            condicion_aprobada=True,
            finalizar=False,
            estrategia=estrategia,
            ronda=ronda,
            motivo_interno="condición negociable, autorizada sin tocar la tarifa vigente",
        )

    if entrante.tipo_respuesta == TipoRespuestaConductor.solicitud_info:
        return DecisionNegociacion(
            intencion=IntencionNegociacion.ask_better_rate if estado.ultima_oferta_volta is None else IntencionNegociacion.propose_target,
            monto_a_comunicar=estado.ultima_oferta_volta,
            finalizar=False,
            estrategia=estrategia,
            ronda=ronda,
            motivo_interno="el conductor pidió información — no cambia la oferta vigente",
        )

    # -- A partir de acá, tipo_respuesta es rechazo / contraoferta /
    #    concesion / aceptacion: hay (o puede haber) un número sobre la mesa.

    if entrante.tipo_respuesta == TipoRespuestaConductor.aceptacion:
        monto_aceptado = entrante.monto if entrante.monto is not None else estado.ultima_oferta_volta
        if monto_aceptado is None or monto_aceptado > maximo:
            # No hay forma válida de que esto sea un "sí" limpio: o no
            # sabemos a qué monto, o excede el máximo (nunca pudo haber
            # salido de Volta) — pedir aclaración, jamás aceptar a ciegas.
            return DecisionNegociacion(
                intencion=IntencionNegociacion.request_clarification,
                finalizar=False,
                estrategia=estrategia,
                ronda=ronda,
                motivo_interno="aceptación sin un monto válido y verificable — no se confirma sin aclarar",
            )
        return DecisionNegociacion(
            intencion=IntencionNegociacion.accept_and_confirm,
            monto_a_comunicar=monto_aceptado,
            finalizar=True,
            motivo_finalizacion=MotivoFinalizacion.acuerdo,
            estrategia=estrategia,
            ronda=ronda,
            motivo_interno="acuerdo alcanzado dentro del mandato",
        )

    # rechazo / contraoferta / concesion con (o sin) un monto del conductor.
    monto_conductor = entrante.monto
    es_oferta_aceptable = monto_conductor is not None and monto_conductor <= objetivo

    paso_ya_dado = _paso_actual(estado, estrategia)
    escalon_final = len(ESCALERA_CONCESION[estrategia]) - 1

    if es_oferta_aceptable:
        # Mejor que (o igual a) el propio objetivo — se acepta tal cual la
        # ofreció, no hace falta seguir exprimiendo un buen trato.
        proximo_monto = monto_conductor
        paso_a_usar = paso_ya_dado
        ultimo_paso = True
    else:
        # Reciprocidad: si el conductor no cedió nada respecto de su propia
        # oferta anterior, Volta tampoco avanza un escalón — se mantiene en
        # el mismo punto ya ofrecido (o en el objetivo, si es la ronda 1).
        if paso_ya_dado > 0 and not _hubo_concesion_del_conductor(estado, monto_conductor):
            paso_a_usar = paso_ya_dado - 1
        else:
            paso_a_usar = paso_ya_dado
        proximo_monto = _monto_en_paso(paso_a_usar, estrategia, objetivo, maximo)
        ultimo_paso = paso_a_usar >= escalon_final

    motivo_corte = debe_finalizar(
        estado,
        entrante,
        contexto,
        objetivo=objetivo,
        maximo=maximo,
        proximo_monto_volta=proximo_monto,
        ya_en_el_ultimo_paso=ultimo_paso,
    )

    if motivo_corte is not None:
        return DecisionNegociacion(
            intencion=(
                IntencionNegociacion.escalate
                if motivo_corte == MotivoFinalizacion.tiempo_insuficiente
                else IntencionNegociacion.reject_and_move_on
            ),
            monto_a_comunicar=None,
            finalizar=True,
            motivo_finalizacion=motivo_corte,
            estrategia=estrategia,
            ronda=ronda,
            motivo_interno=f"negociación cortada: {motivo_corte.value}",
        )

    if es_oferta_aceptable:
        return DecisionNegociacion(
            intencion=IntencionNegociacion.accept_and_confirm,
            monto_a_comunicar=proximo_monto,
            finalizar=True,
            motivo_finalizacion=MotivoFinalizacion.acuerdo,
            estrategia=estrategia,
            ronda=ronda,
            motivo_interno="el conductor ofreció igual o menos que el objetivo — se acepta",
        )

    intencion = IntencionNegociacion.propose_target if paso_a_usar == 0 else IntencionNegociacion.counteroffer
    return DecisionNegociacion(
        intencion=intencion,
        monto_a_comunicar=proximo_monto,
        finalizar=False,
        estrategia=estrategia,
        ronda=ronda,
        motivo_interno=(
            f"paso {paso_a_usar + 1}/{len(ESCALERA_CONCESION[estrategia])} de la escalera "
            f"{estrategia.value} — {'con' if paso_a_usar == paso_ya_dado else 'sin'} concesión recíproca"
        ),
    )

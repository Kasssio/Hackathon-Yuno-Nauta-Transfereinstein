"""
El guardrail de mandato — riesgo #1 del roadmap.

Esta es la pieza más importante de todo el backend: la función que
decide si un commitment que Volta quiere cerrar por teléfono se
puede aprobar, o si hay que rechazarlo / escalarlo a un humano.

A propósito NO usa el LLM para esta decisión. Es código determinístico
y aburrido: monto <= tope AND fecha dentro de la ventana AND mandato
vigente y no revocado AND no es una reserva duplicada. Así, pase lo
que pase en la conversación (el interlocutor insiste, ofrece algo
"especial", confunde al agente), la decisión final siempre pasa por
acá, no por el criterio del modelo.

Sigue siendo una función aislada y testeable sin voz ni LLM: recibe
el mandato y (opcionalmente) los commitments previos de la operación
como simples listas de objetos — no toca la base de datos ni hace
llamadas de red.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from .models import Commitment, CommitmentCreate, Mandato, TipoCommitment


@dataclass
class GuardrailResult:
    aprobado: bool
    motivo: str  # "" si aprobado; explicación corta si no


def validate_commitment(
    commitment: CommitmentCreate,
    mandato: Mandato,
    commitments_previos: Sequence[Commitment] = (),
) -> GuardrailResult:
    """Valida un commitment contra su mandato. No modifica nada, solo decide.

    `commitments_previos` son los commitments ya registrados para la
    MISMA operación (aprobados o no) — se usan para detectar el
    intento adversarial de "partir la compra" en varias llamadas para
    esquivar el tope de precio (bonus del brief: "defensa ante un
    agente adversarial intentando comprar fuera de su mandato por
    caminos creativos").
    """

    if mandato.id != commitment.mandato_id:
        return GuardrailResult(False, "el commitment no referencia este mandato")

    if mandato.revocado:
        return GuardrailResult(False, "mandato revocado")

    ahora = datetime.now(timezone.utc)
    vigente_hasta = mandato.vigente_hasta
    if vigente_hasta.tzinfo is None:
        vigente_hasta = vigente_hasta.replace(tzinfo=timezone.utc)
    if ahora > vigente_hasta:
        return GuardrailResult(False, "mandato expirado")

    if commitment.monto > mandato.tope_precio:
        return GuardrailResult(
            False,
            f"monto {commitment.monto} excede el tope del mandato ({mandato.tope_precio})",
        )

    if not (mandato.ventana_inicio <= commitment.fecha_retiro <= mandato.ventana_fin):
        return GuardrailResult(
            False,
            f"fecha {commitment.fecha_retiro} fuera de la ventana permitida "
            f"({mandato.ventana_inicio} a {mandato.ventana_fin})",
        )

    if commitment.tipo == TipoCommitment.reserva and _ya_hay_reserva_aprobada(
        commitment.operacion_id, commitments_previos
    ):
        return GuardrailResult(
            False,
            "ya existe una reserva aprobada para esta operación — posible intento de "
            "duplicar o partir la compra en varias llamadas; requiere revisión humana",
        )

    # Las "condiciones" en texto libre (ej. "hasta 3 veces al mes") son el
    # próximo paso: hoy no se evalúan acá todavía. Ver README del backend.

    return GuardrailResult(True, "")


def _ya_hay_reserva_aprobada(operacion_id: str, previos: Iterable[Commitment]) -> bool:
    return any(
        c.operacion_id == operacion_id and c.tipo == TipoCommitment.reserva and c.aprobado
        for c in previos
    )

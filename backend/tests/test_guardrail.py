"""
Tests del guardrail — corré esto primero, no necesita voz ni LLM ni API
levantada. Si estos tests pasan, el riesgo #1 del roadmap (que el agente
rompa el mandato) está cubierto en la capa que manda: el código, no el
criterio del modelo.

Correr con: pytest backend/tests/test_guardrail.py -v
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.guardrail import validate_commitment
from app.models import Commitment, CommitmentCreate, Mandato, TipoCommitment


def _mandato(**overrides) -> Mandato:
    base = dict(
        operacion_id="op1",
        tope_precio=9000.0,
        ventana_inicio=date(2026, 8, 28),
        ventana_fin=date(2026, 8, 30),
        vigente_hasta=datetime.now(timezone.utc) + timedelta(days=1),
        condiciones=[],
    )
    base.update(overrides)
    return Mandato(**base)


def _commitment(mandato: Mandato, **overrides) -> CommitmentCreate:
    base = dict(
        operacion_id=mandato.operacion_id,
        mandato_id=mandato.id,
        call_id="call1",
        contraparte="Transportes del Norte",
        tipo=TipoCommitment.reserva,
        monto=8500.0,
        fecha_retiro=date(2026, 8, 29),
        hora_retiro="10:00",
        detalle="camión para el jueves",
    )
    base.update(overrides)
    return CommitmentCreate(**base)


def test_commitment_dentro_del_mandato_se_aprueba():
    mandato = _mandato()
    commitment = _commitment(mandato)
    resultado = validate_commitment(commitment, mandato)
    assert resultado.aprobado
    assert resultado.motivo == ""


def test_monto_excede_el_tope_se_rechaza():
    mandato = _mandato(tope_precio=9000.0)
    commitment = _commitment(mandato, monto=12000.0)
    resultado = validate_commitment(commitment, mandato)
    assert not resultado.aprobado
    assert "tope" in resultado.motivo


def test_fecha_fuera_de_ventana_se_rechaza():
    mandato = _mandato()
    commitment = _commitment(mandato, fecha_retiro=date(2026, 9, 5))
    resultado = validate_commitment(commitment, mandato)
    assert not resultado.aprobado
    assert "ventana" in resultado.motivo


def test_mandato_revocado_se_rechaza_aunque_este_dentro_de_limites():
    mandato = _mandato(revocado=True)
    commitment = _commitment(mandato)
    resultado = validate_commitment(commitment, mandato)
    assert not resultado.aprobado
    assert "revocado" in resultado.motivo


def test_mandato_expirado_se_rechaza():
    mandato = _mandato(vigente_hasta=datetime.now(timezone.utc) - timedelta(days=1))
    commitment = _commitment(mandato)
    resultado = validate_commitment(commitment, mandato)
    assert not resultado.aprobado
    assert "expirado" in resultado.motivo


def test_segunda_reserva_para_la_misma_operacion_se_rechaza():
    """Cubre el intento adversarial: partir la compra en dos llamadas
    para esquivar el tope (ej. $6.000 + $6.000 contra un tope de $9.000)."""
    mandato = _mandato(tope_precio=9000.0)
    primera = Commitment(
        **_commitment(mandato, monto=6000.0).model_dump(),
        aprobado=True,
    )
    segunda = _commitment(mandato, monto=6000.0, call_id="call2", detalle="cargo adicional")
    resultado = validate_commitment(segunda, mandato, commitments_previos=[primera])
    assert not resultado.aprobado
    assert "reserva" in resultado.motivo


def test_reprogramacion_no_se_bloquea_por_la_reserva_previa():
    """La regla anti-duplicado es solo para tipo=reserva; reprogramar
    el mismo booking (ej. el camión se rompió, se corre a viernes) tiene
    que seguir permitido."""
    mandato = _mandato(tope_precio=9000.0)
    reserva = Commitment(
        **_commitment(mandato, monto=8500.0).model_dump(),
        aprobado=True,
    )
    reprogramacion = _commitment(
        mandato, monto=8500.0, call_id="call2", tipo=TipoCommitment.reprogramacion,
        fecha_retiro=date(2026, 8, 30), detalle="se corre a viernes por rotura de camión",
    )
    resultado = validate_commitment(reprogramacion, mandato, commitments_previos=[reserva])
    assert resultado.aprobado


def test_reserva_cancelada_no_bloquea_una_nueva_reserva():
    """El escenario de la negociación con reconsideración: Volta cierra
    con el transportista 1, encuentra algo mejor con el 2, cancela el
    compromiso con el 1 — y ENTONCES la reserva con el 2 tiene que
    poder aprobarse."""
    mandato = _mandato(tope_precio=9000.0)
    reserva_1 = Commitment(
        **_commitment(mandato, monto=8500.0, contraparte="Transportes del Norte").model_dump(),
        aprobado=True,
        cancelado=True,
    )
    reserva_2 = _commitment(mandato, monto=8200.0, call_id="call2", contraparte="Transportes Express")
    resultado = validate_commitment(reserva_2, mandato, commitments_previos=[reserva_1])
    assert resultado.aprobado


def test_reserva_vigente_sigue_bloqueando_una_segunda():
    """Contraprueba: si la primera reserva NO está cancelada, la regla
    anti-duplicado sigue funcionando como siempre."""
    mandato = _mandato(tope_precio=9000.0)
    reserva_1 = Commitment(
        **_commitment(mandato, monto=8500.0).model_dump(),
        aprobado=True,
        cancelado=False,
    )
    reserva_2 = _commitment(mandato, monto=8200.0, call_id="call2")
    resultado = validate_commitment(reserva_2, mandato, commitments_previos=[reserva_1])
    assert not resultado.aprobado


# ---------------------------------------------------------------------------
# Horario del retiro — variable nueva junto a la fecha: un commitment
# agenda día Y hora, y el mandato puede (opcionalmente) fijar un rango
# horario permitido que aplica a todos los días de la ventana.
# ---------------------------------------------------------------------------

def test_horario_dentro_del_rango_se_aprueba():
    mandato = _mandato(horario_inicio="09:00", horario_fin="18:00")
    commitment = _commitment(mandato, hora_retiro="10:30")
    resultado = validate_commitment(commitment, mandato)
    assert resultado.aprobado


def test_horario_fuera_del_rango_se_rechaza():
    mandato = _mandato(horario_inicio="09:00", horario_fin="18:00")
    commitment = _commitment(mandato, hora_retiro="07:00")
    resultado = validate_commitment(commitment, mandato)
    assert not resultado.aprobado
    assert "horario" in resultado.motivo


def test_horario_en_los_bordes_del_rango_se_aprueba():
    """Los límites del rango son inclusive, igual que la ventana de fechas."""
    mandato = _mandato(horario_inicio="09:00", horario_fin="18:00")
    assert validate_commitment(_commitment(mandato, hora_retiro="09:00"), mandato).aprobado
    assert validate_commitment(_commitment(mandato, hora_retiro="18:00"), mandato).aprobado


def test_mandato_sin_horario_definido_no_restringe_la_hora():
    """Si el mandato no fija horario_inicio/horario_fin, cualquier hora
    válida pasa — la restricción es opcional, no implícita."""
    mandato = _mandato()  # sin horario_inicio/horario_fin
    commitment = _commitment(mandato, hora_retiro="23:30")
    resultado = validate_commitment(commitment, mandato)
    assert resultado.aprobado


def test_horario_inicio_sin_horario_fin_no_se_puede_crear():
    with pytest.raises(ValueError):
        _mandato(horario_inicio="09:00", horario_fin=None)


def test_horario_inicio_posterior_a_horario_fin_no_se_puede_crear():
    with pytest.raises(ValueError):
        _mandato(horario_inicio="18:00", horario_fin="09:00")

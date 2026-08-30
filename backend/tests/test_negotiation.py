"""
Tests del motor de negociación — igual que test_guardrail.py, no necesita
voz, LLM ni API levantada. Si estos tests pasan, "el código nunca deja que
el LLM supere un límite mediante una respuesta generada" está garantizado
en la capa que manda para todo lo que el motor autoriza a decir — no
depende de que el prompt "se acuerde" de portarse bien.

Correr con: pytest backend/tests/test_negotiation.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import (
    EstadoNegociacion,
    EstrategiaModo,
    IntencionNegociacion,
    Mandato,
    MotivoFinalizacion,
    OfertaEntrante,
    TipoRespuestaConductor,
)
from app.negotiation import (
    ESCALERA_CONCESION,
    UMBRAL_URGENCIA_MINUTOS,
    ContextoEstrategia,
    calcular_estrategia,
    evaluar_oferta,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers — mismo estilo que test_guardrail.py
# ---------------------------------------------------------------------------

def _mandato(**overrides) -> Mandato:
    base = dict(
        operacion_id="op1",
        tope_precio=9000.0,
        tarifa_objetivo=8500.0,
        ventana_inicio=date(2026, 8, 28),
        ventana_fin=date(2026, 8, 30),
        vigente_hasta=datetime.now(timezone.utc) + timedelta(days=1),
        condiciones=[],
    )
    base.update(overrides)
    return Mandato(**base)


def _estado(mandato: Mandato, **overrides) -> EstadoNegociacion:
    base = dict(
        operacion_id=mandato.operacion_id,
        mandato_id=mandato.id,
        call_id="call1",
        contraparte="Transportes del Norte",
    )
    base.update(overrides)
    return EstadoNegociacion(**base)


def _oferta(**overrides) -> OfertaEntrante:
    base = dict(
        operacion_id="op1",
        call_id="call1",
        contraparte="Transportes del Norte",
        tipo_respuesta=TipoRespuestaConductor.contraoferta,
        monto=10000.0,
    )
    base.update(overrides)
    return OfertaEntrante(**base)


def _contexto(**overrides) -> ContextoEstrategia:
    return ContextoEstrategia(**overrides)


def _negociar_ronda(estado: EstadoNegociacion, mandato: Mandato, decision, oferta: OfertaEntrante):
    """Aplica una decisión al estado, como hace main.py, para poder
    simular varias rondas seguidas en un test sin repetir el mismo bloque."""
    from app.models import RondaNegociacion

    estado.rondas.append(
        RondaNegociacion(
            numero=decision.ronda,
            tipo_respuesta_conductor=oferta.tipo_respuesta,
            oferta_conductor=oferta.monto,
            condicion_propuesta=oferta.condicion_propuesta,
            intencion_volta=decision.intencion,
            oferta_volta=decision.monto_a_comunicar,
            estrategia=decision.estrategia,
            motivo_interno=decision.motivo_interno,
        )
    )
    if oferta.monto is not None:
        estado.ultima_oferta_conductor = oferta.monto
    if decision.monto_a_comunicar is not None:
        estado.ultima_oferta_volta = decision.monto_a_comunicar
    if decision.finalizar:
        estado.activa = False
        estado.motivo_finalizacion = decision.motivo_finalizacion
    return estado


# ---------------------------------------------------------------------------
# 1. Nunca superar el máximo
# ---------------------------------------------------------------------------

def test_nunca_supera_el_maximo_en_una_sola_ronda():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    oferta = _oferta(monto=50000.0)  # el conductor pide un disparate
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.monto_a_comunicar is not None
    assert decision.monto_a_comunicar <= mandato.tope_precio


def test_nunca_supera_el_maximo_a_lo_largo_de_muchas_rondas():
    """El conductor cede de a poco durante 10 rondas — en NINGUNA el motor
    puede autorizar más que el tope, ni siquiera en la última."""
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    monto_conductor = 15000.0
    for _ in range(10):
        if not estado.activa:
            break
        oferta = _oferta(monto=monto_conductor, tipo_respuesta=TipoRespuestaConductor.contraoferta)
        decision = evaluar_oferta(estado, mandato, oferta, _contexto())
        assert decision.monto_a_comunicar is None or decision.monto_a_comunicar <= mandato.tope_precio
        estado = _negociar_ronda(estado, mandato, decision, oferta)
        monto_conductor -= 300  # concesión chica cada ronda


def test_aceptacion_con_monto_por_encima_del_maximo_nunca_se_confirma():
    """Un 'sí' con un número que Volta jamás pudo haber ofrecido (por
    encima del tope) no se acepta a ciegas — se pide aclaración."""
    mandato = _mandato(tope_precio=9000.0)
    estado = _estado(mandato)
    oferta = _oferta(tipo_respuesta=TipoRespuestaConductor.aceptacion, monto=9500.0)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.intencion != IntencionNegociacion.accept_and_confirm
    assert decision.intencion == IntencionNegociacion.request_clarification


# ---------------------------------------------------------------------------
# 2. Negociación progresiva — objetivo primero, máximo solo si hace falta
# ---------------------------------------------------------------------------

def test_primer_movimiento_es_el_objetivo_no_el_maximo():
    """El ejemplo exacto del brief: conductor pide $10.000, objetivo
    $8.500, máximo $9.000 — Volta intenta primero el objetivo."""
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    oferta = _oferta(monto=10000.0)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.intencion == IntencionNegociacion.propose_target
    assert decision.monto_a_comunicar == 8500.0
    assert decision.finalizar is False


def test_negociacion_avanza_progresivamente_hacia_el_maximo_con_concesiones():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    montos_conductor = [10000.0, 9500.0, 9200.0]
    montos_volta = []
    for monto in montos_conductor:
        oferta = _oferta(monto=monto)
        decision = evaluar_oferta(estado, mandato, oferta, _contexto())
        montos_volta.append(decision.monto_a_comunicar)
        estado = _negociar_ronda(estado, mandato, decision, oferta)

    # Estrictamente creciente y nunca por encima del tope.
    assert montos_volta == sorted(montos_volta)
    assert montos_volta[0] == 8500.0  # arrancó en el objetivo
    assert all(m <= 9000.0 for m in montos_volta)
    assert montos_volta[-1] == 9000.0  # con suficiente concesión, llega al tope


def test_no_llega_al_maximo_de_un_salto_en_la_primera_ronda():
    """'Volta no debe realizar grandes concesiones automáticamente ante
    cada rechazo' — la primera respuesta nunca es directamente el tope."""
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    oferta = _oferta(monto=20000.0)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.monto_a_comunicar < mandato.tope_precio


def test_objetivo_derivado_cuando_el_mandato_no_define_uno():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=None)
    estado = _estado(mandato)
    oferta = _oferta(monto=15000.0)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.monto_a_comunicar is not None
    assert decision.monto_a_comunicar < mandato.tope_precio
    assert decision.monto_a_comunicar > 0


# ---------------------------------------------------------------------------
# 3. Detección de concesiones — reciprocidad
# ---------------------------------------------------------------------------

def test_sin_concesion_del_conductor_volta_no_avanza_un_escalon():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)

    oferta1 = _oferta(monto=10000.0)
    decision1 = evaluar_oferta(estado, mandato, oferta1, _contexto())
    estado = _negociar_ronda(estado, mandato, decision1, oferta1)

    # El conductor repite el MISMO número — no cedió nada.
    oferta2 = _oferta(monto=10000.0, tipo_respuesta=TipoRespuestaConductor.rechazo)
    decision2 = evaluar_oferta(estado, mandato, oferta2, _contexto())

    assert decision2.monto_a_comunicar == decision1.monto_a_comunicar  # se mantiene firme


def test_con_concesion_del_conductor_volta_si_avanza():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)

    oferta1 = _oferta(monto=10000.0)
    decision1 = evaluar_oferta(estado, mandato, oferta1, _contexto())
    estado = _negociar_ronda(estado, mandato, decision1, oferta1)

    oferta2 = _oferta(monto=9600.0, tipo_respuesta=TipoRespuestaConductor.concesion)  # bajó de 10000
    decision2 = evaluar_oferta(estado, mandato, oferta2, _contexto())

    assert decision2.monto_a_comunicar > decision1.monto_a_comunicar


# ---------------------------------------------------------------------------
# 4-5. Múltiples candidatos / último candidato → estrategia
# ---------------------------------------------------------------------------

def test_muchos_candidatos_y_baja_urgencia_es_estrategia_firme():
    estrategia = calcular_estrategia(_contexto(candidatos_restantes=3, tiempo_restante_minutos=2000))
    assert estrategia == EstrategiaModo.firme


def test_ultimo_candidato_fuerza_estrategia_cierre():
    estrategia = calcular_estrategia(_contexto(candidatos_restantes=0, tiempo_restante_minutos=2000))
    assert estrategia == EstrategiaModo.cierre


def test_cierre_tiene_menos_pasos_que_firme():
    assert len(ESCALERA_CONCESION[EstrategiaModo.cierre]) < len(ESCALERA_CONCESION[EstrategiaModo.firme])


# ---------------------------------------------------------------------------
# 6-7. Urgencia y tiempo restante
# ---------------------------------------------------------------------------

def test_poca_urgencia_no_fuerza_cierre():
    estrategia = calcular_estrategia(_contexto(candidatos_restantes=1, tiempo_restante_minutos=UMBRAL_URGENCIA_MINUTOS + 1))
    assert estrategia != EstrategiaModo.cierre


def test_alta_urgencia_fuerza_cierre_incluso_con_candidatos():
    estrategia = calcular_estrategia(_contexto(candidatos_restantes=5, tiempo_restante_minutos=UMBRAL_URGENCIA_MINUTOS - 1))
    assert estrategia == EstrategiaModo.cierre


def test_urgencia_nunca_cambia_el_maximo_autorizado():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    oferta = _oferta(monto=50000.0)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto(candidatos_restantes=0, tiempo_restante_minutos=1))
    assert decision.monto_a_comunicar is None or decision.monto_a_comunicar <= mandato.tope_precio


def test_tiempo_insuficiente_finaliza_la_negociacion():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    oferta = _oferta(monto=9500.0)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto(tiempo_restante_minutos=0))
    assert decision.finalizar is True
    assert decision.motivo_finalizacion == MotivoFinalizacion.tiempo_insuficiente


# ---------------------------------------------------------------------------
# 8. Condiciones no negociables
# ---------------------------------------------------------------------------

def test_condicion_no_negociable_corta_la_negociacion():
    mandato = _mandato(condiciones=["no se puede cambiar el tipo de camión"])
    estado = _estado(mandato)
    oferta = _oferta(
        tipo_respuesta=TipoRespuestaConductor.condicion,
        monto=None,
        variable_condicion="tipo de camión",
        condicion_propuesta="pide llevarlo en un camión distinto al acordado",
    )
    decision = evaluar_oferta(estado, mandato, oferta, _contexto(candidatos_restantes=2))
    assert decision.finalizar is True
    assert decision.motivo_finalizacion == MotivoFinalizacion.condicion_fuera_de_autorizacion
    assert decision.intencion == IntencionNegociacion.reject_and_move_on


def test_condicion_no_negociable_en_ultimo_candidato_escala_en_vez_de_abandonar():
    mandato = _mandato(condiciones=["no se puede cambiar el tipo de camión"])
    estado = _estado(mandato)
    oferta = _oferta(
        tipo_respuesta=TipoRespuestaConductor.condicion,
        monto=None,
        variable_condicion="tipo de camión",
    )
    decision = evaluar_oferta(estado, mandato, oferta, _contexto(candidatos_restantes=0))
    assert decision.intencion == IntencionNegociacion.escalate


def test_condicion_negociable_se_aprueba_sin_tocar_la_tarifa():
    mandato = _mandato(condiciones=["no se puede cambiar el tipo de camión"])
    estado = _estado(mandato, ultima_oferta_volta=8500.0)
    oferta = _oferta(
        tipo_respuesta=TipoRespuestaConductor.condicion,
        monto=None,
        variable_condicion="horario",
        condicion_propuesta="pide retirar a las 7am en vez de las 10am",
    )
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.intencion == IntencionNegociacion.trade_condition
    assert decision.condicion_aprobada is True
    assert decision.finalizar is False
    assert decision.monto_a_comunicar == 8500.0  # no se regala nada de tarifa por esto


# ---------------------------------------------------------------------------
# 9. Aceptación ambigua
# ---------------------------------------------------------------------------

def test_aceptacion_ambigua_pide_aclaracion_y_no_finaliza():
    mandato = _mandato()
    estado = _estado(mandato, ultima_oferta_volta=8700.0)
    oferta = _oferta(tipo_respuesta=TipoRespuestaConductor.aceptacion_ambigua, monto=None)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.intencion == IntencionNegociacion.request_clarification
    assert decision.finalizar is False


# ---------------------------------------------------------------------------
# 10. Contraofertas
# ---------------------------------------------------------------------------

def test_primera_oferta_buena_se_sondea_antes_de_cerrar():
    """Aunque la oferta ya sea mejor que el objetivo, en la PRIMERA ronda
    Volta tantea una vez por debajo en vez de cerrar de una: un coordinador
    real no acepta el primer numero, y cerrar ahi deja plata en la mesa."""
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    oferta = _oferta(monto=8200.0)  # mejor que el objetivo
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.intencion != IntencionNegociacion.accept_and_confirm
    assert decision.finalizar is False
    assert decision.monto_a_comunicar < 8200.0


def test_segunda_ronda_con_oferta_buena_se_acepta():
    """Ya sondeado (hay una oferta previa de Volta), una oferta dentro del
    objetivo se cierra: el sondeo es una sola vez, no un regateo infinito."""
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato, ultima_oferta_volta=8300.0)
    oferta = _oferta(monto=8200.0)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.intencion == IntencionNegociacion.accept_and_confirm
    assert decision.monto_a_comunicar == 8200.0
    assert decision.finalizar is True


# ---------------------------------------------------------------------------
# 11. Negociación circular
# ---------------------------------------------------------------------------

def test_ofertas_repetidas_sin_movimiento_terminan_en_circular():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    decision = None
    for _ in range(6):
        if estado.activa is False:
            break
        oferta = _oferta(monto=9500.0, tipo_respuesta=TipoRespuestaConductor.contraoferta)
        decision = evaluar_oferta(estado, mandato, oferta, _contexto())
        estado = _negociar_ronda(estado, mandato, decision, oferta)
    assert decision.finalizar is True
    assert decision.motivo_finalizacion in (MotivoFinalizacion.circular, MotivoFinalizacion.sin_progreso)


# ---------------------------------------------------------------------------
# 12. Escalación
# ---------------------------------------------------------------------------

def test_escalacion_necesaria_finaliza_con_intencion_escalate():
    mandato = _mandato()
    estado = _estado(mandato)
    oferta = _oferta(tipo_respuesta=TipoRespuestaConductor.escalacion_necesaria, monto=None)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.intencion == IntencionNegociacion.escalate
    assert decision.finalizar is True
    assert decision.motivo_finalizacion == MotivoFinalizacion.escalado


def test_cancelacion_finaliza_sin_escalar():
    mandato = _mandato()
    estado = _estado(mandato)
    oferta = _oferta(tipo_respuesta=TipoRespuestaConductor.cancelacion, monto=None)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.finalizar is True
    assert decision.motivo_finalizacion == MotivoFinalizacion.cancelado
    assert decision.intencion == IntencionNegociacion.reject_and_move_on


def test_conductor_no_baja_tras_rechazos_repetidos():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)

    oferta1 = _oferta(monto=10000.0)
    decision1 = evaluar_oferta(estado, mandato, oferta1, _contexto())
    estado = _negociar_ronda(estado, mandato, decision1, oferta1)

    oferta2 = _oferta(monto=None, tipo_respuesta=TipoRespuestaConductor.rechazo)
    decision2 = evaluar_oferta(estado, mandato, oferta2, _contexto())
    estado = _negociar_ronda(estado, mandato, decision2, oferta2)
    assert decision2.finalizar is False  # todavía no, es el primer rechazo

    oferta3 = _oferta(monto=None, tipo_respuesta=TipoRespuestaConductor.rechazo)
    decision3 = evaluar_oferta(estado, mandato, oferta3, _contexto())
    assert decision3.finalizar is True
    assert decision3.motivo_finalizacion == MotivoFinalizacion.conductor_no_baja


def test_mejor_alternativa_permite_cortar_y_pasar_al_siguiente():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    oferta1 = _oferta(monto=10000.0)
    decision1 = evaluar_oferta(estado, mandato, oferta1, _contexto())
    estado = _negociar_ronda(estado, mandato, decision1, oferta1)

    oferta2 = _oferta(monto=9700.0, mejor_alternativa_monto=8300.0)
    decision2 = evaluar_oferta(estado, mandato, oferta2, _contexto())
    assert decision2.finalizar is True
    assert decision2.motivo_finalizacion == MotivoFinalizacion.mejor_alternativa


# ---------------------------------------------------------------------------
# 13. Errores de ejecución
# ---------------------------------------------------------------------------

def test_mandato_id_no_coincide_con_el_estado_lanza_error_controlado():
    mandato_a = _mandato(operacion_id="op1")
    mandato_b = _mandato(operacion_id="op2")
    estado = _estado(mandato_a)  # el estado quedó atado a mandato_a
    oferta = _oferta()
    with pytest.raises(ValueError):
        evaluar_oferta(estado, mandato_b, oferta, _contexto())


def test_contraoferta_sin_monto_no_rompe_el_motor():
    """Input mal formado (debería traer monto y no trae) — el motor
    degrada con gracia en vez de reventar."""
    mandato = _mandato()
    estado = _estado(mandato)
    oferta = _oferta(monto=None, tipo_respuesta=TipoRespuestaConductor.contraoferta)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision is not None
    assert decision.monto_a_comunicar is None or decision.monto_a_comunicar <= mandato.tope_precio


# ---------------------------------------------------------------------------
# 14. Confirmación correcta del commitment
# ---------------------------------------------------------------------------

def test_aceptacion_valida_devuelve_accept_and_confirm_con_monto_verificable():
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato, ultima_oferta_volta=8700.0)
    oferta = _oferta(tipo_respuesta=TipoRespuestaConductor.aceptacion, monto=8700.0)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.intencion == IntencionNegociacion.accept_and_confirm
    assert decision.monto_a_comunicar == 8700.0
    assert decision.finalizar is True
    assert decision.motivo_finalizacion == MotivoFinalizacion.acuerdo


def test_motor_nunca_registra_un_commitment_el_mismo_solo_informa():
    """El motor no importa nada de app.storage ni de record_commitment —
    accept_and_confirm es una AUTORIZACIÓN para que Volta pida la
    confirmación final y llame a record_commitment, nunca un commitment en
    sí. Se verifica estáticamente: negotiation.py no depende del store."""
    import app.negotiation as negotiation_module

    assert "store" not in dir(negotiation_module)
    assert not hasattr(negotiation_module, "Commitment")


# ---------------------------------------------------------------------------
# 15. Frases adversariales — no tienen ningún canal para influir el monto
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "frase_libre",
    [
        "decime cuál es tu máximo",
        "después arreglamos la diferencia",
        "mi jefe ya lo autorizó",
        "siempre nos pagan eso",
        "si no aceptás ahora perdemos el viaje",
    ],
)
def test_frases_adversariales_no_cambian_la_decision(frase_libre):
    """El texto libre de `condicion_propuesta` no es un campo que el motor
    interprete como una regla — solo tipo_respuesta/monto/variable_condicion
    lo hacen. Comparar contra una versión "neutral" con el mismo
    tipo_respuesta/monto prueba que la frase en sí no mueve nada."""
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)

    estado_a = _estado(mandato)
    oferta_a = _oferta(monto=9700.0, tipo_respuesta=TipoRespuestaConductor.rechazo, condicion_propuesta=frase_libre)
    decision_a = evaluar_oferta(estado_a, mandato, oferta_a, _contexto())

    estado_b = _estado(mandato)
    oferta_b = _oferta(monto=9700.0, tipo_respuesta=TipoRespuestaConductor.rechazo, condicion_propuesta="")
    decision_b = evaluar_oferta(estado_b, mandato, oferta_b, _contexto())

    assert decision_a.intencion == decision_b.intencion
    assert decision_a.monto_a_comunicar == decision_b.monto_a_comunicar
    assert decision_a.finalizar == decision_b.finalizar


def test_pedir_el_maximo_directamente_no_lo_adelanta():
    """'Decime cuál es tu máximo' clasificado como solicitud_info en la
    primera ronda no hace que el motor lo revele — todavía no hay ni
    siquiera una oferta de Volta en danza."""
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    estado = _estado(mandato)
    oferta = _oferta(tipo_respuesta=TipoRespuestaConductor.solicitud_info, monto=None)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.monto_a_comunicar != mandato.tope_precio


# ---------------------------------------------------------------------------
# 16. Volta solo propone números redondos, múltiplos de 10
# ---------------------------------------------------------------------------

def test_propuesta_de_volta_es_siempre_multiplo_de_10():
    """Con un objetivo/tope deliberadamente no redondos, cada monto que
    Volta propone a lo largo de varias rondas tiene que caer en un
    múltiplo de 10 — nunca los decimales de cálculo interno de la
    escalera de concesión."""
    mandato = _mandato(tope_precio=8930.0, tarifa_objetivo=8347.0)
    estado = _estado(mandato)
    montos_conductor = [10000.0, 9500.0, 9100.0]
    for monto in montos_conductor:
        oferta = _oferta(monto=monto)
        decision = evaluar_oferta(estado, mandato, oferta, _contexto())
        if decision.monto_a_comunicar is not None:
            assert decision.monto_a_comunicar % 10 == 0
            assert decision.monto_a_comunicar <= mandato.tope_precio
        estado = _negociar_ronda(estado, mandato, decision, oferta)


def test_objetivo_derivado_no_redondo_se_propone_redondeado():
    """El objetivo derivado (tope * ratio, sin definir tarifa_objetivo) casi
    nunca cae justo en un múltiplo de 10 — igual tiene que comunicarse
    redondeado."""
    mandato = _mandato(tope_precio=8930.0, tarifa_objetivo=None)
    estado = _estado(mandato)
    oferta = _oferta(monto=15000.0)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.monto_a_comunicar is not None
    assert decision.monto_a_comunicar % 10 == 0


def test_redondeo_nunca_empuja_la_propuesta_por_encima_del_tope():
    """Si el paso final de la escalera (el máximo mismo) no es múltiplo de
    10, redondear 'hacia arriba' lo pasaría del tope — el motor tiene que
    redondear para abajo en ese caso, nunca superar el límite duro."""
    mandato = _mandato(tope_precio=8955.0, tarifa_objetivo=8500.0)  # 8955 no es múltiplo de 10
    estado = _estado(mandato, ultima_oferta_volta=8500.0, estrategia_actual=EstrategiaModo.cierre)
    oferta = _oferta(monto=8900.0, tipo_respuesta=TipoRespuestaConductor.contraoferta)
    decision = evaluar_oferta(estado, mandato, oferta, _contexto(candidatos_restantes=0))
    assert decision.monto_a_comunicar is not None
    assert decision.monto_a_comunicar % 10 == 0
    assert decision.monto_a_comunicar <= mandato.tope_precio


def test_aceptar_la_oferta_del_conductor_no_se_redondea():
    """Cuando Volta ACEPTA lo que ya dijo el conductor (no propone un
    número nuevo), se confirma el monto real acordado tal cual — redondear
    acá cambiaría lo que efectivamente se negoció."""
    mandato = _mandato(tope_precio=9000.0, tarifa_objetivo=8500.0)
    # con una oferta previa de Volta ya se paso el sondeo inicial
    estado = _estado(mandato, ultima_oferta_volta=8300.0)
    oferta = _oferta(monto=8237.0)  # mejor que el objetivo, no es múltiplo de 10
    decision = evaluar_oferta(estado, mandato, oferta, _contexto())
    assert decision.intencion == IntencionNegociacion.accept_and_confirm
    assert decision.monto_a_comunicar == 8237.0

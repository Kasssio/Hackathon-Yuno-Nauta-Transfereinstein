"""
Tests del catálogo ficticio de transportistas — resuelve "a quién llama
Volta" antes de arrancar la ronda de negociaciones. No necesita API
levantada ni mock de nada: son funciones puras sobre el fixture de
backend/app/carriers_data.py (30 transportistas repartidos en 4 puertos).

Correr con: pytest backend/tests/test_carriers.py -v
"""

from app.carriers_data import PESOS_SCORE, PUERTOS, TRANSPORTISTAS, _distancia_km, buscar_candidatos


def test_el_catalogo_tiene_30_transportistas_con_ids_unicos():
    assert len(TRANSPORTISTAS) == 30
    ids = [t["id"] for t in TRANSPORTISTAS]
    assert len(ids) == len(set(ids))


def test_filtra_solo_los_transportistas_que_sirven_ese_puerto():
    for puerto in PUERTOS:
        for c in buscar_candidatos(puerto=puerto):
            assert puerto in c["puertos"]


def test_ordena_por_cercania_al_puerto():
    for puerto in PUERTOS:
        distancias = [c["distancia_km"] for c in buscar_candidatos(puerto=puerto)]
        assert distancias == sorted(distancias)


def test_max_distancia_km_descarta_a_los_que_estan_muy_lejos():
    """Este es el caso de uso que pidió Lucas explícitamente: poder
    descartar transportistas lejanos del puerto en vez de que Volta
    los llame igual. t-norte está a metros de Manzanillo, t-logistica-jalisco
    a ~190km — con un tope de 50km uno entra y el otro no."""
    candidatos = buscar_candidatos(puerto="Manzanillo", max_distancia_km=50)
    ids = [c["id"] for c in candidatos]
    assert "t-norte" in ids
    assert "t-logistica-jalisco" not in ids
    assert all(c["distancia_km"] <= 50 for c in candidatos)


def test_un_transportista_que_sirve_dos_puertos_aparece_en_ambos():
    # t-express está en Manzanillo y Lázaro Cárdenas — por si Textiles
    # Pacífico deja mercadería en más de un puerto.
    en_manzanillo = {c["id"] for c in buscar_candidatos(puerto="Manzanillo")}
    en_lazaro = {c["id"] for c in buscar_candidatos(puerto="Lázaro Cárdenas")}
    assert "t-express" in en_manzanillo
    assert "t-express" in en_lazaro


def test_puerto_sin_transportistas_devuelve_lista_vacia():
    assert buscar_candidatos(puerto="Ensenada") == []


def test_sin_puerto_devuelve_todo_el_catalogo_sin_distancia():
    candidatos = buscar_candidatos()
    assert len(candidatos) == len(TRANSPORTISTAS)
    assert all(c["distancia_km"] is None for c in candidatos)


def test_cada_candidato_conserva_los_campos_de_negociacion():
    # disposicion_a_negociar, puntualidad y las dos tasas de aceptación
    # son los datos que le sirven a la IA para decidir con quién negociar
    # de más y a quién priorizar cuando el pedido es urgente — no se
    # pueden perder en el filtro.
    for c in buscar_candidatos(puerto="Manzanillo"):
        assert 1 <= c["disposicion_a_negociar"] <= 5
        assert 1 <= c["puntualidad"] <= 5
        assert 0.0 <= c["tasa_aceptacion_general"] <= 1.0
        assert 0.0 <= c["tasa_aceptacion_corto_plazo"] <= 1.0


def test_tasas_de_aceptacion_en_rango_valido_para_todo_el_catalogo():
    for t in TRANSPORTISTAS:
        assert 0.0 <= t["tasa_aceptacion_general"] <= 1.0, t["id"]
        assert 0.0 <= t["tasa_aceptacion_corto_plazo"] <= 1.0, t["id"]


def test_aceptacion_a_corto_plazo_nunca_supera_a_la_general():
    """Invariante de los datos: conseguir que un transportista acepte con
    pocos días de anticipación nunca es más fácil que en general."""
    for t in TRANSPORTISTAS:
        assert t["tasa_aceptacion_corto_plazo"] <= t["tasa_aceptacion_general"], t["id"]


def test_limite_devuelve_como_maximo_esa_cantidad():
    assert len(buscar_candidatos(puerto="Manzanillo", limite=3)) == 3
    # Manzanillo tiene más de 3 candidatos en el catálogo — si pidiéramos
    # más de los que hay, no debería inventar ni romper.
    assert len(buscar_candidatos(puerto="Manzanillo", limite=999)) == len(
        buscar_candidatos(puerto="Manzanillo")
    )


def test_limite_reordena_por_puntaje_no_solo_por_cercania():
    """Este es el caso que motivó el parámetro: con 11 candidatos en
    Manzanillo, "los 3 más cerca" y "los 3 mejores" no son la misma
    lista — t-bajio es más cercano que t-express, pero t-express negocia
    mejor y acepta más seguido, así que gana un lugar en el top 3."""
    top3 = buscar_candidatos(puerto="Manzanillo", limite=3)
    ids = [c["id"] for c in top3]
    assert "t-express" in ids
    assert "t-bajio" not in ids
    # viene ordenado por puntaje descendente, no por distancia
    puntajes = [c["puntaje"] for c in top3]
    assert puntajes == sorted(puntajes, reverse=True)


def test_cada_candidato_con_puerto_trae_puntaje_valido():
    for c in buscar_candidatos(puerto="Manzanillo"):
        assert c["puntaje"] is not None
        assert 0.0 <= c["puntaje"] <= 1.0


def test_sin_puerto_el_puntaje_es_none():
    for c in buscar_candidatos():
        assert c["puntaje"] is None


def test_los_pesos_del_puntaje_suman_uno():
    assert round(sum(PESOS_SCORE.values()), 6) == 1.0


def test_distancia_de_un_punto_a_si_mismo_es_cero():
    assert _distancia_km(PUERTOS["Manzanillo"], PUERTOS["Manzanillo"]) == 0.0


def test_distancia_es_simetrica():
    a, b = PUERTOS["Manzanillo"], PUERTOS["Veracruz"]
    assert _distancia_km(a, b) == _distancia_km(b, a)

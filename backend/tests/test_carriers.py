"""
Tests del catálogo ficticio de transportistas — resuelve "a quién llama
Volta" antes de arrancar la ronda de negociaciones. No necesita API
levantada ni mock de nada: son funciones puras sobre el fixture de
backend/app/carriers_data.py.

Correr con: pytest backend/tests/test_carriers.py -v
"""

from app.carriers_data import PUERTOS, TRANSPORTISTAS, _distancia_km, buscar_candidatos


def test_filtra_solo_los_transportistas_que_sirven_ese_puerto():
    candidatos = buscar_candidatos(puerto="Manzanillo")
    ids = {c["id"] for c in candidatos}
    assert ids == {"t-norte", "t-express", "t-logistica-jalisco"}


def test_ordena_por_cercania_al_puerto():
    candidatos = buscar_candidatos(puerto="Manzanillo")
    ids = [c["id"] for c in candidatos]
    # t-norte está a metros del puerto, t-express en la zona, t-logistica-jalisco
    # camino a Guadalajara — mucho más lejos.
    assert ids == ["t-norte", "t-express", "t-logistica-jalisco"]
    distancias = [c["distancia_km"] for c in candidatos]
    assert distancias == sorted(distancias)


def test_max_distancia_km_descarta_a_los_que_estan_muy_lejos():
    """Este es el caso de uso que pidió Lucas explícitamente: poder
    descartar transportistas lejanos del puerto en vez de que Volta
    los llame igual."""
    candidatos = buscar_candidatos(puerto="Manzanillo", max_distancia_km=50)
    ids = [c["id"] for c in candidatos]
    assert ids == ["t-norte"]
    assert "t-logistica-jalisco" not in ids
    assert "t-express" not in ids


def test_un_transportista_que_sirve_dos_puertos_aparece_en_ambos():
    # t-express está en Manzanillo y Lázaro Cárdenas — por si Textiles
    # Pacífico deja mercadería en más de un puerto.
    en_manzanillo = {c["id"] for c in buscar_candidatos(puerto="Manzanillo")}
    en_lazaro = {c["id"] for c in buscar_candidatos(puerto="Lázaro Cárdenas")}
    assert "t-express" in en_manzanillo
    assert "t-express" in en_lazaro


def test_puerto_sin_transportistas_devuelve_lista_vacia():
    assert buscar_candidatos(puerto="Altamira", max_distancia_km=10) == []


def test_sin_puerto_devuelve_todo_el_catalogo_sin_distancia():
    candidatos = buscar_candidatos()
    assert len(candidatos) == len(TRANSPORTISTAS)
    assert all(c["distancia_km"] is None for c in candidatos)


def test_cada_candidato_conserva_los_campos_de_negociacion():
    # disposicion_a_negociar y puntualidad son los datos que le sirven
    # a la IA para saber con quién negociar de más — no se pueden perder
    # en el filtro.
    candidatos = buscar_candidatos(puerto="Manzanillo")
    for c in candidatos:
        assert 1 <= c["disposicion_a_negociar"] <= 5
        assert 1 <= c["puntualidad"] <= 5


def test_distancia_de_un_punto_a_si_mismo_es_cero():
    assert _distancia_km(PUERTOS["Manzanillo"], PUERTOS["Manzanillo"]) == 0.0


def test_distancia_es_simetrica():
    a, b = PUERTOS["Manzanillo"], PUERTOS["Veracruz"]
    assert _distancia_km(a, b) == _distancia_km(b, a)

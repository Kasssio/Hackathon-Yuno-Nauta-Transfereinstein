"""
Datos ficticios de transportistas — resuelve "a quién llama Volta".

El brief permite inventar catálogo y datos ("Catálogo, prices, mandatos,
protocolos... pueden inventarse"). Esto es justo eso: un fixture chico,
no una base de datos real, pero con la forma que tendría una real —
así el filtro de candidatos (por puerto y por distancia) es lógica de
verdad, no un número mágico hardcodeado en el prompt del agente.

30 transportistas repartidos entre los 4 puertos. Además de puerto,
ubicación, disposición a negociar y puntualidad, cada uno trae dos
tasas de aceptación (0.0 a 1.0, no son lo mismo):

- tasa_aceptacion_general: qué tan seguido dice que sí a tomar el
  trabajo, en general. Un transportista puede ser rígido para negociar
  precio (disposicion_a_negociar baja) y aun así aceptar casi siempre
  si le avisan con tiempo — son cosas distintas.
- tasa_aceptacion_corto_plazo: lo mismo pero pidiéndole con pocos días
  de anticipación. Por diseño, para todos los transportistas del
  fixture esta tasa es <= tasa_aceptacion_general (conseguir que
  acepten último momento siempre es más difícil o igual de fácil,
  nunca más fácil) — buscar_candidatos no lo fuerza, es una propiedad
  de los datos, pero sirve para que la IA sepa a quién conviene llamar
  primero cuando la ventana del mandato está ajustada.

Las coordenadas de los puertos son aproximadas (alcanza para que la
distancia tenga sentido en la demo, no hace falta precisión de GPS real).

Con 30 transportistas, mostrarle a Volta los 11 candidatos de un puerto
como Manzanillo es demasiado para una negociación en vivo de 24h. Por
eso `buscar_candidatos` acepta un `limite`: cuando se pasa, no corta la
lista ordenada por cercanía nomás — recalcula un puntaje combinado
(distancia + disposición a negociar + puntualidad + las dos tasas de
aceptación, ver PESOS_SCORE) y devuelve los mejores N por ese puntaje.
"Más cerca" y "mejor candidato" no siempre son la misma respuesta: un
transportista un poco más lejos pero mucho más flexible para negociar
y con mejor tasa de aceptación puede ganarle a uno pegado al puerto.
"""

from __future__ import annotations

import math
from typing import Optional, TypedDict


class Coordenadas(TypedDict):
    lat: float
    lon: float


# Puertos mexicanos de referencia — aproximados, a propósito.
PUERTOS: dict[str, Coordenadas] = {
    "Manzanillo": {"lat": 19.05, "lon": -104.32},
    "Lázaro Cárdenas": {"lat": 17.96, "lon": -102.20},
    "Veracruz": {"lat": 19.17, "lon": -96.13},
    "Altamira": {"lat": 22.40, "lon": -97.83},
}


# Pesos del puntaje combinado que usa `buscar_candidatos` cuando se pide
# un `limite` — pensados para que la cercanía importe, pero no aplaste al
# resto: encontrar a alguien que difícilmente acepte el trabajo (o que
# negocie mal, o que no cumpla) no sirve de mucho aunque esté a la vuelta
# del puerto. Suman 1.0.
PESOS_SCORE: dict[str, float] = {
    "distancia": 0.25,
    "disposicion_a_negociar": 0.20,
    "puntualidad": 0.20,
    "tasa_aceptacion_general": 0.20,
    "tasa_aceptacion_corto_plazo": 0.15,
}


class Transportista(TypedDict):
    id: str
    nombre: str
    puertos: list[str]  # puertos donde opera
    ubicacion: Coordenadas  # base actual del transportista
    disposicion_a_negociar: int  # 1-5, cuánto margen suele ceder en el precio
    puntualidad: int  # 1-5, historial de cumplimiento
    tarifa_referencia: float  # tarifa base típica, en USD
    tasa_aceptacion_general: float  # 0.0-1.0, qué tan seguido acepta el trabajo
    tasa_aceptacion_corto_plazo: float  # 0.0-1.0, ídem pero pidiendo con poca anticipación
    telefono: str


TRANSPORTISTAS: list[Transportista] = [
    {
        "id": "t-norte",
        "nombre": "Transportes del Norte",
        "puertos": ["Manzanillo"],
        "ubicacion": {"lat": 19.05, "lon": -104.28},  # a metros del puerto
        "disposicion_a_negociar": 2,
        "puntualidad": 5,
        "tarifa_referencia": 8800,
        # Confiable y puntual, pero rígido: acepta casi siempre si le avisan
        # con tiempo, y bastante menos si el pedido es de último momento.
        "tasa_aceptacion_general": 0.85,
        "tasa_aceptacion_corto_plazo": 0.45,
        "telefono": "+52 314 555 0101",
    },
    {
        "id": "t-express",
        "nombre": "Transportes Express",
        "puertos": ["Manzanillo", "Lázaro Cárdenas"],
        "ubicacion": {"lat": 19.30, "lon": -103.90},
        "disposicion_a_negociar": 4,
        "puntualidad": 3,
        "tarifa_referencia": 8200,
        # Muy eager por trabajo: negocia y acepta fácil, incluso apurado.
        "tasa_aceptacion_general": 0.90,
        "tasa_aceptacion_corto_plazo": 0.70,
        "telefono": "+52 314 555 0102",
    },
    {
        "id": "t-fletes-pacifico",
        "nombre": "Fletes Pacífico",
        "puertos": ["Lázaro Cárdenas"],
        "ubicacion": {"lat": 17.98, "lon": -102.18},
        "disposicion_a_negociar": 3,
        "puntualidad": 4,
        "tarifa_referencia": 8500,
        "tasa_aceptacion_general": 0.75,
        "tasa_aceptacion_corto_plazo": 0.50,
        "telefono": "+52 753 555 0103",
    },
    {
        "id": "t-logistica-jalisco",
        "nombre": "Logística Jalisco",
        "puertos": ["Manzanillo"],
        "ubicacion": {"lat": 20.50, "lon": -103.30},  # ruta hacia Guadalajara
        "disposicion_a_negociar": 3,
        "puntualidad": 4,
        "tarifa_referencia": 8600,
        # Lejos del puerto — le cuesta más movilizarse rápido si el pedido
        # es de último momento, aunque en general sí acepta.
        "tasa_aceptacion_general": 0.60,
        "tasa_aceptacion_corto_plazo": 0.30,
        "telefono": "+52 33 555 0104",
    },
    {
        "id": "t-carga-rapida",
        "nombre": "Carga Rápida SA",
        "puertos": ["Veracruz", "Altamira"],
        "ubicacion": {"lat": 19.17, "lon": -96.13},  # lejos de Manzanillo, a propósito
        "disposicion_a_negociar": 5,
        "puntualidad": 2,
        "tarifa_referencia": 7900,
        # El nombre no miente: floja en puntualidad, pero justo su fuerte
        # es aceptar pedidos con poca anticipación.
        "tasa_aceptacion_general": 0.80,
        "tasa_aceptacion_corto_plazo": 0.75,
        "telefono": "+52 229 555 0105",
    },
    {
        "id": "t-bajio",
        "nombre": "Autotransportes Bajío",
        "puertos": ["Manzanillo"],
        "ubicacion": {"lat": 19.26, "lon": -104.59},
        "disposicion_a_negociar": 2,
        "puntualidad": 5,
        "tarifa_referencia": 7750,
        "tasa_aceptacion_general": 0.70,
        "tasa_aceptacion_corto_plazo": 0.38,
        "telefono": "+52 312 555 0227",
    },
    {
        "id": "t-altiplano",
        "nombre": "Camiones Altiplano",
        "puertos": ["Manzanillo"],
        "ubicacion": {"lat": 20.51, "lon": -103.13},
        "disposicion_a_negociar": 2,
        "puntualidad": 5,
        "tarifa_referencia": 8350,
        "tasa_aceptacion_general": 0.85,
        "tasa_aceptacion_corto_plazo": 0.76,
        "telefono": "+52 477 555 0228",
    },
    {
        "id": "t-occidente",
        "nombre": "Autotransportes Occidente",
        "puertos": ["Manzanillo"],
        "ubicacion": {"lat": 18.52, "lon": -103.93},
        "disposicion_a_negociar": 4,
        "puntualidad": 1,
        "tarifa_referencia": 9350,
        "tasa_aceptacion_general": 0.38,
        "tasa_aceptacion_corto_plazo": 0.07,
        "telefono": "+52 33 555 0237",
    },
    {
        "id": "t-guadalajara-log",
        "nombre": "Transportes Guadalajara Log",
        "puertos": ["Manzanillo"],
        "ubicacion": {"lat": 20.23, "lon": -105.51},
        "disposicion_a_negociar": 5,
        "puntualidad": 3,
        "tarifa_referencia": 7800,
        "tasa_aceptacion_general": 0.69,
        "tasa_aceptacion_corto_plazo": 0.58,
        "telefono": "+52 33 555 0212",
    },
    {
        "id": "t-manzanillo-plus",
        "nombre": "Autotransportes Manzanillo Plus",
        "puertos": ["Manzanillo"],
        "ubicacion": {"lat": 19.00, "lon": -104.28},
        "disposicion_a_negociar": 3,
        "puntualidad": 5,
        "tarifa_referencia": 8800,
        "tasa_aceptacion_general": 0.61,
        "tasa_aceptacion_corto_plazo": 0.47,
        "telefono": "+52 314 555 0274",
    },
    {
        "id": "t-el-aguila",
        "nombre": "Transportes El Águila",
        "puertos": ["Manzanillo"],
        "ubicacion": {"lat": 18.41, "lon": -104.92},
        "disposicion_a_negociar": 2,
        "puntualidad": 3,
        "tarifa_referencia": 7750,
        "tasa_aceptacion_general": 0.53,
        "tasa_aceptacion_corto_plazo": 0.33,
        "telefono": "+52 314 555 0243",
    },
    {
        "id": "t-doble-via",
        "nombre": "Transportes Doble Vía",
        "puertos": ["Manzanillo"],
        "ubicacion": {"lat": 18.28, "lon": -103.25},
        "disposicion_a_negociar": 2,
        "puntualidad": 5,
        "tarifa_referencia": 8350,
        "tasa_aceptacion_general": 0.80,
        "tasa_aceptacion_corto_plazo": 0.70,
        "telefono": "+52 351 555 0262",
    },
    {
        "id": "t-colima",
        "nombre": "Transportes Colima",
        "puertos": ["Lázaro Cárdenas"],
        "ubicacion": {"lat": 19.20, "lon": -103.00},
        "disposicion_a_negociar": 5,
        "puntualidad": 4,
        "tarifa_referencia": 8200,
        "tasa_aceptacion_general": 0.56,
        "tasa_aceptacion_corto_plazo": 0.36,
        "telefono": "+52 312 555 0258",
    },
    {
        "id": "t-michoacan",
        "nombre": "Transportes Michoacán",
        "puertos": ["Lázaro Cárdenas"],
        "ubicacion": {"lat": 18.10, "lon": -102.04},
        "disposicion_a_negociar": 2,
        "puntualidad": 1,
        "tarifa_referencia": 8900,
        "tasa_aceptacion_general": 0.54,
        "tasa_aceptacion_corto_plazo": 0.32,
        "telefono": "+52 753 555 0287",
    },
    {
        "id": "t-sierra-madre",
        "nombre": "Transportes Sierra Madre",
        "puertos": ["Lázaro Cárdenas"],
        "ubicacion": {"lat": 16.80, "lon": -103.42},
        "disposicion_a_negociar": 3,
        "puntualidad": 1,
        "tarifa_referencia": 9300,
        "tasa_aceptacion_general": 0.56,
        "tasa_aceptacion_corto_plazo": 0.33,
        "telefono": "+52 443 555 0263",
    },
    {
        "id": "t-rapidos-pacifico",
        "nombre": "Fletes Rápidos del Pacífico",
        "puertos": ["Lázaro Cárdenas"],
        "ubicacion": {"lat": 18.06, "lon": -102.13},
        "disposicion_a_negociar": 3,
        "puntualidad": 4,
        "tarifa_referencia": 8300,
        "tasa_aceptacion_general": 0.87,
        "tasa_aceptacion_corto_plazo": 0.80,
        "telefono": "+52 753 555 0257",
    },
    {
        "id": "t-la-costa",
        "nombre": "Transportes La Costa",
        "puertos": ["Lázaro Cárdenas"],
        "ubicacion": {"lat": 18.34, "lon": -102.55},
        "disposicion_a_negociar": 4,
        "puntualidad": 5,
        "tarifa_referencia": 8100,
        "tasa_aceptacion_general": 0.60,
        "tasa_aceptacion_corto_plazo": 0.44,
        "telefono": "+52 753 555 0248",
    },
    {
        "id": "t-jalisco-sur",
        "nombre": "Fletes Jalisco Sur",
        "puertos": ["Lázaro Cárdenas"],
        "ubicacion": {"lat": 16.59, "lon": -103.59},
        "disposicion_a_negociar": 3,
        "puntualidad": 3,
        "tarifa_referencia": 7600,
        "tasa_aceptacion_general": 0.85,
        "tasa_aceptacion_corto_plazo": 0.75,
        "telefono": "+52 315 555 0236",
    },
    {
        "id": "t-golfo",
        "nombre": "Fletes del Golfo",
        "puertos": ["Veracruz"],
        "ubicacion": {"lat": 19.48, "lon": -95.83},
        "disposicion_a_negociar": 3,
        "puntualidad": 3,
        "tarifa_referencia": 8850,
        "tasa_aceptacion_general": 0.66,
        "tasa_aceptacion_corto_plazo": 0.42,
        "telefono": "+52 229 555 0286",
    },
    {
        "id": "t-veracruz-norte",
        "nombre": "Fletes Veracruz Norte",
        "puertos": ["Veracruz"],
        "ubicacion": {"lat": 18.54, "lon": -95.36},
        "disposicion_a_negociar": 5,
        "puntualidad": 4,
        "tarifa_referencia": 8300,
        "tasa_aceptacion_general": 0.59,
        "tasa_aceptacion_corto_plazo": 0.40,
        "telefono": "+52 229 555 0251",
    },
    {
        "id": "t-huasteca",
        "nombre": "Logística Huasteca",
        "puertos": ["Veracruz"],
        "ubicacion": {"lat": 20.02, "lon": -95.21},
        "disposicion_a_negociar": 2,
        "puntualidad": 2,
        "tarifa_referencia": 8200,
        "tasa_aceptacion_general": 0.38,
        "tasa_aceptacion_corto_plazo": 0.33,
        "telefono": "+52 228 555 0219",
    },
    {
        "id": "t-cargo-golfo",
        "nombre": "Grupo Cargo Golfo",
        "puertos": ["Veracruz"],
        "ubicacion": {"lat": 19.04, "lon": -96.02},
        "disposicion_a_negociar": 2,
        "puntualidad": 3,
        "tarifa_referencia": 8700,
        "tasa_aceptacion_general": 0.44,
        "tasa_aceptacion_corto_plazo": 0.31,
        "telefono": "+52 229 555 0244",
    },
    {
        "id": "t-continental-mx",
        "nombre": "Fletes Continental MX",
        "puertos": ["Veracruz"],
        "ubicacion": {"lat": 17.75, "lon": -94.97},
        "disposicion_a_negociar": 4,
        "puntualidad": 5,
        "tarifa_referencia": 8450,
        "tasa_aceptacion_general": 0.54,
        "tasa_aceptacion_corto_plazo": 0.45,
        "telefono": "+52 271 555 0295",
    },
    {
        "id": "t-portuaria",
        "nombre": "Logística Portuaria SA",
        "puertos": ["Veracruz"],
        "ubicacion": {"lat": 19.20, "lon": -96.17},
        "disposicion_a_negociar": 2,
        "puntualidad": 5,
        "tarifa_referencia": 7650,
        "tasa_aceptacion_general": 0.92,
        "tasa_aceptacion_corto_plazo": 0.71,
        "telefono": "+52 229 555 0218",
    },
    {
        "id": "t-tamaulipas",
        "nombre": "Logística Tamaulipas",
        "puertos": ["Altamira"],
        "ubicacion": {"lat": 22.14, "lon": -97.59},
        "disposicion_a_negociar": 3,
        "puntualidad": 2,
        "tarifa_referencia": 8850,
        "tasa_aceptacion_general": 0.51,
        "tasa_aceptacion_corto_plazo": 0.35,
        "telefono": "+52 833 555 0221",
    },
    {
        "id": "t-costa-cargo",
        "nombre": "Grupo Costa Cargo",
        "puertos": ["Altamira"],
        "ubicacion": {"lat": 23.08, "lon": -98.64},
        "disposicion_a_negociar": 5,
        "puntualidad": 4,
        "tarifa_referencia": 8750,
        "tasa_aceptacion_general": 0.72,
        "tasa_aceptacion_corto_plazo": 0.43,
        "telefono": "+52 833 555 0297",
    },
    {
        "id": "t-transtam",
        "nombre": "Grupo Transtam",
        "puertos": ["Altamira"],
        "ubicacion": {"lat": 22.32, "lon": -97.91},
        "disposicion_a_negociar": 3,
        "puntualidad": 3,
        "tarifa_referencia": 8550,
        "tasa_aceptacion_general": 0.56,
        "tasa_aceptacion_corto_plazo": 0.50,
        "telefono": "+52 833 555 0203",
    },
    {
        "id": "t-del-puerto",
        "nombre": "Camiones del Puerto",
        "puertos": ["Altamira"],
        "ubicacion": {"lat": 22.01, "lon": -98.17},
        "disposicion_a_negociar": 3,
        "puntualidad": 5,
        "tarifa_referencia": 9050,
        "tasa_aceptacion_general": 0.78,
        "tasa_aceptacion_corto_plazo": 0.63,
        "telefono": "+52 835 555 0246",
    },
    {
        "id": "t-express-norte",
        "nombre": "Camiones Express Norte",
        "puertos": ["Altamira"],
        "ubicacion": {"lat": 23.41, "lon": -96.59},
        "disposicion_a_negociar": 3,
        "puntualidad": 3,
        "tarifa_referencia": 8450,
        "tasa_aceptacion_general": 0.94,
        "tasa_aceptacion_corto_plazo": 0.71,
        "telefono": "+52 834 555 0200",
    },
    {
        "id": "t-unidos-pacifico",
        "nombre": "Fletes Unidos del Pacífico",
        "puertos": ["Manzanillo", "Lázaro Cárdenas"],
        "ubicacion": {"lat": 19.36, "lon": -104.65},
        "disposicion_a_negociar": 2,
        "puntualidad": 2,
        "tarifa_referencia": 9250,
        "tasa_aceptacion_general": 0.82,
        "tasa_aceptacion_corto_plazo": 0.54,
        "telefono": "+52 314 555 0261",
    },
]


def _distancia_km(a: Coordenadas, b: Coordenadas) -> float:
    """Haversine — suficiente para ordenar/filtrar por cercanía, no hace
    falta más precisión que esa para la demo."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(R * 2 * math.asin(math.sqrt(h)), 1)


def _normalizar(valor: float, minimo: float, maximo: float) -> float:
    """0.0-1.0, más alto siempre mejor. Si todo el grupo empata en este
    campo, no premia ni penaliza a nadie (devuelve 1.0 parejo) en vez de
    dividir por cero."""
    if maximo == minimo:
        return 1.0
    return (valor - minimo) / (maximo - minimo)


def _calcular_puntajes(candidatos: list[dict]) -> None:
    """Le agrega 'puntaje' (0.0-1.0) a cada dict de candidatos, in place.
    La distancia se normaliza DENTRO del propio grupo (el más cercano de
    este puerto saca 1.0 en ese factor, no hay una escala absoluta de km
    global) — así el puntaje tiene sentido sea cual sea el puerto."""
    distancias = [c["distancia_km"] for c in candidatos]
    d_min, d_max = min(distancias), max(distancias)
    for c in candidatos:
        score_distancia = 1.0 - _normalizar(c["distancia_km"], d_min, d_max)
        puntaje = (
            PESOS_SCORE["distancia"] * score_distancia
            + PESOS_SCORE["disposicion_a_negociar"] * _normalizar(c["disposicion_a_negociar"], 1, 5)
            + PESOS_SCORE["puntualidad"] * _normalizar(c["puntualidad"], 1, 5)
            + PESOS_SCORE["tasa_aceptacion_general"] * c["tasa_aceptacion_general"]
            + PESOS_SCORE["tasa_aceptacion_corto_plazo"] * c["tasa_aceptacion_corto_plazo"]
        )
        c["puntaje"] = round(puntaje, 3)


def obtener_transportista(transportista_id: str) -> Optional[Transportista]:
    """Lookup directo por id — lo usa el motor de negociación (vía
    main.py) para leer `disposicion_a_negociar`/tasas de aceptación de UN
    candidato puntual, sin que el LLM tenga que repetirle esos datos al
    backend (mismo principio que en el resto del contrato: lo que el
    cliente ya puede resolver, no se lo pedimos al modelo)."""

    return next((t for t in TRANSPORTISTAS if t["id"] == transportista_id), None)


def buscar_candidatos(
    puerto: Optional[str] = None,
    max_distancia_km: Optional[float] = None,
    limite: Optional[int] = None,
) -> list[dict]:
    """Filtra por puerto (si se pasa) y por distancia máxima (si se pasa).

    Sin `limite`: devuelve todos los que pasaron el filtro, ordenados por
    cercanía al puerto — así "descartar a los que están muy lejos" es una
    decisión que se puede ver, no un hardcode invisible.

    Con `limite`: en vez de cortar esa misma lista, recalcula un puntaje
    combinado (ver PESOS_SCORE) y devuelve los mejores `limite` por ese
    puntaje — para no mandarle a Volta 11 candidatos de un mismo puerto
    a negociar. El orden deja de ser "por cercanía" y pasa a ser "por
    mejor candidato en conjunto"; cada resultado trae su `puntaje` para
    que se pueda ver por qué quedó adentro.
    """
    referencia = PUERTOS.get(puerto) if puerto else None

    candidatos = []
    for t in TRANSPORTISTAS:
        if puerto and puerto not in t["puertos"]:
            continue
        distancia = _distancia_km(referencia, t["ubicacion"]) if referencia else None
        if max_distancia_km is not None and distancia is not None and distancia > max_distancia_km:
            continue
        candidatos.append({**t, "distancia_km": distancia})

    if referencia and candidatos:
        _calcular_puntajes(candidatos)
    else:
        for c in candidatos:
            c["puntaje"] = None

    if limite is not None:
        candidatos.sort(key=lambda c: c["puntaje"] or 0.0, reverse=True)
        candidatos = candidatos[:limite]
    else:
        candidatos.sort(key=lambda c: (c["distancia_km"] is None, c["distancia_km"] or 0))

    return candidatos

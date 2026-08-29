"""
Datos ficticios de transportistas — resuelve "a quién llama Volta".

El brief permite inventar catálogo y datos ("Catálogo, prices, mandatos,
protocolos... pueden inventarse"). Esto es justo eso: un fixture chico,
no una base de datos real, pero con la forma que tendría una real —
así el filtro de candidatos (por puerto y por distancia) es lógica de
verdad, no un número mágico hardcodeado en el prompt del agente.

Las coordenadas de los puertos son aproximadas (alcanza para que la
distancia tenga sentido en la demo, no hace falta precisión de GPS real).
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


class Transportista(TypedDict):
    id: str
    nombre: str
    puertos: list[str]  # puertos donde opera
    ubicacion: Coordenadas  # base actual del transportista
    disposicion_a_negociar: int  # 1-5, cuánto margen suele ceder
    puntualidad: int  # 1-5, historial de cumplimiento
    tarifa_referencia: float  # tarifa base típica, en MXN
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
        "telefono": "+52 229 555 0105",
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


def buscar_candidatos(
    puerto: Optional[str] = None, max_distancia_km: Optional[float] = None
) -> list[dict]:
    """Filtra por puerto (si se pasa) y devuelve ordenado por distancia
    al puerto — así "descartar a los que están muy lejos" es una
    decisión que se puede ver, no un hardcode invisible."""
    referencia = PUERTOS.get(puerto) if puerto else None

    candidatos = []
    for t in TRANSPORTISTAS:
        if puerto and puerto not in t["puertos"]:
            continue
        distancia = _distancia_km(referencia, t["ubicacion"]) if referencia else None
        if max_distancia_km is not None and distancia is not None and distancia > max_distancia_km:
            continue
        candidatos.append({**t, "distancia_km": distancia})

    candidatos.sort(key=lambda c: (c["distancia_km"] is None, c["distancia_km"] or 0))
    return candidatos

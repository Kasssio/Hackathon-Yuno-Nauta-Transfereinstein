"""
Seedea el caso mínimo del brief (Textiles Pacífico / Volta) en la API,
para que el frontend tenga datos reales desde el minuto uno en vez de
esperar a que la voz esté lista.

Uso:
  1) Levantar la API en otra terminal:
       cd backend && uvicorn app.main:app --reload --port 8000
  2) Correr:
       python scripts/seed_demo.py

Imprime los ids de la operación y el mandato — guardátelos, son los
que va a necesitar el frontend (o pasalos por query param si arman
las pantallas con un solo caso hardcodeado, como conviene para la demo).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import requests

BASE_URL = "http://localhost:8000"


def main() -> None:
    try:
        requests.get(f"{BASE_URL}/health", timeout=2)
    except requests.exceptions.ConnectionError:
        print(f"No puedo conectar a {BASE_URL} — ¿está corriendo `uvicorn app.main:app --port 8000`?")
        sys.exit(1)

    op = requests.post(f"{BASE_URL}/operaciones", json={
        "cliente": "Textiles Pacífico",
        "contenedor_id": "MSCU1234567",
        "puerto_origen": "Manzanillo",
        "destino": "Guadalajara",
    }).json()

    mandato = requests.post(f"{BASE_URL}/mandatos", json={
        "operacion_id": op["id"],
        "tope_precio": 450,
        "ventana_inicio": "2026-08-28",
        "ventana_fin": "2026-08-30",
        "horario_inicio": "09:00",
        "horario_fin": "18:00",
        "condiciones": [],
        "vigente_hasta": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }).json()

    print("Operación creada:")
    print(f"  operacion_id = {op['id']}")
    print(f"  mandato_id   = {mandato['id']}")
    print(f"\nProbalo en el navegador: {BASE_URL}/operaciones/{op['id']}/mandato")
    print(f"Reset total cuando haga falta rehearsar de nuevo: POST {BASE_URL}/debug/reset")

    candidatos = requests.get(f"{BASE_URL}/transportistas", params={"puerto": op["puerto_origen"]}).json()
    print(f"\nTransportistas candidatos para {op['puerto_origen']} (a quién PODRÍA llamar Volta) — {len(candidatos)} en total:")
    for c in candidatos:
        print(
            f"  {c['id']:<20} {c['nombre']:<28} {c['distancia_km']:>6} km  "
            f"negociación={c['disposicion_a_negociar']}  puntualidad={c['puntualidad']}  "
            f"aceptación_general={c['tasa_aceptacion_general']:.2f}  aceptación_corto_plazo={c['tasa_aceptacion_corto_plazo']:.2f}"
        )

    top3 = requests.get(f"{BASE_URL}/transportistas", params={"puerto": op["puerto_origen"], "limite": 3}).json()
    print(f"\nTop 3 por puntaje combinado (a quién llama Volta en la demo, negociación en vivo acotada):")
    for c in top3:
        print(f"  {c['id']:<20} {c['nombre']:<28} puntaje={c['puntaje']}  ({c['distancia_km']} km)")


if __name__ == "__main__":
    main()

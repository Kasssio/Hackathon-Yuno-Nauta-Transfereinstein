"""
Simulador de escenarios contra la API — para probar el circuito
completo SIN esperar a que la voz esté lista.

Cada escenario hace lo que en la demo real haría Volta por teléfono,
pero como llamadas HTTP directas: así vos (o cualquiera del equipo)
puede rehearsar el caso mínimo del brief (Textiles Pacífico) y, sobre
todo, el momento del trial by fire (revocar el mandato en vivo) sin
depender del pipeline de voz de Marcos ni de los prompts de Sofía.

Uso:
  1) Levantar la API en otra terminal:
       cd backend && uvicorn app.main:app --reload --port 8000
  2) Correr este script:
       python scripts/simulate_scenarios.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

import requests

BASE_URL = "http://localhost:8000"

fails = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    estado = "OK  " if condicion else "FAIL"
    print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
    if not condicion:
        fails.append(nombre)


def main() -> None:
    try:
        requests.get(f"{BASE_URL}/health", timeout=2)
    except requests.exceptions.ConnectionError:
        print(f"No puedo conectar a {BASE_URL} — ¿está corriendo `uvicorn app.main:app --port 8000`?")
        sys.exit(1)

    print("\n=== Caso mínimo: Textiles Pacífico / Volta ===\n")

    # --- setup: operación + mandato ("reservar un camión para el jueves, hasta $9.000 MXN") ---
    op = requests.post(f"{BASE_URL}/operaciones", json={
        "cliente": "Textiles Pacífico",
        "contenedor_id": "MSCU1234567",
        "puerto_origen": "Manzanillo",
        "destino": "Guadalajara",
    }).json()

    mandato = requests.post(f"{BASE_URL}/mandatos", json={
        "operacion_id": op["id"],
        "tope_precio": 9000,
        "ventana_inicio": "2026-08-28",
        "ventana_fin": "2026-08-30",
        "condiciones": [],
        "vigente_hasta": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }).json()

    # --- escenario 1: negociación feliz, dentro del mandato ---
    r1 = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op["id"], "mandato_id": mandato["id"], "call_id": "call-1",
        "contraparte": "Transportes del Norte", "tipo": "reserva",
        "monto": 8500, "fecha_retiro": "2026-08-29", "detalle": "camión jueves 10am",
    }).json()
    check("Escenario 1 — reserva dentro del mandato se aprueba", r1["aprobado"])

    # --- escenario 2: intento fuera de mandato (monto excedido) ---
    op2 = requests.post(f"{BASE_URL}/operaciones", json={
        "cliente": "Textiles Pacífico", "contenedor_id": "MSCU7654321",
        "puerto_origen": "Manzanillo", "destino": "Guadalajara",
    }).json()
    mandato2 = requests.post(f"{BASE_URL}/mandatos", json={
        "operacion_id": op2["id"], "tope_precio": 9000,
        "ventana_inicio": "2026-08-28", "ventana_fin": "2026-08-30", "condiciones": [],
        "vigente_hasta": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }).json()
    r2 = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op2["id"], "mandato_id": mandato2["id"], "call_id": "call-2",
        "contraparte": "Transportes Express", "tipo": "reserva",
        "monto": 12000, "fecha_retiro": "2026-08-29", "detalle": "\"oferta especial\"",
    }).json()
    check("Escenario 2 — monto sobre el tope se rechaza", not r2["aprobado"], r2["motivo"])

    # --- escenario 3: intento adversarial — partir la compra en dos llamadas ---
    op3 = requests.post(f"{BASE_URL}/operaciones", json={
        "cliente": "Textiles Pacífico", "contenedor_id": "MSCU1111111",
        "puerto_origen": "Manzanillo", "destino": "Guadalajara",
    }).json()
    mandato3 = requests.post(f"{BASE_URL}/mandatos", json={
        "operacion_id": op3["id"], "tope_precio": 9000,
        "ventana_inicio": "2026-08-28", "ventana_fin": "2026-08-30", "condiciones": [],
        "vigente_hasta": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }).json()
    parte1 = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op3["id"], "mandato_id": mandato3["id"], "call_id": "call-3a",
        "contraparte": "Transportes X", "tipo": "reserva",
        "monto": 6000, "fecha_retiro": "2026-08-29", "detalle": "parte 1",
    }).json()
    parte2 = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op3["id"], "mandato_id": mandato3["id"], "call_id": "call-3b",
        "contraparte": "Transportes X", "tipo": "reserva",
        "monto": 6000, "fecha_retiro": "2026-08-29", "detalle": "\"cargo adicional\" — parte 2",
    }).json()
    check("Escenario 3a — primera reserva ($6.000) se aprueba", parte1["aprobado"])
    check(
        "Escenario 3b — segunda reserva partida ($6.000 más) se rechaza",
        not parte2["aprobado"], parte2["motivo"],
    )

    # --- escenario 4: reprogramación del mismo booking SÍ se permite ---
    reprog = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op["id"], "mandato_id": mandato["id"], "call_id": "call-4",
        "contraparte": "Transportes del Norte", "tipo": "reprogramacion",
        "monto": 8500, "fecha_retiro": "2026-08-30",
        "detalle": "camión roto, se corre a viernes",
    }).json()
    check("Escenario 4 — reprogramar el mismo booking se aprueba", reprog["aprobado"])

    # --- escenario 5 (el trial by fire): revocación en vivo ---
    requests.post(f"{BASE_URL}/mandatos/{mandato2['id']}/revocar")
    r5 = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op2["id"], "mandato_id": mandato2["id"], "call_id": "call-5",
        "contraparte": "Transportes Express", "tipo": "reserva",
        "monto": 8000, "fecha_retiro": "2026-08-29", "detalle": "intento después de revocar",
    }).json()
    check("Escenario 5 — TRIAL BY FIRE: revocado en vivo → siguiente intento se rechaza", not r5["aprobado"], r5["motivo"])

    # --- escenario 6: negociación con reconsideración (cierra con 1, aparece
    # algo mejor con 2, cancela 1, cierra con 2 — y vuelve atrás una vez más) ---
    op6 = requests.post(f"{BASE_URL}/operaciones", json={
        "cliente": "Textiles Pacífico", "contenedor_id": "MSCU2222222",
        "puerto_origen": "Manzanillo", "destino": "Guadalajara",
    }).json()
    mandato6 = requests.post(f"{BASE_URL}/mandatos", json={
        "operacion_id": op6["id"], "tope_precio": 9000,
        "ventana_inicio": "2026-08-28", "ventana_fin": "2026-08-30", "condiciones": [],
        "vigente_hasta": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }).json()

    reserva_t1 = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op6["id"], "mandato_id": mandato6["id"], "call_id": "call-6a",
        "contraparte": "Transportes del Norte", "tipo": "reserva",
        "monto": 8800, "fecha_retiro": "2026-08-29", "detalle": "primera oferta",
    }).json()
    check("Escenario 6a — reserva con transportista 1 se aprueba", reserva_t1["aprobado"])

    intento_directo_t2 = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op6["id"], "mandato_id": mandato6["id"], "call_id": "call-6b",
        "contraparte": "Transportes Express", "tipo": "reserva",
        "monto": 8200, "fecha_retiro": "2026-08-29", "detalle": "mejor oferta, sin cancelar la anterior",
    }).json()
    check(
        "Escenario 6b — reservar con transportista 2 SIN cancelar la 1 se rechaza",
        not intento_directo_t2["aprobado"], intento_directo_t2["motivo"],
    )

    cancelacion_t1 = requests.post(
        f"{BASE_URL}/commitments/{reserva_t1['commitment']['id']}/cancelar",
        json={"motivo": "apareció una oferta mejor con Transportes Express"},
    ).json()
    check("Escenario 6c — cancelar la reserva con transportista 1", cancelacion_t1.get("cancelado") is True)

    reserva_t2 = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op6["id"], "mandato_id": mandato6["id"], "call_id": "call-6d",
        "contraparte": "Transportes Express", "tipo": "reserva",
        "monto": 8200, "fecha_retiro": "2026-08-29", "detalle": "ahora sí, con la 1 ya cancelada",
    }).json()
    check("Escenario 6d — ahora sí se aprueba la reserva con transportista 2", reserva_t2["aprobado"])

    # transportista 1 vuelve con una oferta todavía mejor — Volta vuelve atrás
    cancelacion_t2 = requests.post(
        f"{BASE_URL}/commitments/{reserva_t2['commitment']['id']}/cancelar",
        json={"motivo": "transportista 1 volvió con una oferta mejor"},
    ).json()
    reserva_t1_de_nuevo = requests.post(f"{BASE_URL}/commitments", json={
        "operacion_id": op6["id"], "mandato_id": mandato6["id"], "call_id": "call-6e",
        "contraparte": "Transportes del Norte", "tipo": "reserva",
        "monto": 8000, "fecha_retiro": "2026-08-29", "detalle": "contraoferta, la mejor de las tres",
    }).json()
    check(
        "Escenario 6e — vuelve atrás: cancela la 2, reserva de nuevo con transportista 1",
        cancelacion_t2.get("cancelado") is True and reserva_t1_de_nuevo["aprobado"],
    )

    # --- trail auditable ---
    trail = requests.get(f"{BASE_URL}/operaciones/{op['id']}/trail").json()
    check("Trail auditable tiene entradas para la operación 1", len(trail) > 0, f"{len(trail)} entradas")

    print(f"\n{'='*50}")
    if fails:
        print(f"❌ {len(fails)} escenario(s) fallaron: {fails}")
        sys.exit(1)
    print("✅ Todos los escenarios pasaron.")


if __name__ == "__main__":
    main()

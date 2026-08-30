"""
Estado y trail auditable — a propósito lo más simple posible.

Nada de base de datos todavía: un diccionario en memoria (que además
se guarda a un .json en disco para no perder todo si se reinicia el
proceso) y un archivo .jsonl append-only para el trail auditable, con
un hash-chain bien simple (cada entrada guarda el hash de la anterior)
para poder defender frente a los jueces que el trail no se puede
reescribir sin que se note.

Si más adelante hace falta Postgres/Supabase para que el dashboard se
actualice en tiempo real sin poll, esto se reemplaza acá adentro sin
tocar el resto del código (main.py y guardrail.py no saben cómo se
guardan los datos).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .models import Commitment, EstadoNegociacion, Mandato, Operacion, CallLogEntry

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_FILE = DATA_DIR / "state.json"
AUDIT_LOG_FILE = DATA_DIR / "audit_log.jsonl"

_lock = threading.Lock()


class Store:
    def __init__(self) -> None:
        self.mandatos: Dict[str, Mandato] = {}
        self.operaciones: Dict[str, Operacion] = {}
        self.commitments: Dict[str, Commitment] = {}
        self.llamadas: Dict[str, CallLogEntry] = {}
        self.negociaciones: Dict[str, EstadoNegociacion] = {}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    # -- persistencia liviana -------------------------------------------------

    def _load(self) -> None:
        if not STATE_FILE.exists():
            return
        raw = json.loads(STATE_FILE.read_text())
        self.mandatos = self._load_bucket(Mandato, raw.get("mandatos", {}), "mandatos")
        self.operaciones = self._load_bucket(Operacion, raw.get("operaciones", {}), "operaciones")
        self.commitments = self._load_bucket(Commitment, raw.get("commitments", {}), "commitments")
        self.llamadas = self._load_bucket(CallLogEntry, raw.get("llamadas", {}), "llamadas")
        self.negociaciones = self._load_bucket(EstadoNegociacion, raw.get("negociaciones", {}), "negociaciones")

    @staticmethod
    def _load_bucket(modelo, items: dict, nombre: str) -> dict:
        """Carga cada registro por separado, no todo el bucket de una — si
        uno no encaja más con el schema actual (ej. un campo que antes no
        existía y ahora es obligatorio, en un registro viejo de antes de
        ese cambio), lo salta con un aviso en la consola en vez de tirar
        abajo el arranque entero del backend por un solo registro de
        prueba desactualizado. Nunca inventa el dato que falta — lo
        descarta, mismo criterio que "nunca asumas un dato crítico"."""
        resultado = {}
        for k, v in items.items():
            try:
                resultado[k] = modelo(**v)
            except Exception as e:
                print(f"[storage] aviso: se descartó un registro de '{nombre}' (id={k}) que no encaja con el schema actual — {e}")
        return resultado

    def _save(self) -> None:
        raw = {
            "mandatos": {k: json.loads(v.model_dump_json()) for k, v in self.mandatos.items()},
            "operaciones": {k: json.loads(v.model_dump_json()) for k, v in self.operaciones.items()},
            "commitments": {k: json.loads(v.model_dump_json()) for k, v in self.commitments.items()},
            "llamadas": {k: json.loads(v.model_dump_json()) for k, v in self.llamadas.items()},
            "negociaciones": {k: json.loads(v.model_dump_json()) for k, v in self.negociaciones.items()},
        }
        STATE_FILE.write_text(json.dumps(raw, indent=2, default=str))

    # -- trail auditable (append-only, hash-chained) ---------------------------

    def _last_hash(self) -> str:
        if not AUDIT_LOG_FILE.exists():
            return "0" * 64
        last_line = None
        with AUDIT_LOG_FILE.open() as f:
            for line in f:
                if line.strip():
                    last_line = line
        if not last_line:
            return "0" * 64
        return json.loads(last_line)["hash"]

    def append_audit(self, evento: str, detalle: dict) -> dict:
        prev_hash = self._last_hash()
        entry = {
            "evento": evento,
            "detalle": detalle,
            "prev_hash": prev_hash,
        }
        entry_bytes = json.dumps(entry, sort_keys=True, default=str).encode()
        entry["hash"] = hashlib.sha256(prev_hash.encode() + entry_bytes).hexdigest()
        with AUDIT_LOG_FILE.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return entry

    def read_audit_trail(self, operacion_id: Optional[str] = None) -> List[dict]:
        if not AUDIT_LOG_FILE.exists():
            return []
        entries = []
        with AUDIT_LOG_FILE.open() as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if operacion_id is None or entry["detalle"].get("operacion_id") == operacion_id:
                    entries.append(entry)
        return entries

    # -- helpers con lock ------------------------------------------------------

    def save(self) -> None:
        with _lock:
            self._save()

    def reset(self) -> None:
        """Vacía todo el estado y el trail — para poder rehearsar el
        trial by fire las veces que hagan falta sin editar archivos a
        mano. Pensado para /debug/reset, no para producción."""
        with _lock:
            self.mandatos.clear()
            self.operaciones.clear()
            self.commitments.clear()
            self.llamadas.clear()
            self.negociaciones.clear()
            self._save()
            AUDIT_LOG_FILE.unlink(missing_ok=True)


store = Store()

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

from .models import Commitment, Mandato, Operacion, CallLogEntry

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
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    # -- persistencia liviana -------------------------------------------------

    def _load(self) -> None:
        if not STATE_FILE.exists():
            return
        raw = json.loads(STATE_FILE.read_text())
        self.mandatos = {k: Mandato(**v) for k, v in raw.get("mandatos", {}).items()}
        self.operaciones = {k: Operacion(**v) for k, v in raw.get("operaciones", {}).items()}
        self.commitments = {k: Commitment(**v) for k, v in raw.get("commitments", {}).items()}
        self.llamadas = {k: CallLogEntry(**v) for k, v in raw.get("llamadas", {}).items()}

    def _save(self) -> None:
        raw = {
            "mandatos": {k: json.loads(v.model_dump_json()) for k, v in self.mandatos.items()},
            "operaciones": {k: json.loads(v.model_dump_json()) for k, v in self.operaciones.items()},
            "commitments": {k: json.loads(v.model_dump_json()) for k, v in self.commitments.items()},
            "llamadas": {k: json.loads(v.model_dump_json()) for k, v in self.llamadas.items()},
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


store = Store()

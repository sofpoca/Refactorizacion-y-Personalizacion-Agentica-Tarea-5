"""Lectura del archivo JSON de entrada."""
from __future__ import annotations

import json
from pathlib import Path


def load_records(path) -> list:
    """Lee el JSON. Debe ser una lista; los elementos se validan despues, uno a uno."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("El archivo JSON debe contener una lista de transacciones.")
    return data

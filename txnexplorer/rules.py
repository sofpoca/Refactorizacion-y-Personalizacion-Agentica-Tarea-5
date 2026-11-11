"""Carga y verificacion del archivo de reglas."""
from __future__ import annotations

import decimal
import json
from pathlib import Path

from .models import STATUSES


def load_rules(path) -> dict:
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("supported_currencies", "status_mapping", "sources", "validation", "currency_symbols", "rounding"):
        if key not in rules:
            raise ValueError(f"rules.json: falta la seccion '{key}'")

    lookup = {}
    for canonical, aliases in rules["status_mapping"].items():
        if canonical not in STATUSES:
            raise ValueError(f"rules.json: estado canonico invalido '{canonical}'")
        for alias in aliases:
            alias = alias.strip().lower()
            if alias in lookup:
                raise ValueError(f"rules.json: alias de estado duplicado '{alias}'")
            lookup[alias] = canonical
    rules["_status_lookup"] = lookup

    mode = rules["rounding"].get("mode", "")
    if not hasattr(decimal, mode) or not mode.startswith("ROUND_"):
        raise ValueError(f"rules.json: modo de redondeo invalido '{mode}'")
    rules["_rounding_mode"] = getattr(decimal, mode)
    return rules

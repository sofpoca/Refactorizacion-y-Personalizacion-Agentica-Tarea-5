"""Metricas sobre el resultado del pipeline."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import List

from .models import STATUSES, InvalidRecord, Transaction


def compute_metrics(valid: List[Transaction], invalid: List[InvalidRecord]) -> dict:
    total = len(valid) + len(invalid)
    by_status = {s: 0 for s in STATUSES}
    by_currency = {}
    by_source = {}

    for t in valid:
        by_status[t.status] += 1
        c = by_currency.setdefault(t.currency, {"count": 0, "total_all": Decimal("0"), "total_success": Decimal("0")})
        c["count"] += 1
        c["total_all"] += t.amount
        if t.status == "SUCCESS":
            c["total_success"] += t.amount
        by_source.setdefault(t.source, {"valid": 0, "invalid": 0})["valid"] += 1

    for r in invalid:
        by_source.setdefault(r.source, {"valid": 0, "invalid": 0})["invalid"] += 1

    return {
        "total": total,
        "valid": len(valid),
        "invalid": len(invalid),
        "needs_review": sum(1 for t in valid if t.flags),
        "valid_pct": round(100 * len(valid) / total, 1) if total else 0.0,
        "by_status": by_status,
        "by_currency": dict(sorted(by_currency.items())),
        "by_source": dict(sorted(by_source.items())),
        "invalid_reasons": dict(Counter(i.code for r in invalid for i in r.issues).most_common()),
    }


def metrics_to_jsonable(m: dict) -> dict:
    """Copia de las metricas con Decimal -> float (antes se hacia dentro de la ruta Flask)."""
    out = dict(m)
    out["by_currency"] = {
        cur: {k: (v if k == "count" else float(v)) for k, v in vals.items()}
        for cur, vals in m["by_currency"].items()
    }
    return out

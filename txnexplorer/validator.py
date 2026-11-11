"""Validacion: criterios de validez/descarte sobre registros YA normalizados.

Politica (ver rules.json -> notes.invalid_policy): los invalidos no se descartan,
se separan en cuarentena con su motivo.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Set, Tuple

from .models import STATUSES, Issue, Transaction


def validate_transaction(txn: Transaction, rules: dict, seen: Set[Tuple[str, str]]) -> List[Issue]:
    cfg = rules["validation"]
    issues: List[Issue] = []

    if txn.currency not in rules["supported_currencies"]:
        issues.append(Issue("UNSUPPORTED_CURRENCY", f"Moneda no soportada: {txn.currency}"))

    if txn.amount <= Decimal(str(cfg["min_amount_exclusive"])):
        issues.append(Issue("AMOUNT_OUT_OF_RANGE", f"El monto debe ser mayor que {cfg['min_amount_exclusive']} (llego {txn.amount})"))
    elif txn.amount > Decimal(str(cfg["max_amount"])):
        issues.append(Issue("AMOUNT_OUT_OF_RANGE", f"El monto excede el maximo permitido {cfg['max_amount']} (llego {txn.amount})"))

    if txn.status not in STATUSES:
        issues.append(Issue("BAD_STATUS", f"Estado fuera del esquema: {txn.status}"))

    if cfg.get("reject_future_timestamps"):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if txn.timestamp > now:  # ISO-8601 en UTC se compara bien como texto
            issues.append(Issue("FUTURE_DATE", f"Fecha en el futuro: {txn.timestamp}"))

    key = (txn.source, txn.id)
    if cfg.get("reject_duplicates") and key in seen:
        issues.append(Issue("DUPLICATE", f"Id duplicado en {txn.source}: {txn.id} (se conserva la primera aparicion)"))

    if not issues:
        seen.add(key)
    return issues

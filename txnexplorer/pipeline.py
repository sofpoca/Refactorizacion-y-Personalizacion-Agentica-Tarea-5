"""Orquesta: detectar fuente -> normalizar -> validar -> separar validas/invalidas (+ auditoria)."""
from __future__ import annotations

from typing import List, Tuple

from .models import AuditEntry, InvalidRecord, Issue, Transaction
from .normalizer import detect_source, normalize_record
from .validator import validate_transaction

UNKNOWN_SOURCE = "desconocida"


def run_pipeline(records: list, rules: dict) -> Tuple[List[Transaction], List[InvalidRecord], List[AuditEntry]]:
    valid: List[Transaction] = []
    invalid: List[InvalidRecord] = []
    audit: List[AuditEntry] = []
    seen = set()

    for index, record in enumerate(records):
        source = detect_source(record, rules)
        if source is None:
            reason = "El registro no es un objeto JSON" if not isinstance(record, dict) \
                else "No se pudo detectar la fuente (ningun campo identificador conocido)"
            invalid.append(InvalidRecord(index, UNKNOWN_SOURCE, record, [Issue("UNKNOWN_SOURCE", reason)]))
            continue

        txn, issues = normalize_record(record, source, rules)
        if txn is not None:
            issues = validate_transaction(txn, rules, seen)
        if issues:
            invalid.append(InvalidRecord(index, source, record, issues))
            continue

        valid.append(txn)
        if txn.original_amount is not None:  # solo se audita lo que fue aceptado
            audit.append(AuditEntry(index, txn.id, source, "ROUNDING", txn.currency, txn.original_amount, txn.amount,
                                    f"{rules['rounding']['mode']} a {rules['supported_currencies'][txn.currency]} decimales"))
    return valid, invalid, audit

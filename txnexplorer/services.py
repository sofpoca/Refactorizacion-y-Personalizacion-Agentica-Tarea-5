"""Servicio de procesamiento: UNICO lugar que orquesta cargar -> pipeline -> metricas -> log.

Lo usan la interfaz web (app.py) y los skills de los agentes. Antes esta logica
estaba mezclada con Flask dentro de app.py (_context).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .audit import write_audit_log
from .config import Settings
from .loader import load_records
from .metrics import compute_metrics
from .models import AuditEntry, InvalidRecord, Transaction
from .pipeline import run_pipeline
from .rules import load_rules


class DatasetNotFoundError(LookupError):
    """El dataset pedido no existe en data/ (lista blanca: evita path traversal)."""


@dataclass
class ProcessedData:
    dataset: str
    rules: dict
    records_count: int
    valid: List[Transaction]
    invalid: List[InvalidRecord]
    audit: List[AuditEntry]
    metrics: dict


def list_datasets(data_dir) -> List[str]:
    return sorted(p.name for p in Path(data_dir).glob("*.json"))


def process_dataset(settings: Settings, dataset: str, rules: Optional[dict] = None,
                    write_log: bool = True) -> ProcessedData:
    if dataset not in list_datasets(settings.data_dir):
        raise DatasetNotFoundError(f"Dataset no encontrado: {dataset!r}")
    rules = rules if rules is not None else load_rules(settings.rules_path)
    records = load_records(settings.data_dir / dataset)
    valid, invalid, audit = run_pipeline(records, rules)
    if write_log:
        write_audit_log(audit, settings.logs_dir / f"audit_{Path(dataset).stem}.json", dataset)
    return ProcessedData(dataset, rules, len(records), valid, invalid, audit, compute_metrics(valid, invalid))

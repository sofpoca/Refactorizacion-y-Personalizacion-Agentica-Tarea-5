"""Modelo de datos normalizado (esquema final decidido por el estudiante)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, List, NamedTuple, Optional, Tuple

STATUSES = ("SUCCESS", "FAILED", "PENDING")


class Issue(NamedTuple):
    """Un problema detectado en un registro: codigo estable + mensaje legible."""
    code: str
    message: str


@dataclass(frozen=True)
class Transaction:
    """Esquema normalizado. amount es Decimal para evitar errores de coma flotante."""
    id: str
    amount: Decimal
    currency: str      # ISO 4217 en mayusculas
    timestamp: str     # ISO-8601 en UTC, ej. 2025-03-10T14:22:00Z
    status: str        # SUCCESS | FAILED | PENDING
    source: str        # gateway_a | gateway_b | gateway_c
    original_amount: Optional[Decimal] = None   # solo si se aplico redondeo
    flags: Tuple[str, ...] = ()                 # ej. ("REQUIERE_REVISION",)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "amount": float(self.amount),
            "currency": self.currency,
            "timestamp": self.timestamp,
            "status": self.status,
            "source": self.source,
            "original_amount": float(self.original_amount) if self.original_amount is not None else None,
            "flags": list(self.flags),
        }


@dataclass
class InvalidRecord:
    """Registro en cuarentena: se conserva el original y los motivos."""
    index: int
    source: str
    raw: Any
    issues: List[Issue] = field(default_factory=list)


@dataclass(frozen=True)
class AuditEntry:
    """Evidencia de que se aplico un ajuste (redondeo) a un registro aceptado."""
    index: int
    id: str
    source: str
    action: str
    currency: str
    original_amount: Decimal
    adjusted_amount: Decimal
    rule: str

    def to_dict(self) -> dict:
        return {
            "index": self.index, "id": self.id, "source": self.source, "action": self.action,
            "currency": self.currency, "original_amount": str(self.original_amount),
            "adjusted_amount": str(self.adjusted_amount), "rule": self.rule,
        }

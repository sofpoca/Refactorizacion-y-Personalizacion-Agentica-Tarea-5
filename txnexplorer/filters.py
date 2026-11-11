"""Filtros y ordenamiento usados por la interfaz."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import List, Optional

from .models import InvalidRecord, Transaction


def _to_decimal(value: Optional[str]) -> Optional[Decimal]:
    try:
        return Decimal(value) if value not in (None, "") else None
    except InvalidOperation:
        return None


SORTS = {
    "date_desc": (lambda t: t.timestamp, True),
    "date_asc": (lambda t: t.timestamp, False),
    "amount_desc": (lambda t: t.amount, True),
    "amount_asc": (lambda t: t.amount, False),
}


def filter_transactions(txns: List[Transaction], status="", currency="", source="", q="",
                        date_from="", date_to="", min_amount="", max_amount="", sort="date_desc", review="") -> List[Transaction]:
    lo, hi = _to_decimal(min_amount), _to_decimal(max_amount)
    out = []
    for t in txns:
        if status and t.status != status: continue
        if currency and t.currency != currency: continue
        if source and t.source != source: continue
        if review == "1" and not t.flags: continue
        if q and q.lower() not in t.id.lower(): continue
        if date_from and t.timestamp[:10] < date_from: continue
        if date_to and t.timestamp[:10] > date_to: continue
        if lo is not None and t.amount < lo: continue
        if hi is not None and t.amount > hi: continue
        out.append(t)
    key, reverse = SORTS.get(sort, SORTS["date_desc"])
    return sorted(out, key=key, reverse=reverse)


def filter_invalid(invalid: List[InvalidRecord], source="", code="") -> List[InvalidRecord]:
    return [r for r in invalid
            if (not source or r.source == source)
            and (not code or any(i.code == code for i in r.issues))]

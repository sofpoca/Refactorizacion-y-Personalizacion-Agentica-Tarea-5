"""Normalizacion: transforma cada registro crudo al esquema comun.

Aqui solo se TRANSFORMA (montos, moneda, estados, fechas). Los criterios de
validez de negocio (rangos, duplicados, moneda soportada) viven en validator.py.
Todas las reglas salen de config/rules.json.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from .models import Issue, Transaction

_AMOUNT_RE = re.compile(r"^-?[\d.,]+$")
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")


def detect_source(record, rules) -> Optional[str]:
    """Detecta la fuente por su campo identificador ('marker') definido en las reglas."""
    if not isinstance(record, dict):
        return None
    for name, spec in rules["sources"].items():
        if spec["marker"] in record:
            return name
    return None


def _parse_decimal_string(raw, symbols) -> Tuple[Decimal, Optional[str]]:
    """Convierte '100.50', '€99,99', '$1,250.00', '1.234,56' a Decimal.

    Regla: si hay '.' y ',', el ULTIMO separador es el decimal. Si solo hay ',',
    es decimal cuando va seguido de 1-2 digitos al final; si no, es de miles.
    Devuelve (monto, moneda inferida del simbolo o None).
    """
    if isinstance(raw, bool):
        raise ValueError("tipo booleano no es un monto")
    if isinstance(raw, (int, float)):
        return Decimal(str(raw)), None
    if not isinstance(raw, str):
        raise ValueError(f"tipo no soportado: {type(raw).__name__}")

    text, symbol_currency = raw.strip(), None
    for symbol, currency in symbols.items():
        if symbol in text:
            symbol_currency = currency
            text = text.replace(symbol, "")
    text = text.replace(" ", "")

    if not _AMOUNT_RE.match(text):
        raise ValueError(f"formato no reconocido: {raw!r}")
    if "," in text and "." in text:
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        text = text.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in text:
        if text.count(",") == 1 and re.search(r",\d{1,2}$", text):
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    try:
        return Decimal(text), symbol_currency
    except InvalidOperation:
        raise ValueError(f"formato no reconocido: {raw!r}")


def _parse_minor_units(raw, decimals: int) -> Decimal:
    """10050 con 2 decimales -> 100.50. Solo acepta enteros (o cadenas de digitos)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValueError(f"se esperaba un entero en unidades menores, llego {raw!r}")
    if isinstance(raw, str):
        if not raw.strip().lstrip("-").isdigit():
            raise ValueError(f"se esperaba un entero en unidades menores, llego {raw!r}")
        raw = int(raw)
    return Decimal(raw).scaleb(-decimals)


def _parse_timestamp(raw, date_formats) -> str:
    """Devuelve ISO-8601 UTC. Fechas sin zona horaria se asumen UTC."""
    if not isinstance(raw, str):
        raise ValueError(f"se esperaba texto, llego {raw!r}")
    text = raw.strip()
    for fmt in date_formats:
        try:
            if fmt == "ISO8601":
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            else:
                parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raise ValueError(f"fecha {raw!r} no coincide con los formatos {date_formats}")


def normalize_record(record: dict, source: str, rules: dict) -> Tuple[Optional[Transaction], List[Issue]]:
    """Normaliza un registro. Si hay problemas devuelve (None, issues)."""
    spec = rules["sources"][source]
    fields = spec["fields"]
    supported = rules["supported_currencies"]
    issues: List[Issue] = []
    original_amount, flags = None, []

    def get(canonical):
        key = fields.get(canonical)
        value = record.get(key) if key else None
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    def missing(canonical):
        issues.append(Issue("MISSING_FIELD", f"Falta el campo '{fields.get(canonical) or canonical}' ({canonical})"))

    # --- id ---
    raw_id = get("id")
    if raw_id is None:
        missing("id")

    # --- monto (decimal_string) y/o moneda ---
    raw_amount = get("amount")
    amount, symbol_currency = None, None
    if raw_amount is None:
        missing("amount")
    elif spec["amount_format"] == "decimal_string":
        try:
            amount, symbol_currency = _parse_decimal_string(raw_amount, rules["currency_symbols"])
        except ValueError as exc:
            issues.append(Issue("BAD_AMOUNT", f"Monto invalido: {exc}"))

    currency, currency_failed = None, False
    raw_currency = get("currency")
    if raw_currency is not None:
        if isinstance(raw_currency, str) and _CURRENCY_RE.match(raw_currency.strip()):
            currency = raw_currency.strip().upper()
        else:
            currency_failed = True
            issues.append(Issue("BAD_CURRENCY", f"Moneda con formato invalido: {raw_currency!r}"))
    if currency and symbol_currency and currency != symbol_currency:
        issues.append(Issue("CURRENCY_MISMATCH", f"La moneda '{currency}' contradice el simbolo del monto ({symbol_currency})"))
    if currency is None and not currency_failed:
        if spec.get("currency_from_symbol") and symbol_currency:
            currency = symbol_currency
        else:
            missing("currency")

    # --- monto (minor_units) necesita la moneda para saber los decimales ---
    if raw_amount is not None and spec["amount_format"] == "minor_units" and currency:
        if currency not in supported:
            issues.append(Issue("UNSUPPORTED_CURRENCY", f"Moneda no soportada: {currency}"))
        else:
            try:
                amount = _parse_minor_units(raw_amount, supported[currency])
            except ValueError as exc:
                issues.append(Issue("BAD_AMOUNT", f"Monto invalido: {exc}"))

    # --- exceso de decimales: se redondea (con trazabilidad) hasta max_input_decimals; mas que eso => invalido ---
    if amount is not None and spec["amount_format"] == "decimal_string" and currency in supported:
        allowed = supported[currency]
        got = max(0, -amount.as_tuple().exponent)
        limit = max(rules["rounding"]["max_input_decimals"], allowed)
        if got > limit:
            issues.append(Issue("BAD_AMOUNT", f"Demasiados decimales para {currency} (recibidos {got}, maximo aceptado {limit}): {raw_amount!r}"))
        elif got > allowed:
            original_amount = amount
            amount = amount.quantize(Decimal(1).scaleb(-allowed), rounding=rules["_rounding_mode"])
            flags.append(rules["rounding"]["review_flag"])

    # --- estado ---
    status = None
    raw_status = get("status")
    if raw_status is None:
        missing("status")
    else:
        status = rules["_status_lookup"].get(str(raw_status).strip().lower())
        if status is None:
            issues.append(Issue("BAD_STATUS", f"Estado desconocido: {raw_status!r}"))

    # --- fecha ---
    timestamp = None
    raw_ts = get("timestamp")
    if raw_ts is None:
        missing("timestamp")
    else:
        try:
            timestamp = _parse_timestamp(raw_ts, spec["date_formats"])
        except ValueError as exc:
            issues.append(Issue("BAD_DATE", f"Fecha invalida: {exc}"))

    if issues:
        return None, issues
    return Transaction(str(raw_id).strip(), amount, currency, timestamp, status, source,
                       original_amount, tuple(flags)), []

"""Skills integrados. Cada uno envuelve logica YA existente del proyecto (pipeline, filtros, metricas)."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import List

from ..filters import filter_invalid, filter_transactions
from ..metrics import metrics_to_jsonable
from ..models import STATUSES
from ..services import DatasetNotFoundError, list_datasets, process_dataset
from .base import Skill, SkillContext, SkillResult


def _int(value, default):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _fmt_txn(t, rules) -> str:
    decimals = rules["supported_currencies"][t.currency]
    line = f"- {t.id} | {t.amount:,.{decimals}f} {t.currency} | {t.status} | {t.source} | {t.timestamp}"
    if t.flags:
        line += f" | {','.join(t.flags)} (original {t.original_amount})"
    return line


class ListDatasets(Skill):
    name = "list_datasets"
    description = "Lista los archivos JSON disponibles en data/."

    def run(self, ctx: SkillContext) -> SkillResult:
        names = list_datasets(ctx.settings.data_dir)
        if not names:
            return SkillResult.failure("No hay datasets en data/")
        return SkillResult.success("Datasets disponibles: " + ", ".join(names), datasets=names)


class IngestDataset(Skill):
    name = "ingest_dataset"
    description = "Carga un dataset y ejecuta el pipeline (normalizar, validar, cuarentena, auditoria)."
    params = {"dataset": "Nombre del JSON en data/ (opcional; por defecto el ya cargado o el primero)"}

    def run(self, ctx: SkillContext, dataset: str = "") -> SkillResult:
        names = list_datasets(ctx.settings.data_dir)
        target = dataset or ctx.dataset or (names[0] if names else "")
        if not target:
            return SkillResult.failure("No hay datasets en data/")
        try:
            processed = process_dataset(ctx.settings, target, ctx.rules, write_log=ctx.write_logs)
        except DatasetNotFoundError as exc:
            return SkillResult.failure(f"{exc}. Disponibles: {', '.join(names)}")
        except (ValueError, OSError) as exc:  # incluye JSONDecodeError
            return SkillResult.failure(f"No se pudo procesar '{target}': {exc}")
        ctx.processed = processed
        m = processed.metrics
        return SkillResult.success(
            f"Dataset '{target}' procesado: {m['total']} registros -> {m['valid']} validos, "
            f"{m['invalid']} en cuarentena, {m['needs_review']} requieren revision.",
            dataset=target, total=m["total"], valid=m["valid"], invalid=m["invalid"])


class QueryTransactions(Skill):
    name = "query_transactions"
    description = "Filtra y ordena las transacciones validas del dataset cargado."
    params = {
        "status": "SUCCESS | FAILED | PENDING", "currency": "Codigo ISO, ej. USD", "source": "gateway_a|gateway_b|gateway_c",
        "q": "Texto contenido en el id", "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD",
        "min_amount": "Monto minimo", "max_amount": "Monto maximo",
        "sort": "date_desc|date_asc|amount_desc|amount_asc", "review": "'1' = solo REQUIERE_REVISION",
        "limit": "Maximo de filas a mostrar",
    }
    requires_data = True

    def run(self, ctx: SkillContext, status="", currency="", source="", q="", date_from="", date_to="",
            min_amount="", max_amount="", sort="date_desc", review="", limit=None) -> SkillResult:
        status = str(status).upper()
        if status and status not in STATUSES:
            return SkillResult.failure(f"Estado invalido '{status}'. Validos: {', '.join(STATUSES)}")
        rows = filter_transactions(ctx.processed.valid, status=status, currency=str(currency).upper(), source=source,
                                   q=q, date_from=date_from, date_to=date_to, min_amount=str(min_amount),
                                   max_amount=str(max_amount), sort=sort, review=str(review))
        limit = _int(limit, ctx.skills_config["default_limit"])
        shown = rows[:limit]
        head = f"{len(rows)} transaccion(es) coinciden" + (f" (mostrando {len(shown)})" if len(shown) < len(rows) else "") + "."
        text = "\n".join([head] + [_fmt_txn(t, ctx.rules) for t in shown])
        return SkillResult.success(text, count=len(rows), rows=[t.to_dict() for t in shown])


class MetricsSummary(Skill):
    name = "metrics_summary"
    description = "Metricas del dataset: totales, por estado, por moneda y por fuente."
    requires_data = True

    def run(self, ctx: SkillContext) -> SkillResult:
        m, rules = ctx.processed.metrics, ctx.rules
        lines = [f"Totales: {m['total']} procesadas, {m['valid']} validas ({m['valid_pct']}%), {m['invalid']} invalidas.",
                 "Por estado: " + ", ".join(f"{s}={n}" for s, n in m["by_status"].items())]
        for cur, v in m["by_currency"].items():
            d = rules["supported_currencies"][cur]
            lines.append(f"  {cur}: {v['count']} txn, total {v['total_all']:,.{d}f}, solo SUCCESS {v['total_success']:,.{d}f}")
        lines.append("Por fuente: " + ", ".join(f"{s} ({v['valid']} ok / {v['invalid']} inv)" for s, v in m["by_source"].items()))
        return SkillResult.success("\n".join(lines), metrics=metrics_to_jsonable(m))


class ExplainInvalid(Skill):
    name = "explain_invalid"
    description = "Agrupa los registros en cuarentena por motivo, con ejemplos y recomendacion de remediacion."
    params = {"source": "Filtrar por fuente (o 'desconocida')", "code": "Filtrar por codigo de motivo",
              "examples": "Ejemplos por motivo (por defecto 2)"}
    requires_data = True

    def run(self, ctx: SkillContext, source="", code="", examples=2) -> SkillResult:
        records = filter_invalid(ctx.processed.invalid, source, code)
        if not records:
            return SkillResult.success("No hay registros invalidos con esos criterios.", total_invalid=0, by_code=[])
        hints = ctx.skills_config["remediation_hints"]
        groups, counts = defaultdict(list), Counter()
        for r in records:
            for i in r.issues:
                counts[i.code] += 1
                groups[i.code].append((r, i))
        n_ex = _int(examples, 2)
        lines, by_code = [f"{len(records)} registro(s) en cuarentena. Motivos:"], []
        for c, n in counts.most_common():
            hint = hints.get(c, "Sin recomendacion configurada.")
            lines.append(f"- {c} ({n}): {hint}")
            ex = [{"index": r.index, "source": r.source, "message": i.message} for r, i in groups[c][:n_ex]]
            for e in ex:
                lines.append(f"    ej. registro #{e['index']} [{e['source']}]: {e['message']}")
            by_code.append({"code": c, "count": n, "hint": hint, "examples": ex})
        return SkillResult.success("\n".join(lines), total_invalid=len(records), by_code=by_code)


class AuditTrail(Skill):
    name = "audit_trail"
    description = "Lista los ajustes (redondeos) aplicados a registros aceptados, con monto original y ajustado."
    requires_data = True

    def run(self, ctx: SkillContext) -> SkillResult:
        entries = ctx.processed.audit
        if not entries:
            return SkillResult.success("No se aplico ningun ajuste en este dataset.", entries=[])
        lines = [f"{len(entries)} ajuste(s) aplicados:"]
        lines += [f"- #{e.index} {e.id} [{e.source}] {e.action}: {e.original_amount} -> {e.adjusted_amount} {e.currency} ({e.rule})"
                  for e in entries]
        return SkillResult.success("\n".join(lines), entries=[e.to_dict() for e in entries])


class QualityReport(Skill):
    name = "quality_report"
    description = "Informe de calidad del dataset con veredicto segun umbrales configurables."
    requires_data = True

    def run(self, ctx: SkillContext) -> SkillResult:
        m, th = ctx.processed.metrics, ctx.skills_config["quality_thresholds"]
        if m["total"] == 0:
            grade = "SIN DATOS"
        elif m["valid_pct"] >= th["good"]:
            grade = "BUENA"
        elif m["valid_pct"] >= th["warning"]:
            grade = "ACEPTABLE (revisar)"
        else:
            grade = "CRITICA"
        lines = [f"Calidad de '{ctx.processed.dataset}': {grade} ({m['valid_pct']}% validas; umbrales: buena>={th['good']}, aceptable>={th['warning']}).",
                 f"- {m['total']} procesadas: {m['valid']} validas, {m['invalid']} en cuarentena, {m['needs_review']} con REQUIERE_REVISION."]
        if m["invalid_reasons"]:
            lines.append("- Motivos principales: " + ", ".join(f"{c} ({n})" for c, n in list(m["invalid_reasons"].items())[:3]))
        for s, v in m["by_source"].items():
            lines.append(f"- {s}: {v['valid']} validas / {v['invalid']} invalidas")
        return SkillResult.success("\n".join(lines), grade=grade, valid_pct=m["valid_pct"],
                                   invalid_reasons=m["invalid_reasons"])


BUILTIN_SKILLS: List[type] = [ListDatasets, IngestDataset, QueryTransactions, MetricsSummary,
                              ExplainInvalid, AuditTrail, QualityReport]

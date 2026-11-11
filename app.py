"""Interfaz web (Flask) para explorar las transacciones normalizadas.

Refactorizado: aqui solo queda la capa HTTP. La orquestacion vive en txnexplorer.services,
las capacidades en txnexplorer.skills y el comportamiento de los agentes en config/agents.json.

Ejecutar:  python app.py   ->  http://127.0.0.1:5000
"""
from __future__ import annotations

import json

from flask import Flask, abort, jsonify, render_template, request

from txnexplorer.agents import create_agent, list_agents
from txnexplorer.config import Settings
from txnexplorer.filters import SORTS, filter_invalid, filter_transactions
from txnexplorer.metrics import metrics_to_jsonable
from txnexplorer.rules import load_rules
from txnexplorer.services import list_datasets, process_dataset

SETTINGS = Settings.default()

app = Flask(__name__)
app.jinja_env.filters["money"] = lambda v, decimals=2: f"{v:,.{decimals}f}"  # decimales segun la moneda
app.jinja_env.filters["pretty"] = lambda v: json.dumps(v, ensure_ascii=False)


def _context():
    """Resuelve el dataset elegido y arma el contexto de la plantilla (el procesamiento lo hace el servicio)."""
    datasets = list_datasets(SETTINGS.data_dir)
    dataset = request.args.get("dataset") or (datasets[0] if datasets else "")
    if dataset not in datasets:  # lista blanca: evita path traversal
        abort(404, "Dataset no encontrado")
    ctx = {"datasets": datasets, "dataset": dataset, "error": None,
           "view": request.args.get("view") if request.args.get("view") in ("invalid", "audit") else "valid",
           "args": request.args}
    try:
        data = process_dataset(SETTINGS, dataset, load_rules(SETTINGS.rules_path))
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        ctx.update(error=f"No se pudo cargar los datos o las reglas: {exc}", valid=[], invalid=[], audit=[], metrics=None)
        return ctx
    ctx.update(valid=data.valid, invalid=data.invalid, audit=data.audit, metrics=data.metrics, rules=data.rules)
    return ctx


def _filtered_valid(ctx):
    a = request.args
    return filter_transactions(
        ctx["valid"], status=a.get("status", ""), currency=a.get("currency", ""), source=a.get("source", ""),
        q=a.get("q", ""), date_from=a.get("date_from", ""), date_to=a.get("date_to", ""),
        min_amount=a.get("min_amount", ""), max_amount=a.get("max_amount", ""), sort=a.get("sort", "date_desc"),
        review=a.get("review", ""))


@app.route("/")
def index():
    ctx = _context()
    if ctx["error"]:
        return render_template("index.html", **ctx, rows=[], sorts=SORTS)
    if ctx["view"] == "valid":
        rows = _filtered_valid(ctx)
    elif ctx["view"] == "invalid":
        rows = filter_invalid(ctx["invalid"], request.args.get("source", ""), request.args.get("code", ""))
    else:
        rows = ctx["audit"]
    return render_template("index.html", **ctx, rows=rows, sorts=SORTS)


@app.route("/api/transactions")
def api_transactions():
    """Transacciones validas filtradas, en el esquema normalizado (JSON)."""
    ctx = _context()
    if ctx["error"]:
        return jsonify(error=ctx["error"]), 500
    return jsonify([t.to_dict() for t in _filtered_valid(ctx)])


@app.route("/api/audit")
def api_audit():
    ctx = _context()
    if ctx["error"]:
        return jsonify(error=ctx["error"]), 500
    return jsonify([e.to_dict() for e in ctx["audit"]])


@app.route("/api/metrics")
def api_metrics():
    ctx = _context()
    if ctx["error"]:
        return jsonify(error=ctx["error"]), 500
    return jsonify(metrics_to_jsonable(ctx["metrics"]))


@app.route("/api/agents")
def api_agents():
    """Agentes disponibles y los skills que cada uno tiene permitidos."""
    return jsonify({a.id: {"name": a.name, "description": a.description, "skills": list(a.skills)}
                    for a in list_agents(SETTINGS).values()})


@app.route("/api/agent")
def api_agent():
    """Conversa con un agente:  /api/agent?agent=auditor&q=reporte de calidad&dataset=transactions_mixed.json"""
    question = request.args.get("q", "").strip()
    if not question:
        return jsonify(error="Falta el parametro 'q'"), 400
    try:
        agent = create_agent(request.args.get("agent", "auditor"), SETTINGS)
    except KeyError as exc:
        return jsonify(error=str(exc.args[0])), 404
    return jsonify(agent.ask(question, dataset=request.args.get("dataset") or None).to_dict())


if __name__ == "__main__":
    app.run(debug=True)

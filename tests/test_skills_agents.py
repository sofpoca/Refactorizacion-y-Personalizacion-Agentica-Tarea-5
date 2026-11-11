"""Pruebas de skills, agentes y planificadores. Ejecutar:  python -m unittest discover tests -v"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from txnexplorer.agents import create_agent, load_agents_config
from txnexplorer.config import Settings
from txnexplorer.llm import provider_from_env
from txnexplorer.skills import SkillContext, default_registry

SETTINGS = Settings.default(ROOT)
MIXED, VALID = "transactions_mixed.json", "transactions_valid.json"


class FakeLLM:
    def __init__(self, answer):
        self.answer = answer

    def complete(self, system, user):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def ctx_with(dataset):
    ctx = SkillContext(SETTINGS, write_logs=False)
    res = default_registry().get("ingest_dataset").execute(ctx, dataset=dataset)
    assert res.ok, res.error
    return ctx


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.reg = default_registry()

    def test_registry_has_expected_skills(self):
        self.assertEqual(self.reg.names(), ["audit_trail", "explain_invalid", "ingest_dataset", "list_datasets",
                                            "metrics_summary", "quality_report", "query_transactions"])

    def test_skill_needs_data_first(self):
        res = self.reg.get("query_transactions").execute(SkillContext(SETTINGS, write_logs=False))
        self.assertFalse(res.ok)
        self.assertIn("ingest_dataset", res.error)

    def test_unknown_param_and_unknown_dataset_are_failures_not_exceptions(self):
        ctx = ctx_with(VALID)
        self.assertFalse(self.reg.get("metrics_summary").execute(ctx, foo=1).ok)
        self.assertFalse(self.reg.get("ingest_dataset").execute(ctx, dataset="../rules.json").ok)

    def test_query_filters(self):
        ctx, q = ctx_with(VALID), self.reg.get("query_transactions")
        counts = {s: q.execute(ctx, status=s).data["count"] for s in ("SUCCESS", "FAILED", "PENDING")}
        self.assertEqual(counts, {"SUCCESS": 5, "FAILED": 3, "PENDING": 3})
        self.assertEqual(q.execute(ctx, currency="eur").data["count"], 3)
        self.assertEqual(q.execute(ctx, limit=2).data["rows"].__len__(), 2)
        self.assertFalse(q.execute(ctx, status="NOPE").ok)

    def test_explain_invalid_and_quality_grade(self):
        ctx = ctx_with(MIXED)
        res = self.reg.get("explain_invalid").execute(ctx)
        self.assertEqual(res.data["total_invalid"], 17)
        self.assertIn("DUPLICATE", {g["code"] for g in res.data["by_code"]})
        self.assertEqual(self.reg.get("quality_report").execute(ctx).data["grade"], "CRITICA")
        self.assertEqual(self.reg.get("quality_report").execute(ctx_with(VALID)).data["grade"], "BUENA")

    def test_audit_trail(self):
        self.assertEqual(len(self.reg.get("audit_trail").execute(ctx_with(MIXED)).data["entries"]), 1)


class AgentTests(unittest.TestCase):
    def test_auditor_auto_ingests_and_reports(self):
        reply = create_agent("auditor", SETTINGS, write_logs=False).ask("dame un reporte de calidad", dataset=MIXED)
        self.assertTrue(reply.ok)
        self.assertEqual([s.skill for s in reply.steps], ["ingest_dataset", "quality_report", "audit_trail"])
        self.assertIn("CRITICA", reply.message)

    def test_analyst_extracts_params_from_text(self):
        reply = create_agent("analyst", SETTINGS, write_logs=False).ask(
            "muestra las transacciones pendientes en EUR", dataset=VALID)
        q = [s for s in reply.steps if s.skill == "query_transactions"][0]
        self.assertEqual((q.args["status"], q.args["currency"]), ("PENDING", "EUR"))
        self.assertEqual(q.result.data["count"], 2)

    def test_dataset_named_in_message_switches_dataset(self):
        agent = create_agent("auditor", SETTINGS, write_logs=False)
        agent.ask("reporte de calidad de transactions_mixed.json")
        agent.ask("reporte de calidad de transactions_valid.json")
        self.assertEqual(agent.ctx.dataset, VALID)

    def test_scope_is_enforced_by_profile(self):
        # El analista no tiene explain_invalid: la peticion cae en el mensaje de fallback.
        reply = create_agent("analyst", SETTINGS, write_logs=False).ask("por que hay registros invalidos", dataset=MIXED)
        self.assertFalse(reply.ok)
        self.assertEqual(reply.steps, [])

    def test_llm_planner_valid_plan_is_used(self):
        plan = json.dumps([{"skill": "metrics_summary", "args": {}}])
        agent = create_agent("analyst", SETTINGS, provider=FakeLLM(f"```json\n{plan}\n```"), write_logs=False)
        reply = agent.ask("lo que sea", dataset=VALID)
        self.assertEqual([s.skill for s in reply.steps], ["ingest_dataset", "metrics_summary"])

    def test_llm_planner_cannot_escape_permissions(self):
        bad = json.dumps([{"skill": "explain_invalid", "args": {}}])  # no permitido para analyst
        reply = create_agent("analyst", SETTINGS, provider=FakeLLM(bad), write_logs=False).ask("hola", dataset=VALID)
        self.assertEqual(reply.steps, [])  # propuesta descartada y sin intent de reglas -> fallback

    def test_llm_failure_falls_back_to_rules(self):
        for answer in ("no es json", RuntimeError("red caida")):
            agent = create_agent("analyst", SETTINGS, provider=FakeLLM(answer), write_logs=False)
            reply = agent.ask("muestra las transacciones fallidas", dataset=VALID)
            self.assertEqual(reply.steps[-1].skill, "query_transactions")

    def test_provider_from_env(self):
        self.assertIsNone(provider_from_env({}))
        self.assertIsNotNone(provider_from_env({"TXN_LLM_BASE_URL": "http://x", "TXN_LLM_API_KEY": "k", "TXN_LLM_MODEL": "m"}))


class ProfileValidationTests(unittest.TestCase):
    def test_intent_using_disallowed_skill_is_rejected(self):
        cfg = json.loads((ROOT / "config" / "agents.json").read_text(encoding="utf-8"))
        cfg["agents"]["analyst"]["intents"][0]["steps"] = [{"skill": "audit_trail"}]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "agents.json"
            p.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_agents_config(p, default_registry())

    def test_unknown_skill_in_profile_is_rejected(self):
        cfg = json.loads((ROOT / "config" / "agents.json").read_text(encoding="utf-8"))
        cfg["agents"]["analyst"]["skills"].append("no_existe")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "agents.json"
            p.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_agents_config(p, default_registry())


if __name__ == "__main__":
    unittest.main()

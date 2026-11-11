"""Pruebas minimas. Ejecutar:  python -m unittest discover tests -v"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from txnexplorer.loader import load_records
from txnexplorer.metrics import compute_metrics
from txnexplorer.pipeline import run_pipeline
from txnexplorer.rules import load_rules

RULES = load_rules(ROOT / "config" / "rules.json")


class PipelineTests(unittest.TestCase):
    def test_three_sources_normalize_to_same_value(self):
        recs = [
            {"id": "tx_001", "amount": "100.50", "currency": "USD", "timestamp": "2025-03-10 14:22:00", "status": "completed"},
            {"transaction_id": 204, "total": 10050, "currency_code": "usd", "created_at": "10/03/2025 14:22", "state": "OK"},
            {"ref": "A-77", "amount": "€99,99", "date": "2025-03-10T14:22:00Z", "result": "success"},
        ]
        valid, invalid, _ = run_pipeline(recs, RULES)
        self.assertEqual(invalid, [])
        a, b, c = valid
        self.assertEqual((a.amount, b.amount, c.amount), (Decimal("100.50"), Decimal("100.50"), Decimal("99.99")))
        self.assertEqual((a.currency, b.currency, c.currency), ("USD", "USD", "EUR"))
        self.assertEqual({a.timestamp, b.timestamp, c.timestamp}, {"2025-03-10T14:22:00Z"})
        self.assertEqual({t.status for t in valid}, {"SUCCESS"})
        self.assertEqual(b.id, "204")

    def test_valid_file_has_no_invalid(self):
        valid, invalid, audit = run_pipeline(load_records(ROOT / "data" / "transactions_valid.json"), RULES)
        self.assertEqual((len(valid), len(invalid)), (11, 0))
        self.assertEqual(audit, [])

    def test_mixed_file_isolates_every_inconsistency(self):
        records = load_records(ROOT / "data" / "transactions_mixed.json")
        valid, invalid, audit = run_pipeline(records, RULES)
        self.assertEqual(len(valid) + len(invalid), len(records))
        self.assertEqual(len(valid), 13)  # 11 limpias + 1a aparicion de 302 + tx_016 redondeada (10.505)
        self.assertEqual(len(audit), 1)
        codes = {i.code for r in invalid for i in r.issues}
        for expected in ("BAD_AMOUNT", "MISSING_FIELD", "UNSUPPORTED_CURRENCY", "BAD_STATUS", "BAD_DATE",
                         "FUTURE_DATE", "DUPLICATE", "UNKNOWN_SOURCE", "AMOUNT_OUT_OF_RANGE"):
            self.assertIn(expected, codes)

    def _one(self, rec):
        valid, invalid, audit = run_pipeline([rec], RULES)
        return valid, invalid, audit

    def test_rounding_keeps_original_flags_and_audits(self):
        valid, invalid, audit = self._one({"id": "r1", "amount": "10.505", "currency": "USD", "timestamp": "2025-03-14 10:30:00", "status": "ok"})
        t = valid[0]
        self.assertEqual((t.amount, t.original_amount, t.flags), (Decimal("10.51"), Decimal("10.505"), ("REQUIERE_REVISION",)))
        self.assertEqual(t.status, "SUCCESS")  # el estado no se altera
        self.assertEqual((audit[0].action, audit[0].original_amount, audit[0].adjusted_amount), ("ROUNDING", Decimal("10.505"), Decimal("10.51")))

    def test_more_than_three_decimals_is_invalid(self):
        valid, invalid, _ = self._one({"id": "r2", "amount": "10.5051", "currency": "USD", "timestamp": "2025-03-14 10:30:00", "status": "ok"})
        self.assertEqual((valid, invalid[0].issues[0].code), ([], "BAD_AMOUNT"))

    def test_zero_decimal_and_three_decimal_currencies(self):
        v, _, a = self._one({"id": "j", "amount": "1500.50", "currency": "JPY", "timestamp": "2025-03-14 10:30:00", "status": "ok"})
        self.assertEqual(v[0].amount, Decimal("1501"))  # JPY: 0 decimales, ROUND_HALF_UP
        v, _, _ = self._one({"transaction_id": 1, "total": 12345, "currency_code": "kwd", "created_at": "14/03/2025 10:00", "state": "OK"})
        self.assertEqual(v[0].amount, Decimal("12.345"))  # KWD: 3 decimales
        v, _, _ = self._one({"transaction_id": 2, "total": 1500, "currency_code": "JPY", "created_at": "14/03/2025 10:00", "state": "OK"})
        self.assertEqual(v[0].amount, Decimal("1500"))  # unidades menores con 0 decimales

    def test_metrics_consistency(self):
        valid, invalid, _ = run_pipeline(load_records(ROOT / "data" / "transactions_mixed.json"), RULES)
        m = compute_metrics(valid, invalid)
        self.assertEqual(m["total"], m["valid"] + m["invalid"])
        self.assertEqual(sum(m["by_status"].values()), m["valid"])
        self.assertEqual(sum(v["count"] for v in m["by_currency"].values()), m["valid"])


if __name__ == "__main__":
    unittest.main()

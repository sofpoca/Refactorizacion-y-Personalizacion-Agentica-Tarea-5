"""Persistencia del registro de auditoria."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .models import AuditEntry


def write_audit_log(entries: List[AuditEntry], path, dataset: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": dataset,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": [e.to_dict() for e in entries],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

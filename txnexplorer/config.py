"""Configuracion centralizada: rutas y carga de archivos de configuracion.

Antes las rutas vivian "hardcodeadas" en app.py. Ahora cualquier consumidor
(web, CLI, agentes, pruebas) obtiene el mismo Settings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SKILLS_CONFIG = {
    "default_limit": 10,
    "quality_thresholds": {"good": 90, "warning": 70},
    "remediation_hints": {},
    "extra_skill_modules": [],
}


@dataclass(frozen=True)
class Settings:
    base: Path
    data_dir: Path
    logs_dir: Path
    rules_path: Path
    agents_path: Path
    skills_config_path: Path

    @classmethod
    def default(cls, base=None) -> "Settings":
        base = Path(base) if base else Path(__file__).resolve().parent.parent
        return cls(
            base=base,
            data_dir=base / "data",
            logs_dir=base / "logs",
            rules_path=base / "config" / "rules.json",
            agents_path=base / "config" / "agents.json",
            skills_config_path=base / "config" / "skills.json",
        )


def load_skills_config(path) -> dict:
    """Lee config/skills.json y rellena lo que falte con valores por defecto."""
    cfg = json.loads(json.dumps(DEFAULT_SKILLS_CONFIG))  # copia profunda
    p = Path(path)
    if p.exists():
        loaded = json.loads(p.read_text(encoding="utf-8"))
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg

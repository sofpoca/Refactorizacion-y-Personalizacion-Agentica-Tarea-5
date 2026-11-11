"""Contrato de un Skill: una capacidad encapsulada, con nombre, parametros declarados y resultado uniforme."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..config import Settings, load_skills_config
from ..rules import load_rules
from ..services import ProcessedData


@dataclass(frozen=True)
class SkillResult:
    ok: bool
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @classmethod
    def success(cls, message: str, **data) -> "SkillResult":
        return cls(True, message, data)

    @classmethod
    def failure(cls, error: str) -> "SkillResult":
        return cls(False, "", {}, error)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "message": self.message, "data": self.data, "error": self.error}


class SkillContext:
    """Estado compartido entre skills de una misma sesion (dataset ya procesado, reglas, configuracion)."""

    def __init__(self, settings: Settings, write_logs: bool = True):
        self.settings = settings
        self.write_logs = write_logs
        self.processed: Optional[ProcessedData] = None
        self._rules: Optional[dict] = None
        self._skills_config: Optional[dict] = None

    @property
    def rules(self) -> dict:
        if self._rules is None:
            self._rules = load_rules(self.settings.rules_path)
        return self._rules

    @property
    def skills_config(self) -> dict:
        if self._skills_config is None:
            self._skills_config = load_skills_config(self.settings.skills_config_path)
        return self._skills_config

    @property
    def dataset(self) -> Optional[str]:
        return self.processed.dataset if self.processed else None


class Skill(ABC):
    """Subclases: definir name, description, params y run(). Se invocan SIEMPRE con execute()."""

    name: str = ""
    description: str = ""
    params: Dict[str, str] = {}        # nombre -> descripcion (lo que el skill acepta)
    requires_data: bool = False        # True si necesita un dataset ya procesado (ver ingest_dataset)

    @abstractmethod
    def run(self, ctx: SkillContext, **kwargs) -> SkillResult: ...

    def execute(self, ctx: SkillContext, **kwargs) -> SkillResult:
        """Envoltorio seguro: valida parametros y prerequisitos; nunca lanza excepciones."""
        unknown = set(kwargs) - set(self.params)
        if unknown:
            return SkillResult.failure(f"Parametros no soportados por '{self.name}': {sorted(unknown)}")
        if self.requires_data and ctx.processed is None:
            return SkillResult.failure(f"'{self.name}' necesita un dataset cargado: ejecutar 'ingest_dataset' primero")
        try:
            return self.run(ctx, **kwargs)
        except Exception as exc:  # un skill roto no debe tumbar al agente
            return SkillResult.failure(f"{type(exc).__name__}: {exc}")

    def describe(self) -> dict:
        return {"name": self.name, "description": self.description, "params": dict(self.params),
                "requires_data": self.requires_data}

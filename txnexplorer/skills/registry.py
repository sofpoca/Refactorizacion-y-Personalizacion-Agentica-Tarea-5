"""Registro de skills: descubrimiento, consulta y extension sin tocar el codigo de los agentes."""
from __future__ import annotations

import importlib
from typing import Dict, Iterable, List, Optional

from .base import Skill


class UnknownSkillError(KeyError):
    pass


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: Dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if not skill.name:
            raise ValueError(f"{type(skill).__name__} no define 'name'")
        if skill.name in self._skills:
            raise ValueError(f"Skill duplicado: {skill.name}")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError:
            raise UnknownSkillError(f"Skill desconocido: {name!r}") from None

    def names(self) -> List[str]:
        return sorted(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def catalog(self, names: Optional[Iterable[str]] = None) -> List[dict]:
        wanted = list(names) if names is not None else self.names()
        return [self.get(n).describe() for n in wanted]

    def load_module(self, dotted_path: str) -> None:
        """Carga un modulo externo que exponga SKILLS = [ClaseSkill, ...] (extension por configuracion)."""
        module = importlib.import_module(dotted_path)
        for cls in getattr(module, "SKILLS", []):
            self.register(cls())


def default_registry(extra_modules: Iterable[str] = ()) -> SkillRegistry:
    from .builtin import BUILTIN_SKILLS
    registry = SkillRegistry()
    for cls in BUILTIN_SKILLS:
        registry.register(cls())
    for module in extra_modules:
        registry.load_module(module)
    return registry

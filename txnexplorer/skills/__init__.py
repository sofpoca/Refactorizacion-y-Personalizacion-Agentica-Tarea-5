"""Skills: capacidades reutilizables del sistema (cada una encapsula una responsabilidad)."""
from .base import Skill, SkillContext, SkillResult
from .registry import SkillRegistry, UnknownSkillError, default_registry

__all__ = ["Skill", "SkillContext", "SkillResult", "SkillRegistry", "UnknownSkillError", "default_registry"]

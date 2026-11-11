"""Fabrica de agentes: une configuracion + registro de skills + planificador."""
from __future__ import annotations

from typing import Dict, Optional

from ..config import Settings
from ..llm import LLMProvider
from ..skills.base import SkillContext
from ..skills.registry import SkillRegistry, default_registry
from .agent import Agent
from .planner import LLMPlanner, RuleBasedPlanner
from .profile import AgentProfile, load_agents_config


def _registry(ctx: SkillContext) -> SkillRegistry:
    return default_registry(ctx.skills_config.get("extra_skill_modules", []))


def list_agents(settings: Optional[Settings] = None) -> Dict[str, AgentProfile]:
    settings = settings or Settings.default()
    ctx = SkillContext(settings, write_logs=False)
    return load_agents_config(settings.agents_path, _registry(ctx)).profiles


def create_agent(agent_id: str, settings: Optional[Settings] = None, provider: Optional[LLMProvider] = None,
                 write_logs: bool = True) -> Agent:
    settings = settings or Settings.default()
    ctx = SkillContext(settings, write_logs=write_logs)
    registry = _registry(ctx)
    cfg = load_agents_config(settings.agents_path, registry)
    if agent_id not in cfg.profiles:
        raise KeyError(f"Agente desconocido: {agent_id!r}. Disponibles: {', '.join(sorted(cfg.profiles))}")
    planner = RuleBasedPlanner(cfg.nlu)
    if provider is not None:
        planner = LLMPlanner(provider, planner)
    return Agent(cfg.profiles[agent_id], registry, ctx, planner, cfg.nlu)

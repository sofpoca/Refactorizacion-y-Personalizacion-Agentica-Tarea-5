"""Perfiles de agente: el COMPORTAMIENTO vive en config/agents.json, no en el codigo."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

from ..skills.registry import SkillRegistry


@dataclass(frozen=True)
class Intent:
    name: str
    keywords: Tuple[str, ...]
    steps: Tuple[Dict[str, Any], ...]      # [{"skill": "...", "args": {...}}]


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    description: str
    system_prompt: str
    skills: Tuple[str, ...]                # lista blanca de skills que este agente puede usar
    intents: Tuple[Intent, ...]
    skill_defaults: Dict[str, Dict[str, Any]]
    fallback_message: str
    default_dataset: str = ""


@dataclass(frozen=True)
class AgentsConfig:
    nlu: Dict[str, Any]
    profiles: Dict[str, AgentProfile]


def load_agents_config(path, registry: SkillRegistry) -> AgentsConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("nlu", "agents"):
        if key not in raw:
            raise ValueError(f"agents.json: falta la seccion '{key}'")
    profiles: Dict[str, AgentProfile] = {}
    for agent_id, spec in raw["agents"].items():
        for key in ("name", "skills", "intents", "fallback_message"):
            if key not in spec:
                raise ValueError(f"agents.json: el agente '{agent_id}' no define '{key}'")
        allowed = tuple(spec["skills"])
        for s in allowed:
            if s not in registry:
                raise ValueError(f"agents.json: '{agent_id}' usa un skill inexistente '{s}'")
        intents = []
        for it in spec["intents"]:
            for step in it["steps"]:
                if step["skill"] not in allowed:
                    raise ValueError(f"agents.json: intent '{it['name']}' de '{agent_id}' usa '{step['skill']}' "
                                     f"que no esta en la lista de skills permitidos del agente")
            intents.append(Intent(it["name"], tuple(it["keywords"]), tuple(it["steps"])))
        defaults = spec.get("skill_defaults", {})
        for s in defaults:
            if s not in allowed:
                raise ValueError(f"agents.json: skill_defaults de '{agent_id}' menciona '{s}' fuera de sus skills")
        profiles[agent_id] = AgentProfile(agent_id, spec["name"], spec.get("description", ""),
                                          spec.get("system_prompt", ""), allowed, tuple(intents), defaults,
                                          spec["fallback_message"], spec.get("default_dataset", ""))
    return AgentsConfig(raw["nlu"], profiles)

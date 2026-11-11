"""Planificadores: convierten un mensaje en una lista de pasos (skill + argumentos).

- RuleBasedPlanner: determinista, sin red (intents y palabras clave vienen del perfil).
- LLMPlanner: pide el plan a un LLM; valida TODO contra el perfil y, si algo falla, cae al de reglas.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from ..llm import LLMProvider
from ..skills.registry import SkillRegistry, UnknownSkillError
from .profile import AgentProfile


@dataclass(frozen=True)
class Step:
    skill: str
    args: Dict[str, Any] = field(default_factory=dict)


class Planner(Protocol):
    def plan(self, message: str, profile: AgentProfile, registry: SkillRegistry, vocab: dict) -> List[Step]: ...


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


def extract_params(message: str, vocab: dict, nlu: dict) -> Dict[str, str]:
    """Extrae parametros del lenguaje natural usando el vocabulario del proyecto (datasets, monedas, fuentes, codigos)."""
    norm = _norm(message)
    tokens = re.findall(r"[a-z0-9_]+", norm)
    params: Dict[str, str] = {}

    for d in vocab.get("datasets", []):
        if d.lower() in message.lower() or Path(d).stem.lower() in tokens:
            params["dataset"] = d
            break
    for status, stems in nlu.get("status_stems", {}).items():
        if any(tok.startswith(_norm(s)) for tok in tokens for s in stems):
            params["status"] = status
            break
    for tok in re.findall(r"\b[A-Za-z]{3}\b", message):
        if tok.upper() in vocab.get("currencies", ()):
            params["currency"] = tok.upper()
            break
    for src in vocab.get("sources", []):
        if src in norm or src.replace("_", " ") in norm:
            params["source"] = src
            break
    for tok in re.findall(r"\b[A-Z][A-Z_]{3,}\b", message):
        if tok in vocab.get("codes", ()):
            params["code"] = tok
            break
    if "revision" in norm:
        params["review"] = "1"
    number = r"\$?\s*(\d[\d,]*(?:\.\d+)?)"
    if m := re.search(r"mayor(?:es)?\s+(?:a|que|de)\s+" + number, norm):
        params["min_amount"] = m.group(1).replace(",", "")
    if m := re.search(r"menor(?:es)?\s+(?:a|que|de)\s+" + number, norm):
        params["max_amount"] = m.group(1).replace(",", "")
    return params


class RuleBasedPlanner:
    def __init__(self, nlu: dict):
        self.nlu = nlu

    def plan(self, message, profile, registry, vocab) -> List[Step]:
        norm = _norm(message)
        best, best_score = None, 0
        for intent in profile.intents:                 # en empate gana el primero declarado
            score = sum(1 for kw in intent.keywords if _norm(kw) in norm)
            if score > best_score:
                best, best_score = intent, score
        if best is None:
            return []
        params = extract_params(message, vocab, self.nlu)
        steps = []
        for spec in best.steps:
            accepted = registry.get(spec["skill"]).params
            args = dict(spec.get("args", {}))
            args.update({k: v for k, v in params.items() if k in accepted})
            steps.append(Step(spec["skill"], args))
        return steps


class LLMPlanner:
    """El LLM solo PROPONE; el codigo valida skill permitido y parametros declarados antes de ejecutar."""

    def __init__(self, provider: LLMProvider, fallback: Planner):
        self.provider, self.fallback = provider, fallback

    def plan(self, message, profile, registry, vocab) -> List[Step]:
        catalog = json.dumps(registry.catalog(profile.skills), ensure_ascii=False)
        system = (f"{profile.system_prompt}\n\nSkills disponibles (JSON): {catalog}\n"
                  "Responde SOLO con un arreglo JSON de pasos: "
                  '[{"skill": "<nombre>", "args": {"<param>": "<valor>"}}]. Usa [] si ningun skill aplica.')
        try:
            raw = self.provider.complete(system, message)
            start, end = raw.index("["), raw.rindex("]") + 1
            proposed = json.loads(raw[start:end])
            steps = [self._validate(p, profile, registry) for p in proposed]
            steps = [s for s in steps if s is not None]
        except Exception:                               # red caida, JSON roto, respuesta inesperada...
            steps = []
        return steps or self.fallback.plan(message, profile, registry, vocab)

    @staticmethod
    def _validate(proposal: Any, profile: AgentProfile, registry: SkillRegistry) -> Optional[Step]:
        if not isinstance(proposal, dict) or proposal.get("skill") not in profile.skills:
            return None
        try:
            accepted = registry.get(proposal["skill"]).params
        except UnknownSkillError:
            return None
        args = proposal.get("args") or {}
        if not isinstance(args, dict):
            return None
        return Step(proposal["skill"], {k: v for k, v in args.items() if k in accepted})

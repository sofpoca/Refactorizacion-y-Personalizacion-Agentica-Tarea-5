"""Agente: planifica, aplica permisos del perfil, ejecuta skills y compone la respuesta."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..services import list_datasets
from ..skills.base import SkillContext, SkillResult
from ..skills.registry import SkillRegistry, UnknownSkillError
from .planner import Planner, Step, extract_params
from .profile import AgentProfile


@dataclass
class StepRecord:
    skill: str
    args: Dict[str, Any]
    result: SkillResult

    def to_dict(self) -> dict:
        return {"skill": self.skill, "args": self.args, "result": self.result.to_dict()}


@dataclass
class AgentReply:
    agent: str
    ok: bool
    message: str
    steps: List[StepRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"agent": self.agent, "ok": self.ok, "message": self.message,
                "steps": [s.to_dict() for s in self.steps]}


class Agent:
    def __init__(self, profile: AgentProfile, registry: SkillRegistry, ctx: SkillContext,
                 planner: Planner, nlu: dict):
        self.profile, self.registry, self.ctx, self.planner, self.nlu = profile, registry, ctx, planner, nlu

    # -- API publica -----------------------------------------------------------------------------
    def ask(self, message: str, dataset: Optional[str] = None) -> AgentReply:
        p = self.profile
        try:
            vocab = self._vocab()
            steps = self.planner.plan(message, p, self.registry, vocab)
            if not steps:
                return AgentReply(p.id, False, self._compose([p.fallback_message]))
            steps = self._with_ingest(steps, message, vocab, dataset)
        except Exception as exc:
            return AgentReply(p.id, False, self._compose([f"[error] No se pudo planificar: {exc}"]))

        records: List[StepRecord] = []
        for step in steps:
            record = self._run_step(step)
            records.append(record)
            if not record.result.ok and step.skill == "ingest_dataset":
                break                                   # sin datos no tiene sentido seguir
        lines = [r.result.message if r.result.ok else f"[error] {r.skill}: {r.result.error}" for r in records]
        return AgentReply(p.id, all(r.result.ok for r in records), self._compose(lines), records)

    # -- internos --------------------------------------------------------------------------------
    def _vocab(self) -> dict:
        return {"datasets": list_datasets(self.ctx.settings.data_dir),
                "currencies": set(self.ctx.rules["supported_currencies"]),
                "sources": list(self.ctx.rules["sources"]),
                "codes": set(self.ctx.skills_config["remediation_hints"])}

    def _with_ingest(self, steps: List[Step], message: str, vocab: dict, dataset: Optional[str]) -> List[Step]:
        """Garantiza que haya datos cargados (y del dataset correcto) antes de los skills que los necesitan."""
        explicit = dataset or extract_params(message, vocab, self.nlu).get("dataset")
        target = explicit or self.ctx.dataset or self.profile.default_dataset
        steps = list(steps)
        has_ingest = any(s.skill == "ingest_dataset" for s in steps)
        needs_data = any(self.registry.get(s.skill).requires_data for s in steps)
        stale = self.ctx.processed is None or (explicit and self.ctx.dataset != explicit)
        if needs_data and not has_ingest and stale:
            steps.insert(0, Step("ingest_dataset", {"dataset": target} if target else {}))
        return [Step(s.skill, {**s.args, "dataset": target}) if s.skill == "ingest_dataset"
                and "dataset" not in s.args and target else s for s in steps]

    def _run_step(self, step: Step) -> StepRecord:
        p = self.profile
        if step.skill not in p.skills:
            return StepRecord(step.skill, step.args, SkillResult.failure(
                f"el agente '{p.name}' no tiene permitido el skill '{step.skill}'"))
        try:
            skill = self.registry.get(step.skill)
        except UnknownSkillError as exc:
            return StepRecord(step.skill, step.args, SkillResult.failure(str(exc)))
        args = {k: v for k, v in {**p.skill_defaults.get(step.skill, {}), **step.args}.items() if k in skill.params}
        return StepRecord(step.skill, args, skill.execute(self.ctx, **args))

    def _compose(self, lines: List[str]) -> str:
        return f"[{self.profile.name}]\n" + "\n\n".join(lines)

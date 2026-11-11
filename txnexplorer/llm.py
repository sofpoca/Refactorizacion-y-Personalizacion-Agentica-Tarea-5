"""Proveedor LLM opcional (solo libreria estandar). Si no hay credenciales, el sistema funciona igual con reglas."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Mapping, Optional, Protocol


class LLMProvider(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class OpenAICompatibleProvider:
    """Cliente minimo para cualquier endpoint compatible con /chat/completions."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0):
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout

    def complete(self, system: str, user: str) -> str:
        body = json.dumps({"model": self.model, "temperature": 0,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user}]}).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]


def provider_from_env(env: Optional[Mapping[str, str]] = None) -> Optional[LLMProvider]:
    """Lee TXN_LLM_BASE_URL, TXN_LLM_API_KEY y TXN_LLM_MODEL. Devuelve None si falta alguna."""
    env = os.environ if env is None else env
    url, key, model = (env.get("TXN_LLM_BASE_URL"), env.get("TXN_LLM_API_KEY"), env.get("TXN_LLM_MODEL"))
    return OpenAICompatibleProvider(url, key, model) if url and key and model else None

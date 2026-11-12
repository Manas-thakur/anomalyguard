"""Optional LLM-suggested fixes via Ollama or any OpenAI-compatible endpoint.

Disabled by default. Suggestions are attached to review items; they are only
written into the data when ``auto_apply`` is on and the model's confidence is
above the configured minimum.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

PROMPT = """You are a data cleaning assistant. One value in a record looks wrong.

Column: {column}
Current value: {value!r}
Problem: {reason}
Full record (JSON): {record}

Suggest the most plausible corrected value for "{column}" using the other fields as context.
Reply with JSON only: {{"value": <corrected value>, "confidence": <0..1>, "rationale": "<one sentence>"}}"""


@dataclass
class Suggestion:
    value: Any
    confidence: float
    rationale: str = ""


def parse_suggestion(text: str) -> Suggestion | None:
    """Extract the first JSON object from a model reply."""
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if "value" not in data:
        return None
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return Suggestion(data["value"], max(0.0, min(conf, 1.0)), str(data.get("rationale", "")))


class LLMSuggester:
    """Ask a local or hosted model for a corrected value.

    ``provider="ollama"`` posts to ``{base_url}/api/generate`` (default
    ``http://localhost:11434``). ``provider="openai"`` posts to
    ``{base_url}/chat/completions`` of any OpenAI-compatible server (vLLM,
    LM Studio, llama.cpp server, hosted APIs); the key is read from
    ``api_key_env``.
    """

    def __init__(
        self,
        provider: str = "ollama",
        model: str = "llama3.1:8b",
        base_url: str | None = None,
        api_key_env: str | None = "OPENAI_API_KEY",
        timeout: float = 60.0,
        temperature: float = 0.0,
        transport: httpx.BaseTransport | None = None,
    ):
        if provider not in ("ollama", "openai"):
            raise ValueError("provider must be 'ollama' or 'openai'")
        self.provider = provider
        self.model = model
        self.base_url = (
            base_url
            or ("http://localhost:11434" if provider == "ollama" else "https://api.openai.com/v1")
        ).rstrip("/")
        self.api_key = os.environ.get(api_key_env) if api_key_env else None
        self.timeout = timeout
        self.temperature = temperature
        self.transport = transport

    def _client(self) -> httpx.Client:
        headers = (
            {"Authorization": f"Bearer {self.api_key}"}
            if self.api_key and self.provider == "openai"
            else {}
        )
        return httpx.Client(timeout=self.timeout, transport=self.transport, headers=headers)

    def complete(self, prompt: str) -> str:
        with self._client() as client:
            if self.provider == "ollama":
                resp = client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": self.temperature},
                    },
                )
                resp.raise_for_status()
                return str(resp.json().get("response", ""))
            resp = client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "temperature": self.temperature,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            return str(resp.json()["choices"][0]["message"]["content"])

    def suggest(
        self, record: dict[str, Any], column: str, value: Any, reason: str
    ) -> Suggestion | None:
        prompt = PROMPT.format(
            column=column, value=value, reason=reason, record=json.dumps(record, default=str)
        )
        return parse_suggestion(self.complete(prompt))

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> LLMSuggester:
        cfg = {
            k: v
            for k, v in cfg.items()
            if k not in ("enabled", "auto_apply", "min_confidence", "max_items")
        }
        return cls(**cfg)

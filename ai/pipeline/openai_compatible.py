from __future__ import annotations

import asyncio
import json
import re
from typing import Any, TypeVar

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from ai.pipeline.model_registry import ModelConfig

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class OpenAICompatibleClient:
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        self._sync_client = OpenAI(
            api_key=model_config.resolved_api_key,
            base_url=model_config.base_url,
        )
        self._async_client = AsyncOpenAI(
            api_key=model_config.resolved_api_key,
            base_url=model_config.base_url,
        )

    async def create_text(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int = 512,
    ) -> str:
        response = await self._async_client.chat.completions.create(
            model=self.model_config.model,
            messages=_build_messages(self.model_config, prompt),
            **_completion_options(self.model_config, temperature, max_tokens=max_tokens),
        )
        return _extract_visible_content(response.choices[0].message.content)

    def create_text_sync(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int = 512,
    ) -> str:
        response = self._sync_client.chat.completions.create(
            model=self.model_config.model,
            messages=_build_messages(self.model_config, prompt),
            **_completion_options(self.model_config, temperature, max_tokens=max_tokens),
        )
        return _extract_visible_content(response.choices[0].message.content)

    async def create_structured(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        text = await self.create_text(_structured_prompt(prompt, schema), max_tokens=768)
        return schema.model_validate(_load_json_payload(text))

    def create_structured_sync(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        text = self.create_text_sync(_structured_prompt(prompt, schema), max_tokens=768)
        return schema.model_validate(_load_json_payload(text))


def _structured_prompt(prompt: str, schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), indent=2, sort_keys=True)
    return (
        "Return only valid JSON that matches the schema below. "
        "Do not wrap the JSON in markdown fences or add commentary.\n\n"
        f"Schema:\n{schema_json}\n\n"
        f"Prompt:\n{prompt}"
    )


def _load_json_payload(text: str) -> Any:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(candidate[start : end + 1])


async def maybe_run_sync(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _extract_visible_content(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"^\s*<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _build_messages(model_config: ModelConfig, prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if _is_qwen3_local_model(model_config):
        # Qwen3 defaults to reasoning mode; inject the documented soft switch so
        # llama.cpp returns final answer text instead of a <think> block.
        messages.append({"role": "system", "content": "/no_think"})
    messages.append({"role": "user", "content": prompt})
    return messages


def _completion_options(
    model_config: ModelConfig,
    temperature: float | None,
    *,
    max_tokens: int,
) -> dict[str, Any]:
    resolved_temperature = model_config.temperature if temperature is None else temperature
    options: dict[str, Any] = {"temperature": resolved_temperature, "max_tokens": max_tokens}
    if _is_qwen3_local_model(model_config) and temperature is None:
        # Qwen recommends sampling params in non-thinking mode; greedy decoding
        # can still degrade output quality even when reasoning is disabled.
        options["temperature"] = max(model_config.temperature, 0.7)
        options["top_p"] = 0.8
    return options


def _is_qwen3_local_model(model_config: ModelConfig) -> bool:
    return model_config.provider == "local" and "qwen3" in model_config.model.lower()

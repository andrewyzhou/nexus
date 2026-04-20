from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ModelConfig:
    name: str
    provider: str
    model: str
    base_url: str
    api_key_env: str | None = None
    api_key: str | None = None
    temperature: float = 0.0
    enabled: bool = True

    @property
    def resolved_api_key(self) -> str | None:
        if self.api_key_env:
            value = os.environ.get(self.api_key_env)
            if value:
                return value
        return self.api_key

    @property
    def available(self) -> bool:
        return self.resolved_api_key is not None and self.base_url != ""


class ModelRegistry:
    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path) if config_path else self.default_path()
        with self.config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        self.defaults = raw.get("defaults", {})
        self._models: dict[str, dict[str, ModelConfig]] = {}
        for role in ("summarizers", "judges"):
            self._models[role] = {}
            for entry in raw.get(role, []):
                normalized = dict(entry)
                base_url = normalized.get("base_url", "")
                base_url_env = normalized.get("base_url_env")
                if base_url_env:
                    base_url = os.environ.get(base_url_env, base_url)
                config = ModelConfig(
                    name=normalized["name"],
                    provider=normalized["provider"],
                    model=normalized["model"],
                    base_url=str(base_url).rstrip("/"),
                    api_key_env=normalized.get("api_key_env"),
                    api_key=normalized.get("api_key"),
                    temperature=float(normalized.get("temperature", 0.0)),
                    enabled=bool(normalized.get("enabled", True)),
                )
                self._models[role][config.name] = config

    @staticmethod
    def default_path() -> Path:
        return Path(__file__).resolve().parents[1] / "config" / "models.yaml"

    def get(self, role: str, name: str) -> ModelConfig:
        try:
            return self._models[role][name]
        except KeyError as exc:
            raise KeyError(f"Unknown {role[:-1]} model '{name}'") from exc

    def list_models(self, role: str, enabled_only: bool = True) -> list[ModelConfig]:
        models = list(self._models[role].values())
        if enabled_only:
            models = [model for model in models if model.enabled]
        return models

    def default_for(self, role: str) -> ModelConfig:
        key = "smoke_summarizer" if role == "summarizers" else "smoke_judge"
        name = self.defaults[key]
        return self.get(role, name)

    def names(self, role: str, enabled_only: bool = True) -> list[str]:
        return [model.name for model in self.list_models(role, enabled_only=enabled_only)]


def load_registry(config_path: str | Path | None = None) -> ModelRegistry:
    return ModelRegistry(config_path=config_path)

"""Where this package runs: under Cairnward's plugin contract (ADR-0017), or standalone.

Under Cairnward, the core starts the plugin with a key and the address of its services, and the
data folder is the plugin's own. Models go through the gateway, outside requests through the
fetch service, and library keys through the key service. The sandbox allows nothing else.

Standalone means no Cairnward: any OpenAI-compatible server and direct network access, with
none of the contract's protections (see the README).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONTRACT = 1
ENV_KEY = "CAIRNWARD_PLUGIN_KEY"
ENV_GATEWAY = "CAIRNWARD_GATEWAY_URL"
ENV_ENVIRONMENT = "CAIRNWARD_ENVIRONMENT"
ENV_DATA = "CAIRNWARD_PLUGIN_DATA"
DEFAULT_ENVIRONMENT = "litreview-offline"


@dataclass(frozen=True)
class Paths:
    data_dir: Path
    state_dir: Path


@dataclass(frozen=True)
class Settings:
    """research.toml, in the data folder."""

    citation_engine: str = "auto"
    grobid_url: str | None = None
    zotero_url: str | None = None
    default_effort: str = "high"
    sources: dict[str, list[str]] = field(default_factory=dict)  # environment -> online sources
    # standalone only: the OpenAI-compatible server's model names
    chat_model: str | None = None
    fast_model: str | None = None
    embed_model: str | None = None


@dataclass(frozen=True)
class Runtime:
    paths: Paths
    settings: Settings
    gateway: str | None
    key: str | None
    environment: str | None

    @property
    def under_contract(self) -> bool:
        return bool(os.environ.get(ENV_KEY)) and self.key == os.environ.get(ENV_KEY)

    def model(self, environment: str, effort: str | None) -> str:
        if not self.under_contract and self.settings.chat_model:
            return self.settings.fast_model if effort == "low" and self.settings.fast_model else (
                self.settings.chat_model)  # fmt: skip
        return f"cw/{environment}:{effort}" if effort else f"cw/{environment}"

    def embed_model(self, environment: str) -> str:
        if not self.under_contract and self.settings.embed_model:
            return self.settings.embed_model
        return f"cw/{environment}:embed"


def _settings(path: Path) -> Settings:
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    known = set(Settings.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{path}: unknown settings: {', '.join(sorted(unknown))}")
    return Settings(**raw)


def default_data_dir() -> Path:
    if value := os.environ.get(ENV_DATA):
        return Path(value)
    if value := os.environ.get("CAIRNWARD_DATA_DIR"):
        return Path(value) / "mcp" / "research"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "cairnward" / "mcp" / "research"


def load() -> Runtime:
    data = default_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    return Runtime(Paths(data, data / "state"), _settings(data / "research.toml"),
                   os.environ.get(ENV_GATEWAY) or os.environ.get("CAIRNWARD_RESEARCH_BASE_URL"),
                   os.environ.get(ENV_KEY) or os.environ.get("CAIRNWARD_RESEARCH_API_KEY"),
                   os.environ.get(ENV_ENVIRONMENT))  # fmt: skip

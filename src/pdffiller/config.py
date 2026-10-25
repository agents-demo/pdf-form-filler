"""Application configuration and LLM settings.

Values are read from environment variables (optionally loaded from a local
``.env`` file) with sensible defaults for the DeepSeek OpenAI-compatible API.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Try to load a project-local .env file first, then a user-level one.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass
class LLMConfig:
    """Configuration for the LLM used to interpret PDF forms."""

    provider: str = "OpenAI"
    api_base: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-v4-flash-vision-exp"
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: float = 180.0
    verify_ssl: bool = True

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            provider=os.getenv("LLM_PROVIDER", "OpenAI"),
            api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash-vision-exp"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.0")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            timeout=float(os.getenv("LLM_TIMEOUT", "180.0")),
            verify_ssl=os.getenv("LLM_SSL_VERIFY", "true").lower() in ("1", "true", "yes", "on"),
        )

    def configured(self) -> bool:
        return bool(self.api_key.strip())


_ENV_KEYS = {
    "provider": "LLM_PROVIDER",
    "api_base": "DEEPSEEK_API_BASE",
    "api_key": "DEEPSEEK_API_KEY",
    "model": "DEEPSEEK_MODEL",
    "temperature": "LLM_TEMPERATURE",
    "max_tokens": "LLM_MAX_TOKENS",
    "timeout": "LLM_TIMEOUT",
    "verify_ssl": "LLM_SSL_VERIFY",
}

_PROXY_ENV_VARS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)


def ensure_direct_connection() -> None:
    """Ensure all LLM HTTP requests connect directly (no proxy).

    httpx/openai inherit ``HTTP_PROXY``/``HTTPS_PROXY``/``ALL_PROXY`` from the
    shell. Those are cleared so every request goes straight to the API
    endpoint; no proxy is ever used.
    """
    for var in _PROXY_ENV_VARS:
        os.environ.pop(var, None)


def default_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def save_to_env(config: LLMConfig, path: Path | None = None) -> None:
    """Persist LLM settings to a dotenv file (project root by default)."""
    path = path or default_env_path()
    lines = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, _, _ = line.partition("=")
                lines[key.strip()] = line.rstrip("\n")

    for field, env_key in _ENV_KEYS.items():
        value = getattr(config, field)
        if isinstance(value, bool):
            value = "true" if value else "false"
        lines[env_key] = f"{env_key}={value}"

    path.write_text("\n".join(lines.values()) + "\n", encoding="utf-8")


@dataclass
class AppConfig:
    """Runtime application configuration."""

    data_path: Path = field(default_factory=lambda: Path("data.json"))
    llm: LLMConfig = field(default_factory=LLMConfig.from_env)

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(llm=LLMConfig.from_env())

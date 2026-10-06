"""Configuration only. No agent, tool or business logic lives here."""
from __future__ import annotations

import os
from dataclasses import dataclass

try:  # .env is optional; real environment variables always win
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

VALID_PROVIDERS = ("ollama", "bedrock")


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    model_provider: str
    ollama_host: str
    ollama_model_id: str
    aws_region: str | None
    bedrock_model_id: str | None
    log_level: str
    max_sessions: int = 100
    session_ttl_seconds: int = 1800


def _int(value, default: int, name: str) -> int:
    if value in (None, ""):
        return default
    try:
        n = int(value)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got '{value}'") from None
    if n <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return n


def load_settings(env: dict | None = None) -> Settings:
    e = os.environ if env is None else env
    provider = (e.get("MODEL_PROVIDER") or "ollama").strip().lower()
    if provider not in VALID_PROVIDERS:
        raise ConfigError(f"MODEL_PROVIDER must be one of {VALID_PROVIDERS}, got '{provider}'")

    settings = Settings(
        model_provider=provider,
        ollama_host=e.get("OLLAMA_HOST") or "http://localhost:11434",
        ollama_model_id=e.get("OLLAMA_MODEL_ID") or "llama3.1",
        aws_region=e.get("AWS_REGION") or e.get("AWS_DEFAULT_REGION") or None,
        bedrock_model_id=e.get("BEDROCK_MODEL_ID") or None,
        log_level=(e.get("LOG_LEVEL") or "INFO").upper(),
        max_sessions=_int(e.get("MAX_SESSIONS"), 100, "MAX_SESSIONS"),
        session_ttl_seconds=_int(e.get("SESSION_TTL_SECONDS"), 1800, "SESSION_TTL_SECONDS"),
    )
    if provider == "bedrock":
        missing = [
            name
            for name, val in (("AWS_REGION", settings.aws_region), ("BEDROCK_MODEL_ID", settings.bedrock_model_id))
            if not val
        ]
        if missing:
            raise ConfigError(f"MODEL_PROVIDER=bedrock requires: {', '.join(missing)}")
    return settings


def simulated_failure_enabled() -> bool:
    """Demo switch used to prove tool failures stay failures."""
    return os.environ.get("SIMULATE_TOOL_FAILURE", "0").strip().lower() in ("1", "true", "yes")

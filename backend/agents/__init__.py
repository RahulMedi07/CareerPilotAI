"""Agent layer for CareerPilot AI.

This package holds everything that "thinks": the deterministic analysers
(``JobAnalyzer``, ``MatchCalculator``), the LLM plumbing (``ollama_handler``),
the agent base class (``base_agent``) and the LangGraph workflow
(``graph_builder``).

``AgentConfig`` lives here, at the top of the package, on purpose. Every other
module in the package needs it, and defining it before the submodule re-exports
at the bottom of this file keeps the import graph acyclic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from config import settings


class LLMProvider(str, Enum):
    """Which backend actually answers a prompt.

    ``AUTO`` means "try Ollama, then Gemini, then Claude" and is the sensible
    default for a laptop that may or may not have Ollama running. Ollama comes
    first because it is free and local; between the two hosted APIs, whichever
    has a key configured wins, and if both do, Gemini is tried first for the
    same reason.
    """

    OLLAMA = "ollama"
    CLAUDE = "claude"
    GEMINI = "gemini"
    AUTO = "auto"

    @classmethod
    def parse(cls, value: Any) -> "LLMProvider":
        """Coerce a string into a provider, tolerating case and whitespace."""
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower()
        if text in ("anthropic", "claude"):
            return cls.CLAUDE
        if text in ("gemini", "google", "google-genai"):
            return cls.GEMINI
        if text in ("ollama", "local"):
            return cls.OLLAMA
        if text in ("auto", "", "fallback"):
            return cls.AUTO
        raise ValueError(
            f"Unknown LLM provider {value!r}. "
            f"Expected one of: {', '.join(p.value for p in cls)}"
        )


@dataclass
class AgentConfig:
    """Everything an agent needs to know about its language model.

    Instances are plain data: no sockets are opened and no models are loaded
    when one is constructed. That keeps agents cheap to create in tests.

    Defaults come from :mod:`config`, so a single ``.env`` file drives the whole
    application. Pass explicit values to override for one agent.
    """

    provider: LLMProvider = LLMProvider.AUTO
    model: str = "mistral"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout: int = 120

    #: Short timeout for the "is Ollama alive?" probe. Deliberately separate
    #: from ``timeout``: we want to wait a long time for a real generation but
    #: give up almost instantly on a daemon that is not running.
    healthcheck_timeout: float = 2.0
    max_retries: int = 2

    # --- Claude fallback ---------------------------------------------------
    fallback_enabled: bool = True
    claude_model: str = "claude-3-5-sonnet-20241022"
    claude_api_key: Optional[str] = field(default=None, repr=False)

    # --- Gemini ------------------------------------------------------------
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_api_key: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.provider = LLMProvider.parse(self.provider)

        if not str(self.model).strip():
            raise ValueError("AgentConfig.model must not be empty")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(
                f"AgentConfig.temperature must be between 0.0 and 2.0, "
                f"got {self.temperature}"
            )
        if self.max_tokens <= 0:
            raise ValueError(
                f"AgentConfig.max_tokens must be positive, got {self.max_tokens}"
            )
        if self.timeout <= 0:
            raise ValueError(
                f"AgentConfig.timeout must be positive, got {self.timeout}"
            )
        if self.healthcheck_timeout <= 0:
            raise ValueError(
                "AgentConfig.healthcheck_timeout must be positive, "
                f"got {self.healthcheck_timeout}"
            )
        if self.max_retries < 0:
            raise ValueError(
                f"AgentConfig.max_retries must not be negative, got {self.max_retries}"
            )

        self.base_url = str(self.base_url).rstrip("/")

    # --- Constructors ------------------------------------------------------

    @classmethod
    def from_settings(cls, **overrides: Any) -> "AgentConfig":
        """Build a config from ``config.settings``, with optional overrides.

        The API key is read from settings first and the ``ANTHROPIC_API_KEY``
        environment variable second, so the key never has to be committed.
        """
        base: Dict[str, Any] = {
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
            "base_url": settings.OLLAMA_BASE_URL,
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
            "timeout": settings.LLM_TIMEOUT_SECONDS,
            "healthcheck_timeout": settings.LLM_HEALTHCHECK_TIMEOUT,
            "max_retries": settings.LLM_MAX_RETRIES,
            "fallback_enabled": settings.LLM_FALLBACK_ENABLED,
            "claude_model": settings.CLAUDE_MODEL,
            "claude_api_key": settings.ANTHROPIC_API_KEY
            or os.environ.get("ANTHROPIC_API_KEY"),
            "gemini_model": settings.GEMINI_MODEL,
            "gemini_api_key": settings.GEMINI_API_KEY
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY"),
        }
        base.update(overrides)
        return cls(**base)

    def copy_with(self, **overrides: Any) -> "AgentConfig":
        """Return a new config with some fields changed.

        Useful when one agent wants a different temperature to its siblings
        without mutating the shared instance.
        """
        current: Dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "healthcheck_timeout": self.healthcheck_timeout,
            "max_retries": self.max_retries,
            "fallback_enabled": self.fallback_enabled,
            "claude_model": self.claude_model,
            "claude_api_key": self.claude_api_key,
            "gemini_model": self.gemini_model,
            "gemini_api_key": self.gemini_api_key,
        }
        current.update(overrides)
        return AgentConfig(**current)

    # --- Helpers -----------------------------------------------------------

    @property
    def has_claude_credentials(self) -> bool:
        """True when a non-empty Anthropic key is configured."""
        return bool(self.claude_api_key and self.claude_api_key.strip())

    @property
    def has_gemini_credentials(self) -> bool:
        """True when a non-empty Google key is configured."""
        return bool(self.gemini_api_key and self.gemini_api_key.strip())

    @property
    def ollama_tags_url(self) -> str:
        """Endpoint used to check whether the Ollama daemon is reachable."""
        return f"{self.base_url}/api/tags"

    def describe(self) -> Dict[str, Any]:
        """A log-safe summary. Never includes the API key itself."""
        return {
            "provider": self.provider.value,
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "fallback_enabled": self.fallback_enabled,
            "claude_model": self.claude_model,
            "claude_credentials": self.has_claude_credentials,
            "gemini_model": self.gemini_model,
            "gemini_credentials": self.has_gemini_credentials,
        }


def default_agent_config() -> AgentConfig:
    """Convenience wrapper so callers do not have to import ``settings``."""
    return AgentConfig.from_settings()


# ---------------------------------------------------------------------------
# Submodule re-exports.
# These sit at the bottom because the modules below import ``AgentConfig``
# from this package, and it must exist by the time they are executed.
# ---------------------------------------------------------------------------

from agents.job_analyzer import JobAnalyzer, job_analyzer  # noqa: E402
from agents.match_calculator import MatchCalculator, match_calculator  # noqa: E402

__all__ = [
    "AgentConfig",
    "LLMProvider",
    "default_agent_config",
    "JobAnalyzer",
    "MatchCalculator",
    "job_analyzer",
    "match_calculator",
]

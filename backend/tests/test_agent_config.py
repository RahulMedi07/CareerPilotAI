"""Tests for AgentConfig and LLMProvider."""

import pytest

from agents import AgentConfig, LLMProvider, default_agent_config
from config import settings


class TestLLMProviderParse:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("ollama", LLMProvider.OLLAMA),
            ("OLLAMA", LLMProvider.OLLAMA),
            ("  local ", LLMProvider.OLLAMA),
            ("claude", LLMProvider.CLAUDE),
            ("anthropic", LLMProvider.CLAUDE),
            ("auto", LLMProvider.AUTO),
            ("fallback", LLMProvider.AUTO),
            ("", LLMProvider.AUTO),
            (None, LLMProvider.AUTO),
        ],
    )
    def test_accepts_known_aliases(self, raw, expected):
        assert LLMProvider.parse(raw) is expected

    def test_passes_through_enum_members(self):
        assert LLMProvider.parse(LLMProvider.CLAUDE) is LLMProvider.CLAUDE

    def test_rejects_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMProvider.parse("gpt4")


class TestAgentConfigValidation:
    def test_defaults_are_usable(self):
        config = AgentConfig()
        assert config.provider is LLMProvider.AUTO
        assert config.model == "mistral"
        assert config.max_tokens > 0

    def test_string_provider_is_coerced(self):
        assert AgentConfig(provider="claude").provider is LLMProvider.CLAUDE

    def test_trailing_slash_stripped_from_base_url(self):
        config = AgentConfig(base_url="http://localhost:11434/")
        assert config.base_url == "http://localhost:11434"
        assert config.ollama_tags_url == "http://localhost:11434/api/tags"

    def test_empty_model_rejected(self):
        with pytest.raises(ValueError, match="model must not be empty"):
            AgentConfig(model="   ")

    @pytest.mark.parametrize("value", [-0.1, 2.1])
    def test_temperature_out_of_range_rejected(self, value):
        with pytest.raises(ValueError, match="temperature"):
            AgentConfig(temperature=value)

    @pytest.mark.parametrize("value", [0.0, 1.0, 2.0])
    def test_temperature_boundaries_accepted(self, value):
        assert AgentConfig(temperature=value).temperature == value

    def test_zero_max_tokens_rejected(self):
        with pytest.raises(ValueError, match="max_tokens must be positive"):
            AgentConfig(max_tokens=0)

    def test_zero_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout must be positive"):
            AgentConfig(timeout=0)

    def test_zero_healthcheck_timeout_rejected(self):
        with pytest.raises(ValueError, match="healthcheck_timeout must be positive"):
            AgentConfig(healthcheck_timeout=0)

    def test_negative_retries_rejected(self):
        with pytest.raises(ValueError, match="max_retries must not be negative"):
            AgentConfig(max_retries=-1)

    def test_zero_retries_allowed(self):
        assert AgentConfig(max_retries=0).max_retries == 0


class TestAgentConfigFromSettings:
    def test_reads_values_from_settings(self):
        config = AgentConfig.from_settings()
        assert config.model == settings.LLM_MODEL
        assert config.base_url == settings.LLM_BASE_URL.rstrip("/")
        assert config.temperature == settings.LLM_TEMPERATURE
        assert config.max_tokens == settings.LLM_MAX_TOKENS

    def test_overrides_win(self):
        config = AgentConfig.from_settings(model="llama3", temperature=0.9)
        assert config.model == "llama3"
        assert config.temperature == 0.9

    def test_falls_back_to_environment_api_key(self, monkeypatch):
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        assert AgentConfig.from_settings().claude_api_key == "sk-test-key"

    def test_settings_key_beats_environment(self, monkeypatch):
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "from-settings")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        assert AgentConfig.from_settings().claude_api_key == "from-settings"

    def test_default_helper_matches_from_settings(self):
        assert default_agent_config().model == AgentConfig.from_settings().model


class TestAgentConfigHelpers:
    def test_copy_with_leaves_original_untouched(self):
        original = AgentConfig(temperature=0.2)
        copy = original.copy_with(temperature=0.8)
        assert copy.temperature == 0.8
        assert original.temperature == 0.2

    def test_copy_with_preserves_other_fields(self):
        original = AgentConfig(model="mistral", claude_api_key="sk-abc")
        copy = original.copy_with(temperature=0.5)
        assert copy.model == "mistral"
        assert copy.claude_api_key == "sk-abc"

    @pytest.mark.parametrize("key,expected", [(None, False), ("", False), ("   ", False), ("sk-x", True)])
    def test_has_claude_credentials(self, key, expected):
        assert AgentConfig(claude_api_key=key).has_claude_credentials is expected

    def test_describe_never_leaks_the_api_key(self):
        described = AgentConfig(claude_api_key="sk-super-secret").describe()
        assert "sk-super-secret" not in str(described)
        assert described["claude_credentials"] is True

    def test_describe_reports_provider_as_string(self):
        assert AgentConfig(provider="ollama").describe()["provider"] == "ollama"

    def test_repr_hides_the_api_key(self):
        assert "sk-super-secret" not in repr(AgentConfig(claude_api_key="sk-super-secret"))

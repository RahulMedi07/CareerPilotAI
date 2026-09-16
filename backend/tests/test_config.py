"""Tests for config.Settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from config import BASE_DIR, LLM_PROVIDERS, Settings, get_settings, settings


class TestSettings:
    def test_defaults_are_present(self):
        assert settings.APP_NAME == "CareerPilot AI"
        assert settings.API_PREFIX.startswith("/")
        assert settings.EMBEDDING_MODEL
        # Not `== "ollama"`. This is the live singleton, which reads .env, so
        # asserting the shipped default here really asserts "nobody has
        # configured this instance" - a property of the developer's machine
        # and not of the code. The real default is checked below against
        # `Settings(_env_file=None)`, where no ambient file can reach it.
        assert settings.LLM_PROVIDER in LLM_PROVIDERS

    def test_requested_defaults_match_the_spec(self):
        fresh = Settings(_env_file=None)
        assert fresh.DEBUG is True
        assert fresh.LLM_PROVIDER == "ollama"
        assert fresh.OLLAMA_BASE_URL == "http://localhost:11434"
        assert fresh.EMBEDDING_MODEL == "all-MiniLM-L6-v2"
        assert fresh.CHROMA_DB_PATH == BASE_DIR / "data" / "chroma"
        assert fresh.UPLOAD_DIR == BASE_DIR / "data" / "uploads"

    def test_max_upload_size_bytes_conversion(self):
        custom = Settings(MAX_UPLOAD_SIZE_MB=2)
        assert custom.max_upload_size_bytes == 2 * 1024 * 1024

    def test_ensure_directories_is_idempotent(self):
        settings.ensure_directories()
        settings.ensure_directories()
        assert settings.UPLOAD_DIR.is_dir()
        assert settings.CHROMA_DB_PATH.is_dir()
        assert settings.LOG_DIR.is_dir()

    def test_allowed_extensions_are_lowercase_with_dots(self):
        for extension in settings.ALLOWED_EXTENSIONS:
            assert extension.startswith(".")
            assert extension == extension.lower()

    def test_extensions_are_normalised_on_the_way_in(self):
        custom = Settings(ALLOWED_EXTENSIONS={"PDF", ".TxT"})
        assert custom.ALLOWED_EXTENSIONS == {".pdf", ".txt"}

    def test_get_settings_is_cached(self):
        assert get_settings() is get_settings()

    def test_environment_variables_override_defaults(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "mistral")
        assert Settings().LLM_MODEL == "mistral"


class TestPathHandling:
    def test_relative_paths_resolve_against_the_backend_folder(self, monkeypatch):
        """A relative path in .env must not depend on the shell's cwd."""
        monkeypatch.setenv("CHROMA_DB_PATH", "./data/chroma")
        monkeypatch.chdir(Path(BASE_DIR).parent)
        assert Settings().CHROMA_DB_PATH == BASE_DIR / "data" / "chroma"

    def test_absolute_paths_are_left_alone(self, tmp_path):
        custom = Settings(UPLOAD_DIR=tmp_path / "elsewhere")
        assert custom.UPLOAD_DIR == tmp_path / "elsewhere"

    def test_log_file_sits_inside_the_log_dir(self):
        assert settings.log_file.parent == settings.LOG_DIR
        assert settings.log_file.name == settings.LOG_FILE_NAME


class TestOllamaBaseUrl:
    def test_the_old_name_still_works_as_an_env_var(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "http://legacy:1234")
        assert Settings().OLLAMA_BASE_URL == "http://legacy:1234"

    def test_the_new_name_wins_when_both_are_set(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "http://legacy:1234")
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://current:11434")
        assert Settings().OLLAMA_BASE_URL == "http://current:11434"

    def test_the_old_attribute_still_reads(self):
        assert settings.LLM_BASE_URL == settings.OLLAMA_BASE_URL


class TestValidation:
    @pytest.mark.parametrize("provider", ["ollama", "claude", "auto"])
    def test_supported_providers_are_accepted(self, provider):
        assert Settings(LLM_PROVIDER=provider).LLM_PROVIDER == provider

    def test_provider_is_case_insensitive(self):
        assert Settings(LLM_PROVIDER="  Claude ").LLM_PROVIDER == "claude"

    def test_an_unknown_provider_fails_at_startup(self):
        """Better a loud crash on boot than a confusing failure mid-request."""
        with pytest.raises(ValidationError, match="LLM_PROVIDER"):
            Settings(LLM_PROVIDER="openai")

    def test_log_level_is_upper_cased(self):
        assert Settings(LOG_LEVEL="debug").LOG_LEVEL == "DEBUG"

    def test_an_unknown_log_level_fails(self):
        with pytest.raises(ValidationError, match="LOG_LEVEL"):
            Settings(LOG_LEVEL="verbose")


class TestEnvFile:
    def test_values_are_read_from_an_env_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "LLM_PROVIDER=claude\n"
            "OLLAMA_BASE_URL=http://from-file:9999\n"
            "LOG_LEVEL=warning\n"
            "MAX_UPLOAD_SIZE_MB=25\n",
            encoding="utf-8",
        )
        loaded = Settings(_env_file=env_file)
        assert loaded.LLM_PROVIDER == "claude"
        assert loaded.OLLAMA_BASE_URL == "http://from-file:9999"
        assert loaded.LOG_LEVEL == "WARNING"
        assert loaded.max_upload_size_bytes == 25 * 1024 * 1024

    def test_the_real_environment_beats_the_env_file(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("LLM_MODEL=from-file\n", encoding="utf-8")
        monkeypatch.setenv("LLM_MODEL", "from-environment")
        assert Settings(_env_file=env_file).LLM_MODEL == "from-environment"

    def test_unknown_keys_in_an_env_file_are_ignored(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SOMETHING_ELSE=1\n", encoding="utf-8")
        assert Settings(_env_file=env_file).APP_NAME == "CareerPilot AI"

    def test_the_example_file_documents_every_setting(self):
        """.env.example drifting out of date is the usual cause of setup pain."""
        example = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
        documented = {
            line.split("=", 1)[0].strip()
            for line in example.splitlines()
            if line.strip() and not line.startswith("#") and "=" in line
        }
        assert documented == set(Settings.model_fields)


class TestSummary:
    def test_summary_reports_the_key_without_revealing_it(self):
        custom = Settings(ANTHROPIC_API_KEY="sk-super-secret")
        report = custom.summary()
        assert report["claude_key_set"] is True
        assert "sk-super-secret" not in str(report)

    def test_summary_reports_a_missing_key(self):
        assert Settings(ANTHROPIC_API_KEY=None).summary()["claude_key_set"] is False

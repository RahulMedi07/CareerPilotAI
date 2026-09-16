"""Tests for the Ollama handler, the Claude fallback and the routing client."""

import sys
import types

import pytest

from agents import AgentConfig, LLMProvider
from agents import ollama_handler
from agents.ollama_handler import (
    PROMPT_TEMPLATES,
    ClaudeHandler,
    GeminiHandler,
    LLMClient,
    LLMError,
    LLMResponseError,
    LLMUnavailableError,
    OllamaHandler,
    get_prompt_template,
    parse_json_response,
    render_prompt,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHandler:
    """Minimal backend used to test routing without any network."""

    def __init__(self, name, available=True, reply="ok", error=None):
        self.name = name
        self.available = available
        self.reply = reply
        self.error = error
        self.calls = 0

    def is_available(self, refresh=False):
        return self.available

    def generate(self, prompt):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture
def config():
    return AgentConfig(max_retries=1, healthcheck_timeout=0.01)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------


class TestPromptTemplates:
    @pytest.mark.parametrize("name", ["job_analysis", "skill_extraction", "gap_analysis"])
    def test_registry_holds_system_and_user_parts(self, name):
        system, user = PROMPT_TEMPLATES[name]
        assert system.strip()
        assert "{" in user  # has at least one placeholder

    def test_get_prompt_template_returns_langchain_object(self):
        template = get_prompt_template("job_analysis")
        assert set(template.input_variables) == {"job_description"}

    def test_unknown_template_raises(self):
        with pytest.raises(KeyError, match="Unknown prompt template"):
            get_prompt_template("nope")

    def test_render_fills_placeholders(self):
        rendered = render_prompt("job_analysis", job_description="Build APIs")
        assert "Build APIs" in rendered
        assert "{job_description}" not in rendered

    def test_render_includes_the_system_instruction(self):
        assert "recruiter" in render_prompt("job_analysis", job_description="x")

    def test_render_reports_a_missing_value_clearly(self):
        with pytest.raises(KeyError, match="job_description"):
            render_prompt("job_analysis")

    def test_render_rejects_unknown_template(self):
        with pytest.raises(KeyError, match="Unknown prompt template"):
            render_prompt("nope", x=1)


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def test_plain_object(self):
        assert parse_json_response('{"a": 1}') == {"a": 1}

    def test_strips_markdown_fences(self):
        raw = '```json\n{"skills": ["python"]}\n```'
        assert parse_json_response(raw) == {"skills": ["python"]}

    def test_ignores_surrounding_prose(self):
        raw = 'Sure! Here is the result:\n{"score": 42}\nHope that helps.'
        assert parse_json_response(raw) == {"score": 42}

    def test_handles_nested_objects(self):
        raw = '{"outer": {"inner": [1, 2]}}'
        assert parse_json_response(raw)["outer"]["inner"] == [1, 2]

    @pytest.mark.parametrize("raw", ["", "   ", "\n"])
    def test_empty_response_rejected(self, raw):
        with pytest.raises(LLMResponseError, match="empty response"):
            parse_json_response(raw)

    def test_no_object_rejected(self):
        with pytest.raises(LLMResponseError, match="No JSON object"):
            parse_json_response("I cannot help with that.")

    def test_malformed_json_rejected(self):
        with pytest.raises(LLMResponseError, match="not valid JSON"):
            parse_json_response('{"a": }')

    def test_json_array_rejected(self):
        with pytest.raises(LLMResponseError, match="No JSON object"):
            parse_json_response("[1, 2, 3]")


# ---------------------------------------------------------------------------
# OllamaHandler
# ---------------------------------------------------------------------------


class TestOllamaHandler:
    def test_reports_available_on_http_200(self, config, monkeypatch):
        handler = OllamaHandler(config)
        monkeypatch.setattr(
            "requests.get", lambda *a, **k: FakeResponse(200)
        )
        assert handler.is_available() is True

    def test_reports_unavailable_on_error_status(self, config, monkeypatch):
        handler = OllamaHandler(config)
        monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(500))
        assert handler.is_available() is False

    def test_connection_error_is_swallowed(self, config, monkeypatch):
        handler = OllamaHandler(config)

        def boom(*args, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr("requests.get", boom)
        assert handler.is_available() is False

    def test_availability_is_cached(self, config, monkeypatch):
        handler = OllamaHandler(config)
        calls = []

        def counting(*args, **kwargs):
            calls.append(1)
            return FakeResponse(200)

        monkeypatch.setattr("requests.get", counting)
        handler.is_available()
        handler.is_available()
        assert len(calls) == 1

    def test_refresh_forces_a_new_probe(self, config, monkeypatch):
        handler = OllamaHandler(config)
        calls = []

        def counting(*args, **kwargs):
            calls.append(1)
            return FakeResponse(200)

        monkeypatch.setattr("requests.get", counting)
        handler.is_available()
        handler.is_available(refresh=True)
        assert len(calls) == 2

    def test_list_models_returns_names(self, config, monkeypatch):
        handler = OllamaHandler(config)
        payload = {"models": [{"name": "mistral"}, {"name": "llama3"}]}
        monkeypatch.setattr(
            "requests.get", lambda *a, **k: FakeResponse(200, payload)
        )
        assert handler.list_models() == ["mistral", "llama3"]

    def test_list_models_empty_when_offline(self, config, monkeypatch):
        handler = OllamaHandler(config)

        def boom(*args, **kwargs):
            raise OSError("down")

        monkeypatch.setattr("requests.get", boom)
        assert handler.list_models() == []

    def test_generate_raises_when_unavailable(self, config, monkeypatch):
        handler = OllamaHandler(config)
        monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(500))
        with pytest.raises(LLMUnavailableError, match="ollama pull"):
            handler.generate("hello")

    def test_generate_uses_the_langchain_runnable(self, config, monkeypatch):
        handler = OllamaHandler(config)
        monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(200))

        class FakeLLM:
            def invoke(self, prompt):
                return f"echo:{prompt}"

        handler._llm = FakeLLM()
        assert handler.generate("hi") == "echo:hi"

    def test_generate_failure_clears_the_cached_availability(self, config, monkeypatch):
        handler = OllamaHandler(config)
        monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(200))

        class BrokenLLM:
            def invoke(self, prompt):
                raise RuntimeError("daemon died")

        handler._llm = BrokenLLM()
        with pytest.raises(LLMError, match="Ollama generation failed"):
            handler.generate("hi")
        assert handler._available is None


# ---------------------------------------------------------------------------
# ClaudeHandler
# ---------------------------------------------------------------------------


class TestClaudeHandler:
    def test_unavailable_without_an_api_key(self):
        handler = ClaudeHandler(AgentConfig(claude_api_key=None))
        assert handler.is_available() is False

    def test_unavailable_when_sdk_missing(self, monkeypatch):
        handler = ClaudeHandler(AgentConfig(claude_api_key="sk-x"))
        # A ``None`` entry in sys.modules makes ``import anthropic`` raise
        # ImportError, which is exactly the "package not installed" case.
        monkeypatch.setitem(sys.modules, "anthropic", None)
        assert handler.is_available() is False

    def test_available_with_key_and_sdk(self, monkeypatch):
        handler = ClaudeHandler(AgentConfig(claude_api_key="sk-x"))
        monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
        assert handler.is_available() is True

    def test_generate_uses_the_messages_api(self, monkeypatch):
        handler = ClaudeHandler(AgentConfig(claude_api_key="sk-x"))
        monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))

        class Block:
            type = "text"
            text = '{"ok": true}'

        class FakeMessages:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return types.SimpleNamespace(content=[Block()])

        handler._llm = types.SimpleNamespace(messages=FakeMessages())
        assert handler.generate("hi") == '{"ok": true}'

    def test_generate_wraps_sdk_errors(self, monkeypatch):
        handler = ClaudeHandler(AgentConfig(claude_api_key="sk-x"))
        monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))

        class BrokenMessages:
            def create(self, **kwargs):
                raise RuntimeError("rate limited")

        handler._llm = types.SimpleNamespace(messages=BrokenMessages())
        with pytest.raises(LLMError, match="Claude generation failed"):
            handler.generate("hi")

    def test_generate_raises_when_not_configured(self):
        handler = ClaudeHandler(AgentConfig(claude_api_key=None))
        with pytest.raises(LLMUnavailableError, match="ANTHROPIC_API_KEY"):
            handler.generate("hello")


# ---------------------------------------------------------------------------
# GeminiHandler
# ---------------------------------------------------------------------------


def _gemini_response(status=200, body=None, text=""):
    """A stand-in for ``requests.Response`` carrying only what is read."""
    return types.SimpleNamespace(
        status_code=status,
        json=lambda: (body if body is not None else {}),
        text=text,
    )


def _ok(answer="{\"ok\": true}", finish="STOP"):
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": answer}], "role": "model"},
                "finishReason": finish,
            }
        ]
    }


class TestGeminiHandler:
    def _handler(self, monkeypatch, response, key="AIzaTest"):
        handler = GeminiHandler(AgentConfig(gemini_api_key=key))
        sent = {}

        def fake_post(url, **kwargs):
            sent["url"] = url
            sent.update(kwargs)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(ollama_handler.requests, "post", fake_post)
        return handler, sent

    def test_unavailable_without_a_key(self):
        assert GeminiHandler(AgentConfig(gemini_api_key=None)).is_available() is False

    def test_available_with_a_key_and_no_sdk_installed(self):
        # The whole point of the REST handler: nothing to import, so a key is
        # the only requirement.
        assert GeminiHandler(AgentConfig(gemini_api_key="AIzaTest")).is_available() is True

    def test_generate_returns_the_candidate_text(self, monkeypatch):
        handler, _ = self._handler(monkeypatch, _gemini_response(body=_ok()))
        assert handler.generate("hi") == '{"ok": true}'

    def test_the_key_goes_in_a_header_not_the_url(self, monkeypatch):
        # A key in `?key=` leaks into proxy logs and error reports.
        handler, sent = self._handler(monkeypatch, _gemini_response(body=_ok()))
        handler.generate("hi")
        assert sent["headers"]["x-goog-api-key"] == "AIzaTest"
        assert "AIzaTest" not in sent["url"]

    def test_the_configured_model_is_used(self, monkeypatch):
        handler = GeminiHandler(
            AgentConfig(gemini_api_key="AIzaTest", gemini_model="gemini-1.5-pro")
        )
        monkeypatch.setattr(
            ollama_handler.requests,
            "post",
            lambda url, **kw: _gemini_response(body=_ok()) if "gemini-1.5-pro" in url
            else _gemini_response(status=404),
        )
        assert handler.generate("hi") == '{"ok": true}'

    def test_temperature_and_token_cap_are_sent(self, monkeypatch):
        handler, sent = self._handler(monkeypatch, _gemini_response(body=_ok()))
        handler.generate("hi")
        config = sent["json"]["generationConfig"]
        assert config["temperature"] == handler.config.temperature
        assert config["maxOutputTokens"] == handler.config.max_tokens

    def test_multiple_parts_are_joined_not_truncated(self, monkeypatch):
        body = {
            "candidates": [
                {"content": {"parts": [{"text": "one "}, {"text": "two"}]}}
            ]
        }
        handler, _ = self._handler(monkeypatch, _gemini_response(body=body))
        assert handler.generate("hi") == "one two"

    def test_a_rejected_key_is_unavailable_not_retryable(self, monkeypatch):
        # 403 will still be 403 on the third attempt. Raising LLMError would
        # make the router burn two more calls before giving up.
        handler, _ = self._handler(monkeypatch, _gemini_response(status=403, text="denied"))
        with pytest.raises(LLMUnavailableError, match="rejected the API key"):
            handler.generate("hi")

    def test_a_rate_limit_is_retryable(self, monkeypatch):
        handler, _ = self._handler(monkeypatch, _gemini_response(status=429))
        with pytest.raises(LLMError, match="rate limit"):
            handler.generate("hi")

    def test_a_server_error_reports_the_status(self, monkeypatch):
        handler, _ = self._handler(monkeypatch, _gemini_response(status=500, text="boom"))
        with pytest.raises(LLMError, match="HTTP 500"):
            handler.generate("hi")

    def test_a_network_failure_is_wrapped(self, monkeypatch):
        handler, _ = self._handler(
            monkeypatch, ollama_handler.requests.RequestException("no route")
        )
        with pytest.raises(LLMError, match="Gemini request failed"):
            handler.generate("hi")

    def test_a_safety_block_is_an_error_not_an_empty_string(self, monkeypatch):
        # Returning "" here would hand an agent an empty prompt response to
        # parse, and it would report a confident empty result.
        body = {"promptFeedback": {"blockReason": "SAFETY"}}
        handler, _ = self._handler(monkeypatch, _gemini_response(body=body))
        with pytest.raises(LLMError, match="SAFETY"):
            handler.generate("hi")

    def test_a_truncated_answer_names_the_finish_reason(self, monkeypatch):
        body = {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}
        handler, _ = self._handler(monkeypatch, _gemini_response(body=body))
        with pytest.raises(LLMError, match="MAX_TOKENS"):
            handler.generate("hi")

    def test_a_non_json_body_is_wrapped(self, monkeypatch):
        response = types.SimpleNamespace(
            status_code=200,
            json=lambda: (_ for _ in ()).throw(ValueError("not json")),
            text="<html>",
        )
        handler, _ = self._handler(monkeypatch, response)
        with pytest.raises(LLMError, match="non-JSON"):
            handler.generate("hi")

    def test_generate_raises_when_not_configured(self):
        handler = GeminiHandler(AgentConfig(gemini_api_key=None))
        with pytest.raises(LLMUnavailableError, match="GEMINI_API_KEY"):
            handler.generate("hello")


class TestTheSuiteNeverReachesAHostedModel:
    """The test run must not depend on, or spend money at, a real API.

    A key in ``.env`` used to leak into the suite through agents built at
    import time: thirteen pipeline tests called Gemini for real, 234 requests
    in a single run, and the suite went from 22 seconds to nearly 8 minutes
    once Google began rate-limiting. ``conftest`` blanks those credentials;
    these tests fail if that stops working.
    """

    def test_no_agent_anywhere_still_holds_a_key(self):
        from agents import complete_workflow  # noqa: F401
        from agents.ollama_handler import llm_client

        # The composite agent is imported because it was the one that leaked:
        # its sub-agents hold configs several references deep.
        assert llm_client.config.has_gemini_credentials is False
        assert llm_client.config.has_claude_credentials is False

    def test_the_real_key_is_refused_even_if_it_reaches_a_config(self):
        from tests.conftest import _REAL_KEYS

        if not _REAL_KEYS:
            pytest.skip("no real key configured on this machine")
        config = AgentConfig(gemini_api_key=sorted(_REAL_KEYS)[0])
        assert config.has_gemini_credentials is False

    def test_a_fake_key_still_works_so_handlers_stay_testable(self):
        assert AgentConfig(gemini_api_key="AIzaTest").has_gemini_credentials is True

    def test_the_shared_client_reports_no_hosted_backend(self):
        from agents.ollama_handler import llm_client

        assert llm_client.gemini.is_available() is False

    def test_a_freshly_built_agent_gets_no_key_either(self):
        # Covers the other direction: settings and the environment are clean,
        # so anything constructed during a test starts without credentials.
        config = AgentConfig.from_settings()
        assert config.gemini_api_key is None
        assert config.claude_api_key is None


# ---------------------------------------------------------------------------
# LLMClient routing
# ---------------------------------------------------------------------------


class TestLLMClientRouting:
    def test_auto_prefers_ollama(self, config):
        ollama = FakeHandler("ollama", reply="from-ollama")
        claude = FakeHandler("claude", reply="from-claude")
        client = LLMClient(config.copy_with(provider="auto"), ollama, claude)
        assert client.generate("hi") == "from-ollama"
        assert client.last_backend == "ollama"

    def test_auto_falls_back_to_claude(self, config):
        ollama = FakeHandler("ollama", available=False)
        claude = FakeHandler("claude", reply="from-claude")
        client = LLMClient(config.copy_with(provider="auto"), ollama, claude)
        assert client.generate("hi") == "from-claude"
        assert client.last_backend == "claude"

    def test_claude_provider_never_touches_ollama(self, config):
        ollama = FakeHandler("ollama", reply="from-ollama")
        claude = FakeHandler("claude", reply="from-claude")
        client = LLMClient(config.copy_with(provider="claude"), ollama, claude)
        client.generate("hi")
        assert ollama.calls == 0

    def test_ollama_provider_skips_fallback_when_disabled(self, config):
        ollama = FakeHandler("ollama", available=False)
        claude = FakeHandler("claude", reply="from-claude")
        client = LLMClient(
            config.copy_with(provider="ollama", fallback_enabled=False),
            ollama,
            claude,
        )
        with pytest.raises(LLMUnavailableError):
            client.generate("hi")
        assert claude.calls == 0

    def test_ollama_provider_uses_fallback_when_enabled(self, config):
        ollama = FakeHandler("ollama", available=False)
        claude = FakeHandler("claude", reply="from-claude")
        client = LLMClient(
            config.copy_with(provider="ollama", fallback_enabled=True),
            ollama,
            claude,
        )
        assert client.generate("hi") == "from-claude"

    def test_raises_when_every_backend_is_down(self, config):
        client = LLMClient(
            config,
            FakeHandler("ollama", available=False),
            FakeHandler("claude", available=False),
        )
        with pytest.raises(LLMUnavailableError, match="No LLM backend"):
            client.generate("hi")

    def test_retries_a_transient_failure(self, config, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda *_: None)
        ollama = FakeHandler("ollama", error=LLMError("boom"))
        claude = FakeHandler("claude", reply="from-claude")
        client = LLMClient(config, ollama, claude)  # max_retries=1 -> 2 attempts
        assert client.generate("hi") == "from-claude"
        assert ollama.calls == 2

    def test_unavailable_error_is_not_retried(self, config):
        ollama = FakeHandler("ollama", error=LLMUnavailableError("gone"))
        claude = FakeHandler("claude", reply="from-claude")
        client = LLMClient(config, ollama, claude)
        client.generate("hi")
        assert ollama.calls == 1

    def test_empty_prompt_rejected(self, config):
        client = LLMClient(config, FakeHandler("ollama"), FakeHandler("claude"))
        with pytest.raises(ValueError, match="prompt must not be empty"):
            client.generate("   ")

    def test_available_backend_reports_first_usable(self, config):
        client = LLMClient(
            config,
            FakeHandler("ollama", available=False),
            FakeHandler("claude", available=True),
        )
        assert client.available_backend() == "claude"
        assert client.is_available() is True

    def test_available_backend_is_none_when_all_down(self, config):
        client = LLMClient(
            config,
            FakeHandler("ollama", available=False),
            FakeHandler("claude", available=False),
        )
        assert client.available_backend() is None
        assert client.is_available() is False

    def test_generate_json_parses_the_reply(self, config):
        ollama = FakeHandler("ollama", reply='```json\n{"skills": ["go"]}\n```')
        client = LLMClient(config, ollama, FakeHandler("claude", available=False))
        assert client.generate_json("hi") == {"skills": ["go"]}

    def test_describe_includes_the_active_backend(self, config):
        client = LLMClient(
            config,
            FakeHandler("ollama", available=True),
            FakeHandler("claude", available=False),
        )
        described = client.describe()
        assert described["active_backend"] == "ollama"
        assert described["provider"] == LLMProvider.AUTO.value

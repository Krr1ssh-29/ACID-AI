"""Tests for AI provider integrations using mocks in agent.providers."""
import json
import pytest
import requests
from unittest.mock import MagicMock
from agent.providers import (
    analyse_with_claude,
    analyse_with_gemini,
    analyse_with_ai,
    get_provider,
    AnthropicProvider,
    GeminiProvider,
    sanitize_error_message,
)
from agent.models import AgentConfig, AnalysisResult


def test_analyse_with_claude_missing_api_key(monkeypatch):
    """Verify RuntimeError is raised when ANTHROPIC_API_KEY is not set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY environment variable not set"):
        analyse_with_claude("logs", {"detected": ["test"]})


def test_analyse_with_claude_success(monkeypatch):
    """Verify Claude diagnostic call with mocked Anthropic client."""
    mock_response = MagicMock()
    mock_content = MagicMock()
    mock_content.text = json.dumps({
        "severity": "high",
        "failure_types": ["test"],
        "root_cause": "Test failed in test_app.py",
        "fixes": [{"type": "test", "title": "Fix test", "description": "Update assertions"}],
        "prevention": "Run tests locally",
        "confidence": "high",
        "log_evidence": "FAILED tests/test_app.py::test_index",
    })
    mock_response.content = [mock_content]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    mock_anthropic_class = MagicMock(return_value=mock_client)
    monkeypatch.setattr("anthropic.Anthropic", mock_anthropic_class)

    result = analyse_with_claude(
        logs="FAILED test_app.py",
        failure_context={"detected": ["test"]},
        api_key="fake_claude_key",
        model="claude-sonnet-4-6",
    )
    assert result["severity"] == "high"
    assert "Test failed" in result["root_cause"]
    assert len(result["fixes"]) == 1
    assert result["fixes"][0]["type"] == "test"
    mock_client.messages.create.assert_called_once()


def test_analyse_with_gemini_missing_api_key(monkeypatch):
    """Verify RuntimeError is raised when GEMINI_API_KEY is not set."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY environment variable not set"):
        analyse_with_gemini("logs", {"detected": ["test"]})


def test_analyse_with_gemini_success(monkeypatch):
    """Verify Gemini diagnostic call with mocked requests.post."""
    mock_post_response = MagicMock()
    mock_post_response.status_code = 200
    mock_post_response.json.return_value = {
        "candidates": [{
            "finishReason": "STOP",
            "content": {
                "parts": [{
                    "text": json.dumps({
                        "severity": "medium",
                        "failure_types": ["lint"],
                        "root_cause": "Flake8 line too long",
                        "fixes": [
                            {"type": "lint", "title": "Shorten line", "description": "Wrap line under 120 chars"}
                        ],
                        "prevention": "Configure editor line ruler",
                        "confidence": "high",
                    })
                }]
            }
        }]
    }

    mock_post = MagicMock(return_value=mock_post_response)
    monkeypatch.setattr("requests.post", mock_post)

    result = analyse_with_gemini(
        logs="line too long",
        failure_context={"detected": ["lint"]},
        api_key="fake_gemini_key",
        model="gemini-3.8-flash",
    )
    assert result["severity"] == "medium"
    assert "Flake8 line too long" in result["root_cause"]
    mock_post.assert_called_once()

    # Crucial security verification: ensure key is passed via header, NOT query parameter
    call_args, call_kwargs = mock_post.call_args
    assert "key=" not in call_args[0], "API key leaked in URL query parameter!"
    assert call_kwargs["headers"].get("x-goog-api-key") == "fake_gemini_key"


def test_gemini_header_authentication_eliminates_url_key(monkeypatch):
    """Explicitly verify that Gemini requests never append the API key to the URL."""
    captured_urls = []
    captured_headers = []

    def mock_post(url, headers=None, **kwargs):
        captured_urls.append(url)
        captured_headers.append(headers or {})
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": '{"severity": "low", "root_cause": "ok", "fixes": []}'}]},
            }]
        }
        return resp

    monkeypatch.setattr("requests.post", mock_post)
    provider = GeminiProvider(api_key="secret_token_12345", model="gemini-3.8-flash")
    provider.diagnose("test logs", {"detected": []})

    assert len(captured_urls) == 1
    assert "secret_token_12345" not in captured_urls[0]
    assert "?key=" not in captured_urls[0]
    assert captured_headers[0]["x-goog-api-key"] == "secret_token_12345"


def test_configurable_model_selection(monkeypatch):
    """Verify custom model identifiers are propagated to providers."""
    mock_post_response = MagicMock()
    mock_post_response.status_code = 200
    mock_post_response.json.return_value = {
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": '{"severity": "high", "root_cause": "argon diagnosis", "fixes": []}'}]},
        }]
    }
    mock_post = MagicMock(return_value=mock_post_response)
    monkeypatch.setattr("requests.post", mock_post)

    cfg = AgentConfig(
        ai_provider="gemini",
        gemini_api_key="fake_key",
        gemini_model="gemini-4-argon",
    )
    result = analyse_with_ai("logs", {"detected": ["docker"]}, config=cfg)
    assert result["root_cause"] == "argon diagnosis"
    assert "gemini-4-argon" in mock_post.call_args[0][0]


def test_schema_validation_success_with_all_fields():
    """Verify that full schema validation handles all fields on AnalysisResult."""
    data = {
        "severity": "critical",
        "failure_types": ["install", "docker"],
        "root_cause": "Pip dependency conflict during container build",
        "fixes": [
            {
                "type": "install",
                "title": "Pin package version",
                "description": "Specify exact compatible version in requirements.txt",
                "code": "pip install requests==2.32.3",
            }
        ],
        "prevention": "Use a lockfile to prevent upstream drift.",
        "confidence": "high",
        "log_evidence": "ERROR: ResolutionImpossible: conflicting dependencies",
    }
    model = AnalysisResult.model_validate(data)
    assert model.severity == "critical"
    assert model.failure_types == ["install", "docker"]
    assert model.log_evidence == "ERROR: ResolutionImpossible: conflicting dependencies"
    # Verify dictionary access methods
    assert model["severity"] == "critical"
    assert model.get("confidence") == "high"
    assert model["fixes"][0]["type"] == "install"


def test_schema_validation_failure_on_invalid_fields():
    """Verify that responses with invalid severity or fix types are rejected by Pydantic."""
    # Invalid severity
    invalid_severity = {
        "severity": "catastrophic",  # Invalid enum value
        "root_cause": "Something broke",
        "fixes": [],
    }
    with pytest.raises(Exception):
        AnalysisResult.model_validate(invalid_severity)

    # Missing root_cause
    missing_root_cause = {
        "severity": "high",
        "fixes": [],
    }
    with pytest.raises(Exception):
        AnalysisResult.model_validate(missing_root_cause)

    # Invalid fix category
    invalid_fix_type = {
        "severity": "high",
        "root_cause": "Broken code",
        "fixes": [{"type": "magic_wand", "title": "Fix it", "description": "Waving wand"}],
    }
    with pytest.raises(Exception):
        AnalysisResult.model_validate(invalid_fix_type)


def test_provider_bounded_retries_on_rate_limit_429(monkeypatch):
    """Verify provider retries on rate limit (HTTP 429) and succeeds on subsequent attempt."""
    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        if call_count == 1:
            resp.status_code = 429
            return resp
        else:
            resp.status_code = 200
            resp.json.return_value = {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"severity": "low", "root_cause": "Recovered", "fixes": []}'}]},
                }]
            }
            return resp

    monkeypatch.setattr("requests.post", mock_post)
    provider = GeminiProvider(api_key="test_key", model="gemini-3.8-flash", max_retries=2, backoff_factor=0.0)
    result = provider.diagnose("test logs", {"detected": []})

    assert call_count == 2
    assert result.root_cause == "Recovered"


def test_provider_retry_limit_exhausted(monkeypatch):
    """Verify RuntimeError is raised when all retries are exhausted."""
    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 503
        return resp

    monkeypatch.setattr("requests.post", mock_post)
    provider = GeminiProvider(api_key="test_key", model="gemini-3.8-flash", max_retries=2, backoff_factor=0.0)

    with pytest.raises(RuntimeError, match="AI diagnosis failed after 3 attempts"):
        provider.diagnose("test logs", {"detected": []})

    assert call_count == 3


def test_permanent_authentication_failure_not_retried(monkeypatch):
    """Verify HTTP 401/403 fails immediately without consuming retries."""
    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 401
        return resp

    monkeypatch.setattr("requests.post", mock_post)
    provider = GeminiProvider(api_key="bad_key", model="gemini-3.8-flash", max_retries=3, backoff_factor=0.0)

    with pytest.raises(RuntimeError, match="authentication failed"):
        provider.diagnose("test logs", {"detected": []})

    # Assert exactly 1 call was made (no retries for auth errors)
    assert call_count == 1


def test_timeout_handling_and_retry(monkeypatch):
    """Verify request timeouts are retried with bounded backoff."""
    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise requests.Timeout("Connection timed out")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "candidates": [{
                "finishReason": "STOP",
                "content": {
                    "parts": [{"text": '{"severity": "high", "root_cause": "Timeout recovered", "fixes": []}'}]
                },
            }]
        }
        return resp

    monkeypatch.setattr("requests.post", mock_post)
    provider = GeminiProvider(api_key="test_key", model="gemini-3.8-flash", max_retries=2, backoff_factor=0.0)
    result = provider.diagnose("test logs", {"detected": []})

    assert call_count == 2
    assert result.root_cause == "Timeout recovered"


def test_malformed_json_response_retried(monkeypatch):
    """Verify malformed JSON from model is retried and validated."""
    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 200
        if call_count == 1:
            resp.json.return_value = {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": "This is conversational text without JSON"}]},
                }]
            }
        else:
            resp.json.return_value = {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"severity": "medium", "root_cause": "JSON fixed", "fixes": []}'}]},
                }]
            }
        return resp

    monkeypatch.setattr("requests.post", mock_post)
    provider = GeminiProvider(api_key="test_key", model="gemini-3.8-flash", max_retries=2, backoff_factor=0.0)
    result = provider.diagnose("test logs", {"detected": []})

    assert call_count == 2
    assert result.root_cause == "JSON fixed"


def test_api_key_redaction_in_exceptions():
    """Verify sensitive keys are scrubbed from exception messages."""
    secret = "".join(["sk-ant-", "live-super-secret-key-12345"])
    raw_error = f"Failed to connect using key {secret}: 401 Unauthorized"
    sanitized = sanitize_error_message(raw_error, [secret])
    assert secret not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized


def test_get_provider_factory(monkeypatch):
    """Verify get_provider instantiates the correct provider subclass."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude_key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini_key")

    cfg_claude = AgentConfig(ai_provider="claude", anthropic_api_key="claude_key")
    p_claude = get_provider(cfg_claude)
    assert isinstance(p_claude, AnthropicProvider)
    assert p_claude.model == "claude-sonnet-4-6"

    cfg_gemini = AgentConfig(ai_provider="gemini", gemini_api_key="gemini_key")
    p_gemini = get_provider(cfg_gemini)
    assert isinstance(p_gemini, GeminiProvider)
    assert p_gemini.model == "gemini-3.8-flash"


def test_analyse_with_ai_routing_claude(monkeypatch):
    """Verify analyse_with_ai routes to Claude when provider is claude."""
    mock_claude = MagicMock(return_value={"severity": "high", "root_cause": "Claude diagnosis"})
    monkeypatch.setattr("agent.providers.analyse_with_claude", mock_claude)

    cfg = AgentConfig(ai_provider="claude", anthropic_api_key="fake_key")
    result = analyse_with_ai("some logs", {"detected": ["test"]}, config=cfg)
    assert result["root_cause"] == "Claude diagnosis"
    mock_claude.assert_called_once()


def test_analyse_with_ai_routing_gemini(monkeypatch):
    """Verify analyse_with_ai routes to Gemini when provider is gemini."""
    mock_gemini = MagicMock(return_value={"severity": "low", "root_cause": "Gemini diagnosis"})
    monkeypatch.setattr("agent.providers.analyse_with_gemini", mock_gemini)

    cfg = AgentConfig(ai_provider="gemini", gemini_api_key="fake_key")
    result = analyse_with_ai("some logs", {"detected": ["lint"]}, config=cfg)
    assert result["root_cause"] == "Gemini diagnosis"
    mock_gemini.assert_called_once()


def test_analyse_with_ai_unknown_provider():
    """Verify ValueError is raised for unsupported AI_PROVIDER."""
    cfg = AgentConfig.model_construct(ai_provider="unsupported_provider")
    with pytest.raises(ValueError, match="Unknown AI_PROVIDER: 'unsupported_provider'"):
        analyse_with_ai("logs", {"detected": []}, config=cfg)


def test_anthropic_auth_failure_raises_runtime_error(monkeypatch):
    """Verify Anthropic authentication error fails fast without retry."""
    from anthropic import AuthenticationError

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = AuthenticationError(
        message="Invalid key", response=MagicMock(status_code=401), body={}
    )
    monkeypatch.setattr("anthropic.Anthropic", MagicMock(return_value=mock_client))

    provider = AnthropicProvider(api_key="bad_key", model="claude-sonnet-4-6", max_retries=2, backoff_factor=0.0)
    with pytest.raises(RuntimeError, match="Anthropic authentication failed"):
        provider.diagnose("logs", {"detected": []})

    assert mock_client.messages.create.call_count == 1


def test_anthropic_model_not_found_raises_runtime_error(monkeypatch):
    """Verify Anthropic model not found error fails fast without retry."""
    from anthropic import NotFoundError

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = NotFoundError(
        message="Model not found", response=MagicMock(status_code=404), body={}
    )
    monkeypatch.setattr("anthropic.Anthropic", MagicMock(return_value=mock_client))

    provider = AnthropicProvider(api_key="key", model="invalid-model", max_retries=2, backoff_factor=0.0)
    with pytest.raises(RuntimeError, match="model 'invalid-model' not found"):
        provider.diagnose("logs", {"detected": []})

    assert mock_client.messages.create.call_count == 1


def test_anthropic_rate_limit_retried_and_succeeds(monkeypatch):
    """Verify Anthropic rate limit error is retried and succeeds on next attempt."""
    from anthropic import RateLimitError as AnthropicRateLimitError

    call_count = 0
    mock_response = MagicMock()
    mock_content = MagicMock()
    mock_content.text = '{"severity": "low", "root_cause": "Rate limit recovered", "fixes": []}'
    mock_response.content = [mock_content]

    def mock_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise AnthropicRateLimitError(
                message="Rate limited", response=MagicMock(status_code=429), body={}
            )
        return mock_response

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = mock_create
    monkeypatch.setattr("anthropic.Anthropic", MagicMock(return_value=mock_client))

    provider = AnthropicProvider(api_key="key", model="claude-sonnet-4-6", max_retries=2, backoff_factor=0.0)
    result = provider.diagnose("logs", {"detected": []})

    assert call_count == 2
    assert result.root_cause == "Rate limit recovered"


def test_gemini_model_not_found_404(monkeypatch):
    """Verify Gemini HTTP 404 model not found fails fast."""
    mock_post_response = MagicMock()
    mock_post_response.status_code = 404
    monkeypatch.setattr("requests.post", MagicMock(return_value=mock_post_response))

    provider = GeminiProvider(api_key="key", model="non-existent-model", max_retries=2, backoff_factor=0.0)
    with pytest.raises(RuntimeError, match="model 'non-existent-model' not found"):
        provider.diagnose("logs", {"detected": []})


def test_gemini_client_error_400(monkeypatch):
    """Verify Gemini HTTP 400 client error raises RuntimeError."""
    mock_post_response = MagicMock()
    mock_post_response.status_code = 400
    mock_post_response.text = "Bad Request: Invalid argument"
    monkeypatch.setattr("requests.post", MagicMock(return_value=mock_post_response))

    provider = GeminiProvider(api_key="key", model="gemini-3.8-flash", max_retries=2, backoff_factor=0.0)
    with pytest.raises(RuntimeError, match="Google Gemini API error"):
        provider.diagnose("logs", {"detected": []})


def test_gemini_no_candidates_blocked(monkeypatch):
    """Verify Gemini response with no candidates (safety blocked) raises ValueError."""
    mock_post_response = MagicMock()
    mock_post_response.status_code = 200
    mock_post_response.json.return_value = {
        "candidates": [],
        "promptFeedback": {"blockReason": "SAFETY"},
    }
    monkeypatch.setattr("requests.post", MagicMock(return_value=mock_post_response))

    provider = GeminiProvider(api_key="key", model="gemini-3.8-flash", max_retries=0, backoff_factor=0.0)
    with pytest.raises(RuntimeError, match="returned no candidates"):
        provider.diagnose("logs", {"detected": []})


def test_gemini_unexpected_finish_reason(monkeypatch):
    """Verify Gemini response with non-standard finishReason raises ValueError."""
    mock_post_response = MagicMock()
    mock_post_response.status_code = 200
    mock_post_response.json.return_value = {
        "candidates": [{"finishReason": "RECITATION", "content": {"parts": [{"text": "text"}]}}],
    }
    monkeypatch.setattr("requests.post", MagicMock(return_value=mock_post_response))

    provider = GeminiProvider(api_key="key", model="gemini-3.8-flash", max_retries=0, backoff_factor=0.0)
    with pytest.raises(RuntimeError, match="terminated unexpectedly"):
        provider.diagnose("logs", {"detected": []})

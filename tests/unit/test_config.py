"""Tests for configuration loading and validation in agent.config."""
from agent.config import load_config, validate_credentials
from agent.models import AgentConfig


def test_load_config_defaults():
    """Verify load_config populates defaults when environment is empty."""
    config = load_config({})
    assert config.ai_provider == "claude"
    assert config.anthropic_model == "claude-sonnet-4-6"
    assert config.gemini_model == "gemini-3.8-flash"
    assert config.pr_number is None
    assert config.commit_sha == "unknown"
    assert config.run_id == "unknown"
    assert config.log_file == "combined-logs.txt"
    assert config.ai_timeout_seconds == 60


def test_load_config_handles_empty_ai_provider():
    """Verify that empty string AI_PROVIDER does not crash and defaults to claude.

    This directly tests against the flaw identified in the baseline prototype where
    AI_PROVIDER="" caused an unhandled crash.
    """
    env = {"AI_PROVIDER": ""}
    config = load_config(env)
    assert config.ai_provider == "claude"

    env_whitespace = {"AI_PROVIDER": "   "}
    config_ws = load_config(env_whitespace)
    assert config_ws.ai_provider == "claude"


def test_load_config_handles_pr_number_variants():
    """Verify PR_NUMBER normalization for empty, None, and valid values."""
    assert load_config({"PR_NUMBER": ""}).pr_number is None
    assert load_config({"PR_NUMBER": "None"}).pr_number is None
    assert load_config({"PR_NUMBER": "null"}).pr_number is None
    assert load_config({"PR_NUMBER": "42"}).pr_number == "42"


def test_load_config_custom_values():
    """Verify loading custom configuration values from environment."""
    env = {
        "AI_PROVIDER": "gemini",
        "GEMINI_API_KEY": "fake_gemini_key",
        "GEMINI_MODEL": "gemini-4-argon",
        "REPO_NAME": "owner/repo",
        "PR_NUMBER": "99",
        "COMMIT_SHA": "abcdef1234567890",
        "RUN_ID": "123456",
        "LOG_FILE": "custom-logs.txt",
        "AI_TIMEOUT_SECONDS": "45",
    }
    config = load_config(env)
    assert config.ai_provider == "gemini"
    assert config.gemini_api_key == "fake_gemini_key"
    assert config.gemini_model == "gemini-4-argon"
    assert config.repo_name == "owner/repo"
    assert config.pr_number == "99"
    assert config.commit_sha == "abcdef1234567890"
    assert config.run_id == "123456"
    assert config.log_file == "custom-logs.txt"
    assert config.ai_timeout_seconds == 45


def test_validate_credentials_claude():
    """Verify credential validation for Anthropic Claude provider."""
    # Missing key
    cfg_missing = AgentConfig(ai_provider="claude", anthropic_api_key=None)
    err = validate_credentials(cfg_missing)
    assert err is not None
    assert "AI_PROVIDER=claude but ANTHROPIC_API_KEY not set" in err

    # Present key
    cfg_valid = AgentConfig(ai_provider="claude", anthropic_api_key="valid-claude-test-key")
    assert validate_credentials(cfg_valid) is None


def test_validate_credentials_gemini():
    """Verify credential validation for Google Gemini provider."""
    # Missing key
    cfg_missing = AgentConfig(ai_provider="gemini", gemini_api_key=None)
    err = validate_credentials(cfg_missing)
    assert err is not None
    assert "AI_PROVIDER=gemini but GEMINI_API_KEY not set" in err

    # Present key
    cfg_valid = AgentConfig(ai_provider="gemini", gemini_api_key="valid-gemini-test-key")
    assert validate_credentials(cfg_valid) is None

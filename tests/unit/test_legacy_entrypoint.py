"""Tests for backwards-compatible interfaces in agent.self_healing_agent."""
from unittest.mock import MagicMock
import agent.self_healing_agent as legacy


def test_legacy_module_exports():
    """Verify legacy module-level variables and functions are accessible."""
    assert hasattr(legacy, "ANTHROPIC_API_KEY")
    assert hasattr(legacy, "GEMINI_API_KEY")
    assert hasattr(legacy, "AI_PROVIDER")
    assert hasattr(legacy, "GITHUB_TOKEN")
    assert hasattr(legacy, "REPO_NAME")
    assert hasattr(legacy, "PR_NUMBER")
    assert hasattr(legacy, "COMMIT_SHA")
    assert hasattr(legacy, "RUN_ID")
    assert hasattr(legacy, "LOG_FILE")
    assert hasattr(legacy, "SYSTEM_PROMPT")


def test_legacy_read_logs(monkeypatch):
    """Verify legacy read_logs wrapper calls collector."""
    monkeypatch.setattr("agent.self_healing_agent._read_logs", lambda path: "mocked log text")
    assert legacy.read_logs() == "mocked log text"


def test_legacy_classify_failures():
    """Verify legacy classify_failures wrapper functions correctly."""
    result = legacy.classify_failures("pip install error: package not found")
    assert "install" in result["detected"]


def test_legacy_parse_ai_response():
    """Verify legacy parse_ai_response wrapper functions correctly."""
    result = legacy.parse_ai_response('{"severity": "low"}')
    assert result["severity"] == "low"


def test_legacy_format_pr_comment():
    """Verify legacy format_pr_comment wrapper functions correctly."""
    analysis = {"severity": "high", "failure_types": ["test"], "root_cause": "Failed"}
    comment = legacy.format_pr_comment(analysis, "sha12345", "run999", "org/repo")
    assert "ACID AI" in comment


def test_legacy_post_pr_comment(monkeypatch):
    """Verify legacy post_pr_comment wrapper functions correctly."""
    mock_post = MagicMock(return_value=True)
    monkeypatch.setattr("agent.self_healing_agent._post_pr_comment", mock_post)
    success = legacy.post_pr_comment("Hello")
    assert success is True
    mock_post.assert_called_once()


def test_legacy_analyse_with_claude(monkeypatch):
    """Verify legacy analyse_with_claude delegates properly."""
    mock_claude = MagicMock(return_value={"severity": "high"})
    monkeypatch.setattr("agent.self_healing_agent._analyse_with_claude", mock_claude)
    result = legacy.analyse_with_claude("logs", {"detected": ["test"]})
    assert result["severity"] == "high"


def test_legacy_analyse_with_gemini(monkeypatch):
    """Verify legacy analyse_with_gemini delegates properly."""
    mock_gemini = MagicMock(return_value={"severity": "medium"})
    monkeypatch.setattr("agent.self_healing_agent._analyse_with_gemini", mock_gemini)
    result = legacy.analyse_with_gemini("logs", {"detected": ["lint"]})
    assert result["severity"] == "medium"


def test_legacy_analyse_with_ai(monkeypatch):
    """Verify legacy analyse_with_ai delegates properly."""
    mock_ai = MagicMock(return_value={"severity": "low"})
    monkeypatch.setattr("agent.self_healing_agent._analyse_with_ai", mock_ai)
    result = legacy.analyse_with_ai("logs", {"detected": ["docker"]})
    assert result["severity"] == "low"


def test_legacy_main_delegates(monkeypatch):
    """Verify legacy main calls cli main and exits."""
    monkeypatch.setattr("agent.self_healing_agent._cli_main", lambda: 0)
    try:
        legacy.main()
    except SystemExit as e:
        assert e.code == 0

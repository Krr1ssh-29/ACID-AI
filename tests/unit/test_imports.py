"""Tests for module imports and package safety."""


def test_package_import():
    """Verify that the agent package can be imported cleanly."""
    import agent
    assert hasattr(agent, "__version__")
    assert agent.__version__ == "0.1.0"


def test_all_submodules_import_cleanly():
    """Verify that all agent submodules can be imported without side effects."""
    import agent.models
    import agent.config
    import agent.collector
    import agent.classifier
    import agent.parser
    import agent.formatter
    import agent.github
    import agent.providers
    import agent.cli
    import agent.self_healing_agent
    import agent.evidence

    assert agent.models is not None
    assert agent.config is not None
    assert agent.collector is not None
    assert agent.classifier is not None
    assert agent.parser is not None
    assert agent.formatter is not None
    assert agent.github is not None
    assert agent.providers is not None
    assert agent.cli is not None
    assert agent.self_healing_agent is not None
    assert agent.evidence is not None


def test_public_api_exports():
    """Verify that agent.__all__ contains the expected public symbols."""
    import agent
    expected_symbols = [
        "__version__",
        "AnalysisResult",
        "FixSuggestion",
        "FailureContext",
        "AgentConfig",
        "StepOutcome",
        "PipelineStatus",
        "StepEvidence",
        "PipelineEvidence",
        "load_config",
        "validate_credentials",
        "read_logs",
        "read_logs_bounded",
        "strip_ansi",
        "parse_step_outcomes",
        "split_stage_logs",
        "extract_stack_trace_snippet",
        "classify_failures",
        "parse_ai_response",
        "format_pr_comment",
        "post_pr_comment",
        "analyse_with_ai",
        "analyse_with_claude",
        "analyse_with_gemini",
        "BaseAIProvider",
        "AnthropicProvider",
        "GeminiProvider",
        "get_provider",
        "main",
    ]
    for sym in expected_symbols:
        assert hasattr(agent, sym), f"Expected symbol '{sym}' missing from agent"
        assert sym in agent.__all__, f"Expected symbol '{sym}' missing from agent.__all__"


def test_import_has_no_network_side_effects(monkeypatch):
    """Verify that importing agent modules does not trigger any network calls."""
    def fail_network(*args, **kwargs):
        raise AssertionError("Unexpected network call during module import!")

    monkeypatch.setattr("socket.socket.connect", fail_network)
    # Re-import to confirm safety
    import agent.self_healing_agent
    import agent.cli
    assert agent.self_healing_agent is not None
    assert agent.cli is not None


def test_agent_main_delegates(mocker):
    """Verify that agent.main delegates to agent.cli.main."""
    import agent
    mock_cli_main = mocker.patch("agent.cli.main", return_value=0)
    result = agent.main(["--test-arg"])
    mock_cli_main.assert_called_once_with(["--test-arg"])
    assert result == 0


def test_agent_module_execution(mocker):
    """Verify python -m agent execution invokes agent.cli.main."""
    import runpy
    mock_cli_main = mocker.patch("agent.cli.main", return_value=0)
    mock_sys_exit = mocker.patch("sys.exit")
    runpy.run_module("agent", run_name="__main__")
    mock_cli_main.assert_called_once()
    mock_sys_exit.assert_called_once_with(0)

"""Tests for Pydantic models and schemas in agent.models."""
import pytest
from pydantic import ValidationError
from agent.models import (
    FixSuggestion,
    FailureContext,
    AnalysisResult,
    AgentConfig,
)


def test_fix_suggestion_valid():
    """Verify FixSuggestion accepts valid failure categories."""
    fix = FixSuggestion(
        type="test",
        title="Fix assertion in test_app.py",
        description="Update expected status code",
        code="assert response.status_code == 200",
    )
    assert fix.type == "test"
    assert fix.title == "Fix assertion in test_app.py"
    assert fix.code is not None


def test_fix_suggestion_invalid_type():
    """Verify FixSuggestion rejects invalid type literal."""
    with pytest.raises(ValidationError):
        FixSuggestion(
            type="invalid_category",  # type: ignore
            title="Invalid",
            description="Should fail",
        )


def test_failure_context_defaults():
    """Verify FailureContext initializes with empty collections."""
    ctx = FailureContext()
    assert ctx.detected == []
    assert ctx.raw == {}


def test_analysis_result_normalization():
    """Verify AnalysisResult normalizes comma-separated string to list."""
    result = AnalysisResult(
        severity="high",
        failure_types="test, lint",  # comma-separated string input
        root_cause="AssertionError occurred in test stage.",
        fixes=[
            FixSuggestion(type="test", title="Fix test", description="Fix it")
        ],
        confidence="high",
    )
    assert result.failure_types == ["test", "lint"]
    assert result.severity == "high"
    assert len(result.fixes) == 1


def test_agent_config_defaults():
    """Verify default values in AgentConfig."""
    cfg = AgentConfig()
    assert cfg.ai_provider == "claude"
    assert cfg.anthropic_model == "claude-sonnet-4-6"
    assert cfg.gemini_model == "gemini-3.8-flash"
    assert cfg.ai_timeout_seconds == 60
    assert cfg.commit_sha == "unknown"
    assert cfg.run_id == "unknown"
    assert cfg.log_file == "combined-logs.txt"


def test_agent_config_provider_normalization():
    """Verify AgentConfig normalizes provider casing and empty strings."""
    cfg_upper = AgentConfig(ai_provider="GEMINI")  # type: ignore
    assert cfg_upper.ai_provider == "gemini"

    cfg_empty = AgentConfig(ai_provider="")  # type: ignore
    assert cfg_empty.ai_provider == "claude"

    cfg_whitespace = AgentConfig(ai_provider="   ")  # type: ignore
    assert cfg_whitespace.ai_provider == "claude"


def test_step_outcome_and_pipeline_status_enums():
    """Verify StepOutcome and PipelineStatus enums have expected values."""
    from agent.models import StepOutcome, PipelineStatus

    assert StepOutcome.SUCCESS == "success"
    assert StepOutcome.FAILURE == "failure"
    assert StepOutcome.SKIPPED == "skipped"
    assert StepOutcome.CANCELLED == "cancelled"

    assert PipelineStatus.HEALTHY == "healthy"
    assert PipelineStatus.FAILED == "failed"
    assert PipelineStatus.INCONCLUSIVE == "inconclusive"
    assert PipelineStatus.ERROR == "error"


def test_step_and_pipeline_evidence_models():
    """Verify StepEvidence and PipelineEvidence validation and defaults."""
    from agent.models import StepOutcome, PipelineStatus, StepEvidence, PipelineEvidence

    step = StepEvidence(
        step_id="lint",
        outcome=StepOutcome.FAILURE,
        log_snippet="app.py:12:1: E302",
        failure_category="lint",
    )
    assert step.step_id == "lint"
    assert step.outcome == StepOutcome.FAILURE

    evidence = PipelineEvidence(
        status=PipelineStatus.FAILED,
        step_outcomes={"lint": StepOutcome.FAILURE},
        detected_failures=["lint"],
        logs_by_step={"lint": "app.py:12:1: E302"},
        combined_log="Combined...",
    )
    assert evidence.status == PipelineStatus.FAILED
    assert "lint" in evidence.detected_failures


def test_failure_context_subscript_and_status():
    """Verify FailureContext backwards-compatible dict access and status attribute."""
    from agent.models import PipelineStatus

    ctx = FailureContext(
        detected=["test"],
        raw={"test": True},
        status=PipelineStatus.FAILED,
        details="Pytest assertion failed",
    )
    assert ctx["detected"] == ["test"]
    assert ctx["status"] == PipelineStatus.FAILED
    assert ctx.get("details") == "Pytest assertion failed"
    assert ctx.get("nonexistent", "default_val") == "default_val"

"""Tests for CLI entry point and pipeline orchestrator in agent.cli."""
import json
from unittest.mock import MagicMock
from agent.cli import main
from agent.models import AgentConfig


def test_main_credential_validation_failure(capsys):
    """Verify main returns 1 when credentials for active provider are missing."""
    cfg = AgentConfig(ai_provider="claude", anthropic_api_key=None)
    exit_code = main(config=cfg)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "AI_PROVIDER=claude but ANTHROPIC_API_KEY not set" in captured.out


def test_main_healthy_pipeline_direct_push(monkeypatch, capsys):
    """Verify main exits 0 and does not post comment when pipeline is healthy on direct push."""
    monkeypatch.setattr("agent.cli.read_logs", lambda log_file: "All checks passed cleanly")
    monkeypatch.setattr("agent.cli.classify_failures", lambda logs: {"detected": [], "raw": {}})

    mock_post = MagicMock()
    mock_ai = MagicMock()
    monkeypatch.setattr("agent.cli.post_pr_comment", mock_post)
    monkeypatch.setattr("agent.cli.analyse_with_ai", mock_ai)

    cfg = AgentConfig(
        ai_provider="claude",
        anthropic_api_key="test-anthropic-key",
        pr_number=None,  # direct push
    )
    exit_code = main(config=cfg)
    assert exit_code == 0
    mock_post.assert_not_called()
    mock_ai.assert_not_called()
    captured = capsys.readouterr()
    assert "No failures detected — pipeline healthy" in captured.out


def test_main_healthy_pipeline_silent_bypass_on_pr(monkeypatch, capsys):
    """Verify healthy PR run exits 0 and silently bypasses without posting comments or calling AI.

    Satisfies Phase 00 requirement FR-02 (0 tokens, 0 comments on healthy runs).
    """
    from agent.models import FailureContext, PipelineStatus

    healthy_context = FailureContext(
        detected=[],
        raw={"install": False, "lint": False, "test": False, "docker": False},
        status=PipelineStatus.HEALTHY,
        details="All steps succeeded",
    )
    monkeypatch.setattr("agent.cli.read_logs", lambda log_file: "All tests passed")
    monkeypatch.setattr("agent.cli.classify_failures", lambda logs: healthy_context)

    mock_post = MagicMock()
    mock_ai = MagicMock()
    monkeypatch.setattr("agent.cli.post_pr_comment", mock_post)
    monkeypatch.setattr("agent.cli.analyse_with_ai", mock_ai)

    cfg = AgentConfig(
        ai_provider="claude",
        anthropic_api_key="test-anthropic-key",
        pr_number="12",
        repo_name="owner/repo",
    )
    exit_code = main(config=cfg)
    assert exit_code == 0
    mock_post.assert_not_called()
    mock_ai.assert_not_called()
    captured = capsys.readouterr()
    assert "Silent bypass active" in captured.out


def test_main_inconclusive_pipeline_exits_without_ai_calls(monkeypatch, capsys):
    """Verify inconclusive pipeline exits with code 2 and does not call AI or post comments."""
    from agent.models import FailureContext, PipelineStatus

    inconclusive_context = FailureContext(
        detected=[],
        raw={},
        status=PipelineStatus.INCONCLUSIVE,
        details="Pipeline cancelled",
    )
    monkeypatch.setattr("agent.cli.read_logs", lambda log_file: "Partial logs...")
    monkeypatch.setattr("agent.cli.classify_failures", lambda logs: inconclusive_context)

    mock_post = MagicMock()
    mock_ai = MagicMock()
    monkeypatch.setattr("agent.cli.post_pr_comment", mock_post)
    monkeypatch.setattr("agent.cli.analyse_with_ai", mock_ai)

    cfg = AgentConfig(
        ai_provider="claude",
        anthropic_api_key="test-anthropic-key",
        pr_number="12",
        repo_name="owner/repo",
    )
    exit_code = main(config=cfg)
    assert exit_code == 2
    mock_post.assert_not_called()
    mock_ai.assert_not_called()
    captured = capsys.readouterr()
    assert "inconclusive" in captured.out.lower()


def test_main_error_pipeline_exits_code_1_without_ai_calls(monkeypatch, capsys):
    """Verify log collection error exits with code 1 and does not call AI."""
    from agent.models import FailureContext, PipelineStatus

    error_context = FailureContext(
        detected=[],
        raw={},
        status=PipelineStatus.ERROR,
        details="Log file missing",
    )
    monkeypatch.setattr("agent.cli.read_logs", lambda log_file: "No log file found")
    monkeypatch.setattr("agent.cli.classify_failures", lambda logs: error_context)

    mock_post = MagicMock()
    mock_ai = MagicMock()
    monkeypatch.setattr("agent.cli.post_pr_comment", mock_post)
    monkeypatch.setattr("agent.cli.analyse_with_ai", mock_ai)

    cfg = AgentConfig(
        ai_provider="claude",
        anthropic_api_key="test-anthropic-key",
        pr_number="12",
        repo_name="owner/repo",
    )
    exit_code = main(config=cfg)
    assert exit_code == 1
    mock_post.assert_not_called()
    mock_ai.assert_not_called()
    captured = capsys.readouterr()
    assert "Input/collection error" in captured.out


def test_main_triage_flow_success(monkeypatch, tmp_path):
    """Verify complete failure triage flow: diagnosis, PR comment, and analysis JSON output."""
    monkeypatch.setattr("agent.cli.read_logs", lambda log_file: "FAILED test_app.py")
    monkeypatch.setattr("agent.cli.classify_failures", lambda logs: {"detected": ["test"], "raw": {"test": True}})

    mock_analysis = {
        "severity": "high",
        "failure_types": ["test"],
        "root_cause": "AssertionError in test_app.py",
        "fixes": [{"type": "test", "title": "Fix test", "description": "Update code"}],
        "prevention": "Test locally first",
        "confidence": "high",
    }
    monkeypatch.setattr("agent.cli.analyse_with_ai", lambda logs, ctx, cfg: mock_analysis)

    mock_post = MagicMock(return_value=True)
    monkeypatch.setattr("agent.cli.post_pr_comment", mock_post)

    # Change working dir to tmp_path so agent-analysis.json writes to temporary location
    monkeypatch.chdir(tmp_path)

    cfg = AgentConfig(
        ai_provider="claude",
        anthropic_api_key="test-anthropic-key",
        pr_number="5",
        repo_name="org/repo",
        commit_sha="1234567890abcdef",
        run_id="999",
    )
    exit_code = main(config=cfg)
    assert exit_code == 0
    mock_post.assert_called_once()

    # Verify agent-analysis.json was created with expected contents
    analysis_file = tmp_path / "agent-analysis.json"
    assert analysis_file.exists()
    saved = json.loads(analysis_file.read_text(encoding="utf-8"))
    assert saved["root_cause"] == "AssertionError in test_app.py"


def test_main_ai_json_decode_error(monkeypatch, capsys):
    """Verify main returns 1 when AI response is not valid JSON."""
    monkeypatch.setattr("agent.cli.read_logs", lambda log_file: "error log")
    monkeypatch.setattr("agent.cli.classify_failures", lambda logs: {"detected": ["lint"], "raw": {}})

    def raise_json_error(*args, **kwargs):
        raise json.JSONDecodeError("Invalid JSON", "doc", 0)

    monkeypatch.setattr("agent.cli.analyse_with_ai", raise_json_error)

    cfg = AgentConfig(ai_provider="claude", anthropic_api_key="test-anthropic-key")
    exit_code = main(config=cfg)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Failed to parse AI response as JSON" in captured.out


def test_main_ai_provider_generic_error(monkeypatch, capsys):
    """Verify main returns 1 when AI provider raises an unexpected error."""
    monkeypatch.setattr("agent.cli.read_logs", lambda log_file: "error log")
    monkeypatch.setattr("agent.cli.classify_failures", lambda logs: {"detected": ["lint"], "raw": {}})

    def raise_runtime_error(*args, **kwargs):
        raise RuntimeError("API quota exceeded")

    monkeypatch.setattr("agent.cli.analyse_with_ai", raise_runtime_error)

    cfg = AgentConfig(ai_provider="claude", anthropic_api_key="test-anthropic-key")
    exit_code = main(config=cfg)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "AI provider error: API quota exceeded" in captured.out


def test_main_triage_flow_with_patch_unverified_skips_pr(monkeypatch, tmp_path, capsys):
    """Verify CLI flow when generate_patch=True but verification fails closed (skips PR)."""
    from agent.models import (
        PatchProposal,
        PatchStatus,
        PatchValidationResult,
        VerificationResult,
        VerificationStatus,
        PublishResult,
        PublishStatus,
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agent.cli.read_logs", lambda log_file: "FAILED test_app.py")
    monkeypatch.setattr("agent.cli.classify_failures", lambda logs: {"detected": ["test"], "raw": {}})
    monkeypatch.setattr("agent.cli.analyse_with_ai", lambda *args, **kwargs: {"severity": "high", "root_cause": "err"})
    monkeypatch.setattr("agent.cli.post_pr_comment", lambda *args, **kwargs: True)

    mock_patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Fix test",
        validation=PatchValidationResult(is_valid=True),
    )
    mock_verif = VerificationResult(
        status=VerificationStatus.INFRASTRUCTURE_FAILURE,
        is_verified=False,
        exit_code=1,
    )
    mock_pub = PublishResult(
        status=PublishStatus.SKIPPED_UNVERIFIED,
        message="Refusing to publish unverified repair.",
    )

    monkeypatch.setattr("agent.patcher.generate_patch", lambda *args, **kwargs: mock_patch)
    monkeypatch.setattr("agent.runner.VerificationRunner.verify", lambda self, p: mock_verif)
    monkeypatch.setattr("agent.publisher.publish_repair_pr", lambda *args, **kwargs: mock_pub)

    cfg = AgentConfig(
        ai_provider="claude",
        anthropic_api_key="test-anthropic-key",
        generate_patch=True,
        enable_repair_pr=True,
    )
    exit_code = main(config=cfg)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Patch generation requested" in captured.out
    assert "Repair PR status: skipped_unverified" in captured.out


def test_main_triage_flow_with_verified_patch_publishes_draft_pr(monkeypatch, tmp_path, capsys):
    """Verify CLI flow when generate_patch=True and verification succeeds (publishes Draft PR)."""
    from agent.models import (
        PatchProposal,
        PatchStatus,
        PatchValidationResult,
        VerificationResult,
        VerificationStatus,
        PublishResult,
        PublishStatus,
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agent.cli.read_logs", lambda log_file: "FAILED test_app.py")
    monkeypatch.setattr("agent.cli.classify_failures", lambda logs: {"detected": ["test"], "raw": {}})
    monkeypatch.setattr("agent.cli.analyse_with_ai", lambda *args, **kwargs: {"severity": "high", "root_cause": "err"})
    monkeypatch.setattr("agent.cli.post_pr_comment", lambda *args, **kwargs: True)

    mock_patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Fix test",
        validation=PatchValidationResult(is_valid=True),
    )
    mock_verif = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
    )
    mock_pub = PublishResult(
        status=PublishStatus.PUBLISHED,
        pr_number=55,
        pr_url="https://github.com/org/repo/pull/55",
        message="Published Draft PR #55",
    )

    monkeypatch.setattr("agent.patcher.generate_patch", lambda *args, **kwargs: mock_patch)
    monkeypatch.setattr("agent.runner.VerificationRunner.verify", lambda self, p: mock_verif)
    monkeypatch.setattr("agent.publisher.publish_repair_pr", lambda *args, **kwargs: mock_pub)

    cfg = AgentConfig(
        ai_provider="claude",
        anthropic_api_key="test-anthropic-key",
        generate_patch=True,
        enable_repair_pr=True,
    )
    exit_code = main(config=cfg)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Draft PR created: #55" in captured.out


def test_main_missing_credentials_truthfully_emits_report_and_analysis(tmp_path, monkeypatch):
    """Confirm missing AI credentials do not silently skip report generation (Phase 5 review requirement 3)."""
    monkeypatch.chdir(tmp_path)
    cfg = AgentConfig(
        ai_provider="claude",
        anthropic_api_key=None,
        run_id="run-missing-cred-123",
        repo_name="org/repo",
    )
    exit_code = main(config=cfg)
    assert exit_code == 1

    # Verify agent-analysis.json is created and explains missing credentials
    analysis_file = tmp_path / "agent-analysis.json"
    assert analysis_file.exists()
    analysis_data = json.loads(analysis_file.read_text(encoding="utf-8"))
    assert analysis_data["status"] == "blocked"
    assert "Live diagnosis was unavailable" in analysis_data["details"]

    # Verify report was generated in reports/
    from agent.report import get_report
    rep = get_report("run-missing-cred-123")
    assert rep is not None
    assert rep.outcome == "blocked"
    assert "Live diagnosis was unavailable" in rep.stop_reason
    assert "ANTHROPIC_API_KEY not set" in rep.stop_reason

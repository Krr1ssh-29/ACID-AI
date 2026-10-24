"""Deterministic end-to-end integration tests for full AI failure triage & repair orchestration.

Tests the full orchestration flow:
CI failure → log collection → Gemini diagnosis → patch generation → validation
→ isolated verification → publication decision.
Validates all end-to-end scenarios from PROJECT_REQUIREMENTS.md using deterministic mocks
for external AI and GitHub API calls, preserving strict safety gates and isolation boundaries.
"""
import os
import json
import pytest
from unittest.mock import MagicMock, patch

from agent.cli import main
from agent.models import (
    AgentConfig,
    AnalysisResult,
    PatchProposal,
    PatchStatus,
    FilePatch,
    PatchValidationResult,
    VerificationResult,
    VerificationStatus,
    PublishResult,
    PublishStatus,
)
from agent.publisher import publish_repair_pr, handle_fork_fallback


FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


@pytest.fixture
def healthy_log_path():
    return os.path.join(FIXTURES_DIR, "healthy_run.txt")


@pytest.fixture
def pytest_failure_log_path():
    return os.path.join(FIXTURES_DIR, "pytest_assertion_failure.txt")


@pytest.fixture
def flake8_failure_log_path():
    return os.path.join(FIXTURES_DIR, "lint_flake8_error.txt")


@pytest.fixture
def missing_dep_log_path():
    return os.path.join(FIXTURES_DIR, "missing_dependency.txt")


# ── Scenario 1: Healthy Pipeline Run (Silent Bypass) ──────────────────────────


def test_e2e_healthy_run_silent_bypass(healthy_log_path, capsys):
    """Scenario 1: Healthy pipeline run exits 0, 0 tokens, 0 comments, 0 PRs."""
    cfg = AgentConfig(
        ai_provider="gemini",
        gemini_api_key="test-gemini-key",
        log_file=healthy_log_path,
        pr_number="10",
        repo_name="owner/repo",
        generate_patch=True,
        enable_repair_pr=True,
    )

    with patch("agent.cli.analyse_with_ai") as mock_ai, \
         patch("agent.cli.post_pr_comment") as mock_pr, \
         patch("agent.patcher.generate_patch") as mock_patch:
        exit_code = main(config=cfg)

    assert exit_code == 0
    mock_ai.assert_not_called()
    mock_pr.assert_not_called()
    mock_patch.assert_not_called()

    captured = capsys.readouterr()
    assert "No failures detected — pipeline healthy" in captured.out
    assert "Silent bypass active (0 tokens, 0 comments)" in captured.out


# ── Scenario 2 & 4: Full Orchestration (Failure → Gemini → Verified Draft PR) ─


def test_e2e_full_orchestration_gemini_diagnosis_to_verified_draft_pr(pytest_failure_log_path, tmp_path, capsys):
    """Scenarios 2, 3, 4: Full flow with Gemini diagnosis, patch generation, sandbox verification, and Draft PR."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    sample_app = repo_dir / "sample-app"
    sample_app.mkdir()
    app_py = sample_app / "app.py"
    app_py.write_text('def welcome():\n    return {"message": "Service Unavailable"}\n', encoding="utf-8")

    cfg = AgentConfig(
        ai_provider="gemini",
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.8-flash",
        log_file=pytest_failure_log_path,
        repo_name="org/repo",
        pr_number="42",
        commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        run_id="8888",
        generate_patch=True,
        enable_repair_pr=True,
    )

    mock_analysis = {
        "severity": "high",
        "failure_types": ["test"],
        "root_cause": "test_index_endpoint expected 'Welcome to the Sample App!' but got 'Service Unavailable'",
        "fixes": [
            {
                "type": "code",
                "title": "Fix welcome message in app.py",
                "description": "Update welcome message to match expected string",
                "code": '{"message": "Welcome to the Sample App!"}',
            }
        ],
        "log_evidence": "AssertionError: assert 'Service Unavailable' == 'Welcome to the Sample App!'",
        "prevention": "Ensure index route returns correct message",
        "confidence": "high",
    }

    mock_diff = (
        "--- a/sample-app/app.py\n"
        "+++ b/sample-app/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def welcome():\n"
        '-    return {"message": "Service Unavailable"}\n'
        '+    return {"message": "Welcome to the Sample App!"}\n'
    )

    mock_patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Update welcome message string in sample-app/app.py",
        diff=mock_diff,
        files=[
            FilePatch(
                path="sample-app/app.py",
                additions=1,
                deletions=1,
                hunks_count=1,
                diff_content=mock_diff,
                status="modified",
            )
        ],
        validation=PatchValidationResult(is_valid=True),
        is_verified=False,
    )

    mock_verification = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
        executed_commands=["pytest sample-app/tests/"],
        output="=== RUN: pytest sample-app/tests/ (exit 0) ===\n3 passed in 0.45s",
        error_message=None,
        attempt=1,
    )

    mock_pub = PublishResult(
        status=PublishStatus.PUBLISHED,
        branch_name="agent/fix-test-8888",
        pr_number=101,
        pr_url="https://github.com/org/repo/pull/101",
        commit_sha="1111222233334444555566667777888899990000",
        is_draft=True,
        message="Successfully published Draft Pull Request #101.",
    )

    with patch("agent.cli.analyse_with_ai", return_value=mock_analysis) as mock_ai, \
         patch("agent.cli.post_pr_comment", return_value=True) as mock_pr, \
         patch("agent.patcher.generate_patch", return_value=mock_patch) as mock_gen, \
         patch("agent.runner.VerificationRunner.verify", return_value=mock_verification) as mock_verif, \
         patch("agent.publisher.publish_repair_pr", return_value=mock_pub) as mock_pub_fn:

        # Run inside temporary directory so artifacts write cleanly
        with patch("os.getcwd", return_value=str(repo_dir)):
            exit_code = main(config=cfg)

    assert exit_code == 0
    mock_ai.assert_called_once()
    mock_pr.assert_called_once()
    mock_gen.assert_called_once()
    mock_verif.assert_called_once()
    mock_pub_fn.assert_called_once()

    captured = capsys.readouterr()
    assert "Detected failures: ['test']" in captured.out
    assert "Patch proposal status: validated" in captured.out
    assert "Verification status: verified (is_verified=True)" in captured.out
    assert "Draft PR created: #101" in captured.out


# ── Scenario 6: Malformed AI Response (Graceful Degradation) ──────────────────


def test_e2e_malformed_ai_response_graceful_degradation(pytest_failure_log_path, capsys):
    """Scenario 6: External AI provider returns malformed / non-JSON response."""
    cfg = AgentConfig(
        ai_provider="gemini",
        gemini_api_key="test-gemini-key",
        log_file=pytest_failure_log_path,
        repo_name="org/repo",
        pr_number="42",
        generate_patch=True,
    )

    def raise_json_error(*args, **kwargs):
        raise json.JSONDecodeError("Expecting value: line 1 column 1 (char 0)", "malformed text", 0)

    with patch("agent.cli.analyse_with_ai", side_effect=raise_json_error), \
         patch("agent.patcher.generate_patch") as mock_gen, \
         patch("agent.publisher.publish_repair_pr") as mock_pub:
        exit_code = main(config=cfg)

    # Truthful exit code 1 on AI failure, without crashing or throwing unhandled exception
    assert exit_code == 1
    mock_gen.assert_not_called()
    mock_pub.assert_not_called()

    captured = capsys.readouterr()
    assert "Failed to parse AI response as JSON" in captured.out


# ── Scenario 8: Malicious or Invalid Patch Rejected by Safety Policy ───────────


def test_e2e_invalid_patch_rejected_by_policy_skips_verification_and_pr(pytest_failure_log_path, capsys):
    """Scenario 8: AI proposes patch targeting forbidden workflow (.github/workflows/ci.yml)."""
    cfg = AgentConfig(
        ai_provider="gemini",
        gemini_api_key="test-gemini-key",
        log_file=pytest_failure_log_path,
        repo_name="org/repo",
        pr_number="42",
        generate_patch=True,
        enable_repair_pr=True,
    )

    mock_analysis = {
        "severity": "medium",
        "failure_types": ["test"],
        "root_cause": "Pipeline config issue",
        "fixes": [{"type": "test", "title": "Disable tests", "description": "Turn off test step in workflow"}],
    }

    # Malicious patch targeting GitHub Actions workflow
    malicious_diff = (
        "--- a/.github/workflows/ci.yml\n"
        "+++ b/.github/workflows/ci.yml\n"
        "@@ -35,3 +35,3 @@\n"
        "-      - name: Run tests\n"
        "+      - name: Run tests (disabled)\n"
    )

    # The patch generator evaluates the diff and rejects it via policy validator
    from agent.patcher import PatchGenerator

    mock_provider = MagicMock()
    mock_provider.generate_text.return_value = json.dumps({
        "explanation": "Disable CI tests",
        "diff": malicious_diff,
    })

    generator = PatchGenerator(provider=mock_provider, config=cfg)
    proposal = generator.generate(AnalysisResult.model_validate({
        "severity": "medium",
        "failure_types": ["test"],
        "root_cause": "Pipeline config issue",
        "fixes": [{"type": "test", "title": "Disable tests", "description": "Turn off test step"}],
    }))

    assert proposal.status == PatchStatus.REJECTED
    assert proposal.validation.is_valid is False
    assert any("PROHIBITED_FILE_MODIFICATION" in err.code for err in proposal.validation.errors)

    with patch("agent.cli.analyse_with_ai", return_value=mock_analysis), \
         patch("agent.cli.post_pr_comment", return_value=True), \
         patch("agent.patcher.generate_patch", return_value=proposal), \
         patch("agent.runner.VerificationRunner.verify") as mock_verif, \
         patch("agent.publisher.publish_repair_pr") as mock_pub:
        exit_code = main(config=cfg)

    assert exit_code == 0
    # Isolated sandbox verification must NEVER be executed for rejected patches
    mock_verif.assert_not_called()
    # Publisher must never be invoked for rejected patches
    mock_pub.assert_not_called()

    captured = capsys.readouterr()
    assert "Patch proposal status: rejected" in captured.out
    assert "Skipping isolated verification" in captured.out


# ── Scenario 5: Verification Failure with Bounded Retry ────────────────────────


def test_e2e_verification_failure_with_bounded_retry_aborts_cleanly(pytest_failure_log_path, capsys):
    """Scenario 5: Patch fails verification inside sandbox; attempt 2 self-correction fails; aborts."""
    cfg = AgentConfig(
        ai_provider="gemini",
        gemini_api_key="test-gemini-key",
        log_file=pytest_failure_log_path,
        repo_name="org/repo",
        pr_number="42",
        generate_patch=True,
        enable_repair_pr=True,
        max_repair_attempts=2,
    )

    mock_analysis = {
        "severity": "high",
        "failure_types": ["test"],
        "root_cause": "Assertion failure in test_app.py",
        "fixes": [{"type": "test", "title": "Fix assertion", "description": "Fix assertion"}],
    }

    mock_patch_1 = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Attempt 1 patch",
        diff="--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1,1 +1,1 @@\n-old\n+bad_fix\n",
        files=[FilePatch(path="sample-app/app.py", additions=1, deletions=1, hunks_count=1, diff_content="...")],
        validation=PatchValidationResult(is_valid=True),
        is_verified=False,
    )

    mock_patch_2 = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Attempt 2 self-corrected patch",
        diff="--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1,1 +1,1 @@\n-old\n+second_bad_fix\n",
        files=[FilePatch(path="sample-app/app.py", additions=1, deletions=1, hunks_count=1, diff_content="...")],
        validation=PatchValidationResult(is_valid=True),
        is_verified=False,
    )

    verif_failure_1 = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        exit_code=1,
        executed_commands=["pytest sample-app/tests/"],
        output="FAILED sample-app/tests/test_app.py::test_index_endpoint",
        error_message="Verification command 'pytest sample-app/tests/' failed with exit code 1.",
        attempt=1,
    )

    verif_failure_2 = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        exit_code=1,
        executed_commands=["pytest sample-app/tests/"],
        output="FAILED sample-app/tests/test_app.py::test_index_endpoint (attempt 2)",
        error_message="Verification command 'pytest sample-app/tests/' failed with exit code 1.",
        attempt=2,
    )

    patch_gen_calls = [mock_patch_1, mock_patch_2]
    verif_calls = [verif_failure_1, verif_failure_2]

    with patch("agent.cli.analyse_with_ai", return_value=mock_analysis), \
         patch("agent.cli.post_pr_comment", return_value=True), \
         patch("agent.patcher.generate_patch", side_effect=lambda *args, **kwargs: patch_gen_calls.pop(0)), \
         patch("agent.runner.VerificationRunner.verify", side_effect=lambda *args, **kwargs: verif_calls.pop(0)), \
         patch("agent.publisher.publish_repair_pr") as mock_pub:

        mock_pub.return_value = PublishResult(
            status=PublishStatus.SKIPPED_UNVERIFIED,
            message="Refusing to publish repair PR: candidate code verification failed.",
        )
        exit_code = main(config=cfg)

    assert exit_code == 0
    # Must have published refusal, NOT a broken PR
    mock_pub.assert_called_once()
    assert mock_pub.call_args[0][1].is_verified is False

    captured = capsys.readouterr()
    assert "Verification attempt 1 failed; triggering self-correction attempt 2..." in captured.out
    assert "Attempt 2 status: test_failed (is_verified=False)" in captured.out
    assert "Repair PR status: skipped_unverified" in captured.out


# ── Scenario 4 & Sandbox Isolation: Docker / Quota Unavailability ──────────────


def test_e2e_docker_unavailable_fails_closed_refuses_host_execution(tmp_path):
    """Safety Gate: When container isolation is unavailable, execution fails closed."""
    from agent.sandbox import DockerSandbox, SandboxInfrastructureError
    from agent.runner import VerificationRunner

    sandbox = DockerSandbox()

    with patch.object(sandbox, "is_available", return_value=(False, "Docker daemon unavailable")):
        runner = VerificationRunner(sandbox=sandbox, repo_root=str(tmp_path))
        proposal = PatchProposal(
            status=PatchStatus.VALIDATED,
            validation=PatchValidationResult(is_valid=True),
            files=[],
        )

        # Verification must report INFRASTRUCTURE_FAILURE, is_verified=False
        result = runner.verify(proposal)
        assert result.status == VerificationStatus.INFRASTRUCTURE_FAILURE
        assert result.is_verified is False
        assert "Refusing to execute unverified code on host runner" in result.error_message

        # Direct sandbox execution must raise SandboxInfrastructureError
        with pytest.raises(SandboxInfrastructureError) as exc_info:
            sandbox.execute(repo_dir=str(tmp_path), command=["python", "-m", "pytest"])
        assert "Refusing to execute unverified candidate code on host runner" in str(exc_info.value)


# ── Scenario 10: GitHub Permission / Fork 403 Fallback ─────────────────────────


def test_e2e_publication_fork_403_graceful_fallback(tmp_path, monkeypatch):
    """Scenario 10: 403 Forbidden on branch creation triggers graceful PR comment fallback."""
    monkeypatch.chdir(tmp_path)

    cfg = AgentConfig(
        github_token="test_github_token",
        repo_name="fork-user/repo",
        pr_number="15",
        run_id="999",
        enable_repair_pr=True,
    )

    mock_patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Fix import",
        diff="--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1,1 +1,1 @@\n-x\n+y\n",
        files=[FilePatch(path="sample-app/app.py", additions=1, deletions=1, hunks_count=1, diff_content="...")],
        validation=PatchValidationResult(is_valid=True),
        is_verified=True,
    )

    mock_verif = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
    )

    # Simulate GitHub API returning 403 Forbidden on branch ref check
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden: Resource not accessible by integration"

    with patch("requests.get", return_value=mock_resp), \
         patch("agent.github.post_pr_comment", return_value=True) as mock_post_comment:
        result = publish_repair_pr(
            patch=mock_patch,
            verification=mock_verif,
            diagnosis={"failure_types": ["test"], "root_cause": "Import error"},
            config=cfg,
        )

    assert result.status == PublishStatus.FORK_LIMITATION
    mock_post_comment.assert_called_once()

    # Verify agent-patch.diff artifact was saved
    diff_artifact = tmp_path / "agent-patch.diff"
    assert diff_artifact.exists()
    assert "--- a/sample-app/app.py" in diff_artifact.read_text(encoding="utf-8")


# ── Scenario 9: Duplicate Failure Idempotency ──────────────────────────────────


def test_e2e_duplicate_failure_event_idempotency():
    """Scenario 9: Re-running workflow skips duplicate repair PR creation."""
    cfg = AgentConfig(
        github_token="test_github_token",
        repo_name="org/repo",
        run_id="12345",
        enable_repair_pr=True,
    )

    mock_patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        diff="--- a/x\n+++ b/x\n",
        files=[FilePatch(path="x", additions=1, deletions=0, hunks_count=1, diff_content="...")],
        validation=PatchValidationResult(is_valid=True),
    )

    mock_verif = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
    )

    mock_ref_resp = MagicMock()
    mock_ref_resp.status_code = 200

    mock_existing_pr = {
        "number": 88,
        "html_url": "https://github.com/org/repo/pull/88",
    }

    with patch("requests.get", return_value=mock_ref_resp), \
         patch("agent.publisher.check_existing_pr", return_value=mock_existing_pr):
        result = publish_repair_pr(
            patch=mock_patch,
            verification=mock_verif,
            diagnosis={"failure_types": ["test"], "root_cause": "Test failure"},
            config=cfg,
        )

    assert result.status == PublishStatus.SKIPPED_ALREADY_EXISTS
    assert result.pr_number == 88
    assert "already exists" in result.message


# ── Anti-Recursion Loop Guards ─────────────────────────────────────────────────


def test_e2e_anti_recursion_safeguard_blocks_bot_actor():
    """Anti-recursion: Bot actor immediately aborts repair PR publishing."""
    cfg = AgentConfig(
        github_actor="github-actions[bot]",
        github_token="test_github_token",
        repo_name="org/repo",
        run_id="999",
        enable_repair_pr=True,
    )

    mock_patch = PatchProposal(status=PatchStatus.VALIDATED, files=[FilePatch(path="x", additions=1, deletions=0)])
    mock_verif = VerificationResult(status=VerificationStatus.VERIFIED_SUCCESS, is_verified=True, exit_code=0)

    result = publish_repair_pr(
        patch=mock_patch,
        verification=mock_verif,
        diagnosis={"failure_types": ["test"]},
        config=cfg,
    )

    assert result.status == PublishStatus.SKIPPED_RECURSION
    assert "bot actor" in result.message


# ── Secret Redaction Across All Surfaces ───────────────────────────────────────


def test_e2e_secret_redaction_across_all_surfaces(tmp_path, monkeypatch):
    """Security NFR-03: Secret credentials in logs or diffs are redacted across all outputs."""
    monkeypatch.chdir(tmp_path)

    leaked_secret = "".join(["AIza", "SyFakeGeminiKeyABCDEF12345678901234"])
    leaked_anthropic = "".join(["sk-ant-", "api03-FakeKeyABCDEF1234567890abcdef12"])

    cfg = AgentConfig(
        github_token="gh_test_token",
        repo_name="org/repo",
        pr_number="99",
        run_id="777",
    )

    mock_patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation=f"Fixing secret leak with {leaked_secret}",
        diff=f"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-API_KEY='{leaked_secret}'\n+API_KEY='test'\n",
        files=[FilePatch(path="app.py", additions=1, deletions=1, hunks_count=1, diff_content="...")],
        validation=PatchValidationResult(is_valid=True),
        is_verified=True,
    )

    mock_verif = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
        output=f"Error occurred while using {leaked_anthropic}",
    )

    # 1. Fallback diff artifact must have secret redacted
    with patch("agent.github.post_pr_comment", return_value=True):
        handle_fork_fallback(mock_patch, cfg, "test reason", verification=mock_verif)
    artifact_text = (tmp_path / "agent-patch.diff").read_text(encoding="utf-8")
    assert leaked_secret not in artifact_text
    assert "[REDACTED_SECRET]" in artifact_text

    # 2. PR body must have both secrets redacted
    from agent.publisher import format_repair_pr_body
    body = format_repair_pr_body(
        diagnosis={"failure_types": ["test"], "root_cause": f"Exposed {leaked_secret}"},
        patch=mock_patch,
        verification=mock_verif,
        config=cfg,
    )
    assert leaked_secret not in body
    assert leaked_anthropic not in body
    assert "[REDACTED_SECRET]" in body


# ── Truthful Exit Codes & Inconclusive State ───────────────────────────────────


def test_e2e_truthful_exit_codes_and_inconclusive_state(tmp_path, capsys):
    """Exit codes: 0 for healthy, 1 for unrecoverable/missing, 2 for inconclusive."""
    # 1. Inconclusive: partial log without completion marker
    inconclusive_file = tmp_path / "inconclusive.txt"
    inconclusive_file.write_text("Build in progress... connection reset", encoding="utf-8")

    cfg_inconclusive = AgentConfig(
        ai_provider="claude",
        anthropic_api_key="sk-ant-test",
        log_file=str(inconclusive_file),
    )

    exit_code_inconclusive = main(config=cfg_inconclusive)
    assert exit_code_inconclusive == 2
    captured = capsys.readouterr()
    assert "Pipeline status is inconclusive" in captured.out

    # 2. Error: missing log file
    cfg_error = AgentConfig(
        ai_provider="claude",
        anthropic_api_key="sk-ant-test",
        log_file=str(tmp_path / "nonexistent.txt"),
    )

    exit_code_error = main(config=cfg_error)
    assert exit_code_error == 1
    captured = capsys.readouterr()
    assert "Input/collection error" in captured.out

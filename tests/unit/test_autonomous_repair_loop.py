"""Comprehensive unit tests for ACID AI Phase 4: Autonomous Repair and Retry Loop.

Covers all 10 required test criteria:
1. Known failing test repaired successfully.
2. Candidate patch that fails verification and triggers another attempt.
3. Successful retry after an initial failed patch.
4. Retry exhaustion.
5. Repeated identical patch detection.
6. Sandbox infrastructure failure that blocks further execution.
7. Missing AI credentials and provider failures.
8. Preservation of the original repository.
9. Healthy repository that requires no repair.
10. Accurate final reporting for partial repairs and unresolved failures.
"""
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from agent.models import (
    AgentConfig,
    AnalysisResult,
    FilePatch,
    FixSuggestion,
    PatchProposal,
    PatchStatus,
    PatchValidationResult,
    VerificationResult,
    VerificationStatus,
)
from agent.runner import run_repair_loop
from agent.sandbox import SandboxIsolationBackend
from dashboard.engine import run_repository_analysis


def make_valid_patch(diff: str, path: str = "sample-app/app.py", explanation: str = "Fix") -> PatchProposal:
    """Helper to build a policy-validated PatchProposal for tests."""
    return PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation=explanation,
        diff=diff,
        files=[
            FilePatch(
                path=path,
                status="modified",
                diff_content=diff,
                lines_added=1,
                lines_removed=1,
            )
        ],
        validation=PatchValidationResult(is_valid=True),
        is_verified=False,
    )


@pytest.fixture
def fake_git_repo():
    """Create a minimal temporary Git repository with failing evidence."""
    temp_dir = tempfile.mkdtemp(prefix="acid-test-repo-")
    dot_git = os.path.join(temp_dir, ".git")
    os.makedirs(os.path.join(dot_git, "refs", "heads"), exist_ok=True)
    with open(os.path.join(dot_git, "HEAD"), "w", encoding="utf-8") as f:
        f.write("ref: refs/heads/main\n")
    with open(os.path.join(dot_git, "refs", "heads", "main"), "w", encoding="utf-8") as f:
        f.write("a" * 40 + "\n")

    # Create target python code
    os.makedirs(os.path.join(temp_dir, "sample-app", "tests"), exist_ok=True)
    code_path = os.path.join(temp_dir, "sample-app", "app.py")
    with open(code_path, "w", encoding="utf-8") as f:
        f.write("def calculate():\n    return 500\n")
    test_path = os.path.join(temp_dir, "sample-app", "tests", "test_app.py")
    with open(test_path, "w", encoding="utf-8") as f:
        f.write("def test_calculate():\n    pass\n")

    # Create fixture failure logs
    log_path = os.path.join(temp_dir, "combined-logs.txt")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("=== STEP OUTCOMES ===\ninstall: success\nlint: success\ntest: failure\ndocker: skipped\n"
                "=== TEST LOGS ===\nFAILED sample-app/test_app.py::test_calculate - assert 500 == 200\n")

    yield temp_dir

    shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# Requirement 1: Known failing test repaired successfully
# ==============================================================================

def test_01_known_failing_test_repaired_successfully(fake_git_repo):
    """Verify that a failing test is repaired and verified in Attempt 1."""
    patch_success = VerificationResult(
        status=VerificationStatus.VERIFIED,
        is_verified=True,
        attempt=1,
        output="3 passed in 0.05s",
    )

    diff = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1,2 +1,2 @@\n-    return 500\n+    return 200\n"
    valid_patch = make_valid_patch(diff, explanation="Fix calculate return value")

    with patch("dashboard.engine.VerificationRunner.verify", return_value=patch_success), \
         patch("dashboard.engine.generate_patch", return_value=valid_patch):

        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="mock",
        )

        assert result["final_status"] == "repaired"
        assert result["is_healthy"] is True
        assert result["retry_count"] == 1
        assert len(result["verified_patches"]) == 1
        assert len(result["attempts"]) == 1

        att1 = result["attempts"][0]
        assert att1["attempt"] == 1
        assert att1["status"] == "VERIFIED"
        assert "verified repair" in att1["reason"].lower()
        assert "passed after verified repair" in result["stop_reason"].lower()


# ==============================================================================
# Requirement 2: Candidate patch fails verification and triggers another attempt
# ==============================================================================

def test_02_patch_fails_verification_and_triggers_retry(fake_git_repo):
    """Verify that an initial failing patch triggers a second attempt with failure evidence."""
    fail_res = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        attempt=1,
        output="FAILED test_calculate: still returned 300",
        error_message="Exit code 1",
    )
    pass_res = VerificationResult(
        status=VerificationStatus.VERIFIED,
        is_verified=True,
        attempt=2,
        output="3 passed in 0.05s",
    )

    verify_mock = MagicMock(side_effect=[fail_res, pass_res])

    diff_att1 = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1,2 +1,2 @@\n-    return 500\n+    return 300\n"
    diff_att2 = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1,2 +1,2 @@\n-    return 500\n+    return 200\n"

    patch_prop_1 = make_valid_patch(diff_att1, explanation="Attempt 1: try 300")
    patch_prop_2 = make_valid_patch(diff_att2, explanation="Attempt 2: correct fix 200")
    patch_mock = MagicMock(side_effect=[patch_prop_1, patch_prop_2])

    with patch("dashboard.engine.VerificationRunner.verify", verify_mock), \
         patch("dashboard.engine.generate_patch", patch_mock):

        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="mock",
        )

        assert verify_mock.call_count == 2
        assert result["retry_count"] == 2
        assert len(result["attempts"]) == 2
        assert result["attempts"][0]["status"] == "TEST_FAILED"
        assert result["attempts"][1]["status"] == "VERIFIED"


# ==============================================================================
# Requirement 3: Successful retry after an initial failed patch
# ==============================================================================

def test_03_successful_retry_after_initial_failed_patch(fake_git_repo):
    """Verify that a successful retry marks the repository repaired with truthful attempt history."""
    fail_res = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        attempt=1,
        output="AssertionError: 404 != 200",
        error_message="Test assertion failed",
    )
    pass_res = VerificationResult(
        status=VerificationStatus.VERIFIED,
        is_verified=True,
        attempt=2,
        output="PASSED test_calculate",
    )

    diff_1 = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1,2 +1,2 @@\n-    return 500\n+    return 404\n"
    diff_2 = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1,2 +1,2 @@\n-    return 500\n+    return 200\n"

    patch_1 = make_valid_patch(diff_1, explanation="Attempt 1")
    patch_2 = make_valid_patch(diff_2, explanation="Attempt 2")

    with patch("dashboard.engine.VerificationRunner.verify", side_effect=[fail_res, pass_res]), \
         patch("dashboard.engine.generate_patch", side_effect=[patch_1, patch_2]):

        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="mock",
        )

        assert result["final_status"] == "repaired"
        assert result["retry_count"] == 2
        assert len(result["verified_patches"]) == 1
        assert result["attempts"][0]["status"] == "TEST_FAILED"
        assert result["attempts"][1]["status"] == "VERIFIED"
        assert "retrying" in result["attempts"][0]["reason"].lower()


# ==============================================================================
# Requirement 4: Retry exhaustion
# ==============================================================================

def test_04_retry_exhaustion_stops_cleanly(fake_git_repo):
    """Verify that when attempts reach the limit without passing, loop halts with unresolved status."""
    fail_res = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        output="Failed consistently",
        error_message="Test failed in container",
    )

    patches = [
        make_valid_patch(
            f"--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1 +1 @@\n-500\n+{i}\n",
            explanation=f"Attempt {i}",
        )
        for i in [101, 102, 103]
    ]

    cfg = AgentConfig(max_repair_attempts=3)

    with patch("dashboard.engine.VerificationRunner.verify", return_value=fail_res) as mock_verify, \
         patch("dashboard.engine.generate_patch", side_effect=patches):

        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="mock",
            config=cfg,
        )

        assert mock_verify.call_count == 3
        assert result["final_status"] == "unresolved"
        assert result["retry_count"] == 3
        assert len(result["verified_patches"]) == 0
        assert "exhausted" in result["stop_reason"].lower()


# ==============================================================================
# Requirement 5: Repeated identical patch detection
# ==============================================================================

def test_05_repeated_identical_patch_detection_halts_loop(fake_git_repo):
    """Verify that producing the same diff twice stops the loop immediately."""
    fail_res = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        output="Still failing",
        error_message="Test failure",
    )

    identical_diff = (
        "--- a/sample-app/app.py\n"
        "+++ b/sample-app/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-    return 500\n"
        "+    return 400\n"
    )
    patch_identical = make_valid_patch(identical_diff, explanation="Try 400")

    with patch("dashboard.engine.VerificationRunner.verify", return_value=fail_res) as mock_verify, \
         patch("dashboard.engine.generate_patch", return_value=patch_identical):

        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="mock",
        )

        # Attempt 1 verified patch and failed.
        # Attempt 2 generated identical patch, detected repetition, halted before execution.
        assert mock_verify.call_count == 1
        assert result["final_status"] == "unresolved"
        assert result["retry_count"] == 2
        assert "repeated identical patch" in result["stop_reason"].lower()
        assert len(result["attempts"]) == 2
        assert result["attempts"][1]["status"] == "STALLED"


# ==============================================================================
# Requirement 6: Sandbox infrastructure failure blocks further execution
# ==============================================================================

def test_06_sandbox_infrastructure_failure_blocks_execution(fake_git_repo):
    """Verify that container runtime or disk quota infrastructure error halts loop with BLOCKED status."""
    infra_fail = VerificationResult(
        status=VerificationStatus.INFRASTRUCTURE_FAILURE,
        is_verified=False,
        error_message="Docker daemon unavailable or storage driver lacks quotas.",
        output="Docker connection error",
    )

    diff = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1 +1 @@\n-500\n+200\n"
    valid_patch = make_valid_patch(diff)

    with patch("dashboard.engine.VerificationRunner.verify", return_value=infra_fail), \
         patch("dashboard.engine.generate_patch", return_value=valid_patch):

        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="mock",
        )

        assert result["final_status"] == "blocked"
        assert "sandbox infrastructure" in result["stop_reason"].lower()
        assert result["truthfulness"]["host_execution_permitted"] is False
        assert result["attempts"][0]["status"] == "INFRASTRUCTURE_FAILURE"


# ==============================================================================
# Requirement 7: Missing AI credentials and provider failures
# ==============================================================================

def test_07_missing_ai_credentials_distinguished_from_checks(fake_git_repo):
    """Verify that missing API keys block AI triage while truthfully recording real checks."""
    cfg = AgentConfig(gemini_api_key="", anthropic_api_key="")

    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="gemini",
            config=cfg,
        )

        assert result["final_status"] == "blocked"
        assert "missing" in result["stop_reason"].lower() or "no gemini_api_key" in result["stop_reason"].lower()
        assert result["is_healthy"] is False  # Real checks still ran and found failure!
        assert result["stages"] is not None  # Real exit codes preserved


def test_07_provider_api_failure_handled_gracefully(fake_git_repo):
    """Verify provider runtime exceptions during diagnosis halt the loop with BLOCKED status."""
    cfg = AgentConfig(gemini_api_key="synthetic-test-key")

    mock_provider = MagicMock()
    mock_provider.diagnose.side_effect = RuntimeError("503 Service Unavailable: High load")

    with patch("agent.providers.GeminiProvider", return_value=mock_provider):
        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="gemini",
            config=cfg,
        )

        assert result["final_status"] == "blocked"
        assert "503" in result["stop_reason"]
        assert len(result["attempts"]) == 1
        assert result["attempts"][0]["status"] == "BLOCKED"


# ==============================================================================
# Requirement 8: Preservation of the original repository
# ==============================================================================

def test_08_preservation_of_original_repository(fake_git_repo):
    """Verify that autonomous repair operations never mutate the user's host repository."""
    code_file = os.path.join(fake_git_repo, "sample-app", "app.py")
    with open(code_file, "r", encoding="utf-8") as f:
        original_content = f.read()

    host_files_before = set()
    for root, _, files in os.walk(fake_git_repo):
        for f in files:
            host_files_before.add(os.path.relpath(os.path.join(root, f), fake_git_repo))

    patch_success = VerificationResult(
        status=VerificationStatus.VERIFIED,
        is_verified=True,
        attempt=1,
        output="Tests passed in container",
    )
    diff = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1 +1 @@\n-500\n+200\n"
    valid_patch = make_valid_patch(diff)

    with patch("dashboard.engine.VerificationRunner.verify", return_value=patch_success), \
         patch("dashboard.engine.generate_patch", return_value=valid_patch):

        run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="mock",
        )

    # Content of target code file in original repo must be strictly identical
    with open(code_file, "r", encoding="utf-8") as f:
        current_content = f.read()

    assert current_content == original_content

    # No stray patch or temp files left behind in original repository
    host_files_after = set()
    for root, _, files in os.walk(fake_git_repo):
        for f in files:
            host_files_after.add(os.path.relpath(os.path.join(root, f), fake_git_repo))

    assert host_files_after == host_files_before


# ==============================================================================
# Requirement 9: Healthy repository that requires no repair
# ==============================================================================

def test_09_healthy_repository_bypasses_repair_loop(fake_git_repo):
    """Verify that a passing repository bypasses patch generation and container verification."""
    # Write a healthy log output with all success step outcomes
    log_file = os.path.join(fake_git_repo, "combined-logs.txt")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("=== STEP OUTCOMES ===\ninstall: success\nlint: success\ntest: success\ndocker: success\n"
                "=== TEST LOGS ===\n3 passed in 0.05s\n")

    result = run_repository_analysis(
        repo_path=fake_git_repo,
        provider_mode="mock",
    )

    assert result["is_healthy"] is True
    assert result["status"] == "HEALTHY"
    assert result["retry_count"] == 0
    assert len(result["attempts"]) == 0
    assert result["verification"]["status"] == "SKIPPED_HEALTHY"
    assert result["publication"]["status"] == "SKIPPED_HEALTHY"
    assert result["run_record"]["is_healthy"] is True


# ==============================================================================
# Requirement 10: Accurate final reporting for partial repairs and unresolved failures
# ==============================================================================

def test_10_accurate_final_reporting_for_partial_repair(fake_git_repo):
    """Verify reporting when Issue 1 is repaired and verified, but Issue 2 fails on retry."""
    pass_res = VerificationResult(
        status=VerificationStatus.VERIFIED,
        is_verified=True,
        attempt=1,
        output="Issue 1 fixed",
    )
    fail_res = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        attempt=2,
        output="Issue 2 still failing",
        error_message="Exit code 1",
    )

    diff_1 = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1 +1 @@\n-500\n+200\n"
    diff_2 = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -2 +2 @@\n-bad\n+good\n"

    patch_1 = make_valid_patch(diff_1, explanation="Fix 1")
    patch_2 = make_valid_patch(diff_2, explanation="Fix 2")

    cfg = AgentConfig(max_repair_attempts=2)

    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.stdout = "FAILED sample-app/test_app.py::test_remaining"
    fake_proc.stderr = ""

    with patch("dashboard.engine.VerificationRunner.verify", side_effect=[pass_res, fail_res]), \
         patch("dashboard.engine.generate_patch", side_effect=[patch_1, patch_2]), \
         patch("dashboard.engine.subprocess.run", return_value=fake_proc):

        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="mock",
            config=cfg,
        )

        assert result["final_status"] == "partially repaired"
        assert len(result["verified_patches"]) == 1
        assert result["retry_count"] == 2
        assert "partially repaired" in result["stop_reason"].lower()


def test_10_accurate_final_reporting_for_unresolved_failure(fake_git_repo):
    """Verify reporting when 0 patches are verified and failures remain unresolved."""
    fail_res = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        attempt=1,
        output="Cannot resolve",
        error_message="Exit code 1",
    )

    diff = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1 +1 @@\n-500\n+200\n"
    patch_cand = make_valid_patch(diff)
    cfg = AgentConfig(max_repair_attempts=1)

    with patch("dashboard.engine.VerificationRunner.verify", return_value=fail_res), \
         patch("dashboard.engine.generate_patch", return_value=patch_cand):

        result = run_repository_analysis(
            repo_path=fake_git_repo,
            provider_mode="mock",
            config=cfg,
        )

        assert result["final_status"] == "unresolved"
        assert len(result["verified_patches"]) == 0
        assert result["retry_count"] == 1
        assert "exhausted" in result["stop_reason"].lower()


# ==============================================================================
# Direct unit test on agent.runner.run_repair_loop
# ==============================================================================

def test_runner_run_repair_loop_repeated_patch_detection():
    """Verify agent.runner.run_repair_loop halts immediately on repeated identical diffs."""
    diagnosis = AnalysisResult(
        severity="high",
        failure_types=["test"],
        root_cause="AssertionError",
        fixes=[FixSuggestion(type="test", title="Fix assertion", description="Change 500 to 200")],
        confidence="high",
    )

    class FailingSandbox(SandboxIsolationBackend):
        def is_available(self):
            return True, "Ready"

        def execute(self, repo_dir, command, timeout=180, env=None):
            return 1, "FAILED test_calculate", ""

    diff = (
        "--- a/sample-app/app.py\n"
        "+++ b/sample-app/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def calculate():\n"
        "-    return 500\n"
        "+    return 200\n"
    )
    patch_json = '{"explanation": "Fix", "diff": "' + diff.replace('\n', '\\n') + '"}'

    mock_provider = MagicMock()
    mock_provider.generate_text.return_value = patch_json

    with tempfile.TemporaryDirectory() as host_repo:
        os.makedirs(os.path.join(host_repo, "sample-app"), exist_ok=True)
        with open(os.path.join(host_repo, "sample-app", "app.py"), "w") as f:
            f.write("def calculate():\n    return 500\n")

        final_patch, final_result = run_repair_loop(
            diagnosis=diagnosis,
            repo_root=host_repo,
            sandbox=FailingSandbox(),
            provider=mock_provider,
            commands=["pytest"],
            max_attempts=3,
        )

        # Attempt 1 ran and failed verification.
        # Attempt 2 generated identical patch, detected repetition, halted immediately!
        assert final_result.status == VerificationStatus.TEST_FAILED
        assert final_result.is_verified is False
        assert "repeated identical patch" in final_result.error_message.lower()
        # Exactly 2 calls (attempt 1 and 2), not 3!
        assert mock_provider.generate_text.call_count == 2

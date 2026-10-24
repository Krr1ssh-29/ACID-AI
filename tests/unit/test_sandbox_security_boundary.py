"""Unit regression tests verifying the sandbox security boundary across ACID AI.

Guarantees:
1. Target repository code is NEVER executed on host Python, host shell, or host subprocess.
2. If Docker is unavailable, the system fails closed with truthful refusal (no host fallback).
3. Installation, lint, and test checks are never fabricated; unrun steps report 'Check not run'.
4. Candidate patch verification and discovery checks strictly route through DockerSandbox.
5. Repository immutability is preserved across all execution paths.
"""
import hashlib
import os
import tempfile
from unittest.mock import patch, MagicMock

from agent.config import AgentConfig
from agent.models import (
    FilePatch,
    PatchProposal,
    PatchStatus,
    PatchValidationResult,
    VerificationStatus,
)
from agent.runner import VerificationRunner
from agent.sandbox import DockerSandbox, SandboxError, SandboxTimeoutError
from dashboard.engine import (
    execute_live_pytest,
    run_repository_analysis,
    get_system_status,
)


def _init_fake_git(repo_dir: str):
    """Initialize minimal git repository metadata (.git/HEAD and main ref)."""
    dot_git = os.path.join(repo_dir, ".git")
    os.makedirs(os.path.join(dot_git, "refs", "heads"), exist_ok=True)
    with open(os.path.join(dot_git, "HEAD"), "w", encoding="utf-8") as f:
        f.write("ref: refs/heads/main\n")
    with open(os.path.join(dot_git, "refs", "heads", "main"), "w", encoding="utf-8") as f:
        f.write("a" * 40 + "\n")


def _assert_zero_target_code_execution_on_host(mock_subproc):
    """Assert that host subprocess.run was NEVER invoked for python or pytest."""
    for call_args in mock_subproc.call_args_list:
        if call_args[0]:
            cmd = call_args[0][0]
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            assert "pytest" not in cmd_str.lower(), f"Forbidden host pytest execution: {cmd_str}"
            assert "python" not in cmd_str.lower(), f"Forbidden host python execution: {cmd_str}"


def test_execute_live_pytest_never_executes_host_subprocess():
    """Verify execute_live_pytest NEVER invokes host subprocess with python or pytest."""
    with tempfile.TemporaryDirectory() as temp_repo:
        os.makedirs(os.path.join(temp_repo, "sample-app", "tests"), exist_ok=True)
        with open(os.path.join(temp_repo, "sample-app", "tests", "test_x.py"), "w") as f:
            f.write("def test_x(): assert True\n")

        # Mock DockerSandbox.is_available to return False (Docker offline)
        with patch.object(DockerSandbox, "is_available", return_value=(False, "Docker daemon not running")), \
             patch("subprocess.run") as mock_host_subproc:

            output = execute_live_pytest(temp_repo)

            # Assert host subprocess was NEVER called
            mock_host_subproc.assert_not_called()

            # Assert output truthfully reports blocked execution
            assert "[BLOCKED] Docker sandbox unavailable" in output
            assert "Refusing to execute unverified repository code on host runner" in output
            assert "install: skipped" in output
            assert "lint: skipped" in output
            assert "test: failure" in output
            assert "docker: failure" in output


def test_execute_live_pytest_no_fabricated_logs():
    """Verify execute_live_pytest never fabricates installation or lint success messages."""
    with tempfile.TemporaryDirectory() as temp_repo:
        os.makedirs(os.path.join(temp_repo, "sample-app", "tests"), exist_ok=True)

        with patch.object(DockerSandbox, "is_available", return_value=(True, "Docker operational")), \
             patch.object(DockerSandbox, "execute", return_value=(0, "=== 1 passed in 0.1s ===", "")):

            output = execute_live_pytest(temp_repo)

            # Ensure fabricated logs are completely absent
            assert "Dependencies verified" not in output
            assert "No lint errors" not in output
            assert "install: success" not in output
            assert "lint: success" not in output

            # Ensure truthful reporting
            assert "=== INSTALL LOGS ===\nCheck not run" in output
            assert "=== LINT LOGS ===\nCheck not run" in output
            assert "install: skipped" in output
            assert "lint: skipped" in output
            assert "test: success" in output
            assert "docker: success" in output


def test_execute_live_pytest_handles_sandbox_timeout_truthfully():
    """Verify execute_live_pytest handles container timeout without host execution fallback."""
    with tempfile.TemporaryDirectory() as temp_repo:
        os.makedirs(os.path.join(temp_repo, "sample-app", "tests"), exist_ok=True)

        with patch.object(DockerSandbox, "is_available", return_value=(True, "Docker operational")), \
             patch.object(DockerSandbox, "execute", side_effect=SandboxTimeoutError("Timed out after 30s")):

            output = execute_live_pytest(temp_repo)

            assert "Execution timed out inside container sandbox" in output
            assert "test: failure" in output
            assert "docker: failure" in output


def test_execute_live_pytest_handles_sandbox_error_truthfully():
    """Verify execute_live_pytest handles sandbox errors without host execution fallback."""
    with tempfile.TemporaryDirectory() as temp_repo:
        os.makedirs(os.path.join(temp_repo, "sample-app", "tests"), exist_ok=True)

        with patch.object(DockerSandbox, "is_available", return_value=(True, "Docker operational")), \
             patch.object(DockerSandbox, "execute", side_effect=SandboxError("Container startup error")):

            output = execute_live_pytest(temp_repo)

            assert "Sandbox error" in output
            assert "test: failure" in output
            assert "docker: failure" in output


def test_run_repository_analysis_discovery_never_uses_host_subprocess():
    """Verify repository test discovery routes through DockerSandbox and never runs on host."""
    with tempfile.TemporaryDirectory() as temp_repo:
        _init_fake_git(temp_repo)
        os.makedirs(os.path.join(temp_repo, "sample-app", "tests"), exist_ok=True)
        with open(os.path.join(temp_repo, "sample-app", "tests", "test_x.py"), "w") as f:
            f.write("def test_fail(): assert False\n")

        # Case 1: Docker offline -> must fail closed with BLOCKED status, 0 host python/pytest calls
        with patch.object(DockerSandbox, "is_available", return_value=(False, "Docker offline")), \
             patch("subprocess.run", wraps=os.system if False else None) as mock_host_subproc:

            res = run_repository_analysis(
                repo_path=temp_repo,
                provider_mode="mock",
            )

            # Assert git commands are allowed for repo metadata, but host python/pytest is NEVER called
            _assert_zero_target_code_execution_on_host(mock_host_subproc)
            # Pipeline should fail closed or be blocked
            assert res["final_status"] in ("blocked", "unresolved")
            # Raw log must show blocked message
            assert "[BLOCKED] Docker sandbox unavailable" in res["logs_raw"]
            assert "install: skipped" in res["logs_raw"]
            assert "lint: skipped" in res["logs_raw"]


def test_run_repository_analysis_discovery_routes_through_sandbox_when_available():
    """Verify repository test discovery executes inside DockerSandbox when operational."""
    with tempfile.TemporaryDirectory() as temp_repo:
        _init_fake_git(temp_repo)
        os.makedirs(os.path.join(temp_repo, "sample-app", "tests"), exist_ok=True)
        with open(os.path.join(temp_repo, "sample-app", "tests", "test_x.py"), "w") as f:
            f.write("def test_x(): assert True\n")

        fake_sandbox_output = (
            0,
            "=== 1 passed in 0.05s ===\nsample-app/tests/test_x.py::test_x PASSED\n",
            "",
        )

        with patch.object(DockerSandbox, "is_available", return_value=(True, "Docker operational")), \
             patch.object(DockerSandbox, "execute", return_value=fake_sandbox_output) as mock_sb_exec:

            res = run_repository_analysis(
                repo_path=temp_repo,
                provider_mode="mock",
            )

            # DockerSandbox.execute must have been called for test discovery
            assert mock_sb_exec.called
            # Fabricated logs must not exist
            assert "Dependencies verified in disposable workspace" not in res["logs_raw"]
            assert "Check not run" in res["logs_raw"]


def test_run_repository_analysis_remaining_checks_never_use_host_subprocess():
    """Verify remaining failure checks in multi-attempt repair route through sandbox.execute."""
    pass_res = MagicMock()
    pass_res.is_verified = True
    pass_res.status = VerificationStatus.VERIFIED
    pass_res.error_message = ""
    pass_res.output = "1 passed"
    pass_res.model_dump = lambda: {"is_verified": True, "status": "VERIFIED"}

    fail_res = MagicMock()
    fail_res.is_verified = False
    fail_res.status = VerificationStatus.TEST_FAILED
    fail_res.error_message = "1 failed"
    fail_res.output = "FAILED test_remaining"
    fail_res.model_dump = lambda: {"is_verified": False, "status": "TEST_FAILED"}

    diff_1 = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -1 +1 @@\n-500\n+200\n"
    diff_2 = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ -2 +2 @@\n-bad\n+good\n"

    patch_1 = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Fix 1",
        diff=diff_1,
        files=[FilePatch(path="sample-app/app.py", status="modified", diff_content=diff_1)],
        validation=PatchValidationResult(is_valid=True),
    )
    patch_2 = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Fix 2",
        diff=diff_2,
        files=[FilePatch(path="sample-app/app.py", status="modified", diff_content=diff_2)],
        validation=PatchValidationResult(is_valid=True),
    )

    cfg = AgentConfig(max_repair_attempts=2)

    with tempfile.TemporaryDirectory() as temp_repo:
        _init_fake_git(temp_repo)
        os.makedirs(os.path.join(temp_repo, "sample-app", "tests"), exist_ok=True)
        with open(os.path.join(temp_repo, "sample-app", "app.py"), "w") as f:
            f.write("500\nbad\n")
        with open(os.path.join(temp_repo, "combined-logs.txt"), "w") as f:
            f.write("=== STEP OUTCOMES ===\ntest: failure\nFAILED test_app.py\n")

        with patch("dashboard.engine.VerificationRunner.verify", side_effect=[pass_res, fail_res]), \
             patch("dashboard.engine.generate_patch", side_effect=[patch_1, patch_2]), \
             patch.object(DockerSandbox, "execute", return_value=(1, "FAILED test_remaining", "")) as mock_sb_exec, \
             patch("subprocess.run") as mock_host_subproc:

            result = run_repository_analysis(
                repo_path=temp_repo,
                provider_mode="mock",
                config=cfg,
            )

            # Assert target code was NEVER executed on host
            _assert_zero_target_code_execution_on_host(mock_host_subproc)
            # Assert DockerSandbox.execute was used for remaining check
            assert mock_sb_exec.called
            assert result["final_status"] == "partially repaired"


def test_get_system_status_truthfully_reflects_sandbox_state():
    """Verify get_system_status evaluates Docker availability and storage isolation."""
    # When Docker is unavailable
    with patch.object(DockerSandbox, "is_available", return_value=(False, "Docker daemon not running")):
        status = get_system_status()
        assert status["docker_available"] is False
        assert status["disk_quota_enforced"] is False
        assert status["isolation_guard_status"] == "FAIL_CLOSED_ACTIVE"

    # When Docker is operational with storage isolation
    with patch.object(DockerSandbox, "is_available", return_value=(True, "Docker daemon is running and reachable.")):
        status = get_system_status()
        assert status["docker_available"] is True
        assert status["disk_quota_enforced"] is True
        assert status["isolation_guard_status"] == "FAIL_CLOSED_ACTIVE"


def test_target_repository_remains_strictly_immutable_on_verification_failure():
    """Verify target repository files are not mutated when candidate patch fails verification."""
    def hash_dir(path: str) -> dict:
        h = {}
        for root, _, files in os.walk(path):
            for f in files:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, path)
                with open(p, "rb") as fh:
                    h[rel] = hashlib.sha256(fh.read()).hexdigest()
        return h

    with tempfile.TemporaryDirectory() as temp_repo:
        f1 = os.path.join(temp_repo, "app.py")
        with open(f1, "w", encoding="utf-8") as fh:
            fh.write("def original_code(): return 100\n")

        before_hashes = hash_dir(temp_repo)

        diff = (
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1 +1 @@\n"
            "-def original_code(): return 100\n"
            "+def original_code(): return 200\n"
        )
        proposal = PatchProposal(
            status=PatchStatus.VALIDATED,
            explanation="Candidate mutating app.py",
            diff=diff,
            files=[FilePatch(path="app.py", status="modified", diff_content=diff)],
            validation=PatchValidationResult(is_valid=True),
        )

        sandbox = DockerSandbox(require_disk_quota=False)
        with patch.object(sandbox, "is_available", return_value=(True, "OK")), \
             patch.object(sandbox, "execute", return_value=(1, "FAILED test", "")):

            runner = VerificationRunner(sandbox=sandbox, repo_root=temp_repo)
            result = runner.verify(proposal, commands=["pytest"])

            assert result.is_verified is False
            after_hashes = hash_dir(temp_repo)
            assert before_hashes == after_hashes, "Target repository files were mutated during failed verification!"

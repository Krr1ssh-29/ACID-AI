"""End-to-end integration tests for Phase 4 autonomous repair loop using real Docker sandbox."""
import os
import tempfile
from unittest.mock import MagicMock
import pytest

from agent.config import AgentConfig
from agent.models import (
    AnalysisResult,
    FixSuggestion,
    VerificationStatus,
)
from agent.runner import run_repair_loop
from agent.sandbox import DockerSandbox


def get_live_sandbox():
    """Return an active DockerSandbox instance or skip if Docker is unavailable."""
    sandbox = DockerSandbox(
        image="cicd-sandbox:latest",
        read_only_rootfs=True,
        workspace_tmpfs_size="256m",
        storage_isolation_mode="read_only_tmpfs",
        require_disk_quota=True,
    )
    is_avail, reason = sandbox.is_available()
    if not is_avail:
        pytest.skip(f"Live Docker sandbox unavailable: {reason}")
    return sandbox


def test_e2e_real_sandbox_autonomous_repair_success():
    """Test full autonomous repair cycle with real Docker container executing pytest verification."""
    sandbox = get_live_sandbox()

    diagnosis = AnalysisResult(
        severity="high",
        failure_types=["test"],
        root_cause="AssertionError in test_target: expected 2, got 3",
        fixes=[FixSuggestion(type="test", title="Fix assertion", description="Change 3 to 2")],
        confidence="high",
    )

    diff = (
        "--- a/sample-app/test_target.py\n"
        "+++ b/sample-app/test_target.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def test_addition():\n"
        "-    assert 1 + 1 == 3\n"
        "+    assert 1 + 1 == 2\n"
    )
    patch_json = '{"explanation": "Fix addition assertion", "diff": "' + diff.replace('\n', '\\n') + '"}'

    mock_provider = MagicMock()
    mock_provider.generate_text.return_value = patch_json

    with tempfile.TemporaryDirectory() as host_repo:
        os.makedirs(os.path.join(host_repo, "sample-app"), exist_ok=True)
        test_file = os.path.join(host_repo, "sample-app", "test_target.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def test_addition():\n    assert 1 + 1 == 3\n")

        cfg = AgentConfig(
            verification_commands=["pytest sample-app/test_target.py"],
            max_repair_attempts=3,
        )

        final_patch, final_result = run_repair_loop(
            diagnosis=diagnosis,
            repo_root=host_repo,
            sandbox=sandbox,
            provider=mock_provider,
            config=cfg,
            commands=["pytest sample-app/test_target.py"],
        )

        assert final_result.status == VerificationStatus.VERIFIED
        assert final_result.is_verified is True
        assert final_result.attempt == 1
        assert "1 passed" in final_result.output

        # Zero Host Mutation: Host repo must remain untouched
        with open(test_file, "r", encoding="utf-8") as f:
            assert f.read() == "def test_addition():\n    assert 1 + 1 == 3\n"


def test_e2e_real_sandbox_autonomous_repair_retry_success():
    """Test autonomous retry cycle: attempt 1 fails in real container, attempt 2 passes."""
    sandbox = get_live_sandbox()

    diagnosis = AnalysisResult(
        severity="high",
        failure_types=["test"],
        root_cause="AssertionError in test_target",
        fixes=[FixSuggestion(type="test", title="Fix assertion", description="Correct math")],
        confidence="high",
    )

    # Attempt 1 produces an incorrect fix that still fails
    diff_fail = (
        "--- a/sample-app/test_target.py\n"
        "+++ b/sample-app/test_target.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def test_addition():\n"
        "-    assert 1 + 1 == 3\n"
        "+    assert 1 + 1 == 99\n"
    )
    # Attempt 2 produces the correct fix
    diff_pass = (
        "--- a/sample-app/test_target.py\n"
        "+++ b/sample-app/test_target.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def test_addition():\n"
        "-    assert 1 + 1 == 3\n"
        "+    assert 1 + 1 == 2\n"
    )

    json_fail = '{"explanation": "Bad fix 99", "diff": "' + diff_fail.replace('\n', '\\n') + '"}'
    json_pass = '{"explanation": "Good fix 2", "diff": "' + diff_pass.replace('\n', '\\n') + '"}'

    mock_provider = MagicMock()
    mock_provider.generate_text.side_effect = [json_fail, json_pass]

    with tempfile.TemporaryDirectory() as host_repo:
        os.makedirs(os.path.join(host_repo, "sample-app"), exist_ok=True)
        test_file = os.path.join(host_repo, "sample-app", "test_target.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def test_addition():\n    assert 1 + 1 == 3\n")

        cfg = AgentConfig(
            verification_commands=["pytest sample-app/test_target.py"],
            max_repair_attempts=3,
        )

        final_patch, final_result = run_repair_loop(
            diagnosis=diagnosis,
            repo_root=host_repo,
            sandbox=sandbox,
            provider=mock_provider,
            config=cfg,
            commands=["pytest sample-app/test_target.py"],
        )

        assert final_result.status == VerificationStatus.VERIFIED
        assert final_result.is_verified is True
        assert final_result.attempt == 2
        assert "1 passed" in final_result.output
        assert mock_provider.generate_text.call_count == 2

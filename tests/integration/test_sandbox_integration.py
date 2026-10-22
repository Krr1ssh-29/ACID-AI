"""Integration tests for sandbox container isolation boundary.

Explicitly distinguishes host-refusal safety tests from real container isolation tests.
Never claims real container isolation is verified unless a live container actually runs.
"""
import os
import tempfile
from unittest.mock import patch
import pytest

from agent.models import (
    PatchProposal,
    PatchStatus,
    PatchValidationResult,
    VerificationStatus,
)
from agent.runner import VerificationRunner
from agent.sandbox import DockerSandbox, SandboxInfrastructureError


def test_docker_unavailable_refuses_host_execution():
    """Verify that when container isolation is unavailable, execution fails closed.

    Guarantees that unverified candidate code is NEVER executed directly on the host runner.
    """
    sandbox = DockerSandbox()
    # Force unavailable state to test deterministic refusal behavior
    with patch.object(sandbox, "is_available", return_value=(False, "Docker daemon unavailable")):
        with tempfile.TemporaryDirectory() as temp_repo:
            # Direct execute call must raise SandboxInfrastructureError
            with pytest.raises(SandboxInfrastructureError) as exc_info:
                sandbox.execute(
                    repo_dir=temp_repo,
                    command=["python", "-m", "pytest"],
                )
            assert "Refusing to execute unverified candidate code on host runner" in str(exc_info.value)

            # Verification runner must assign truthful INFRASTRUCTURE_FAILURE status
            runner = VerificationRunner(sandbox=sandbox, repo_root=temp_repo)
            proposal = PatchProposal(
                status=PatchStatus.VALIDATED,
                validation=PatchValidationResult(is_valid=True),
                files=[],
            )
            result = runner.verify(proposal)
            assert result.status == VerificationStatus.INFRASTRUCTURE_FAILURE
            assert result.is_verified is False
            assert "Refusing to execute unverified code on host runner" in result.error_message


def test_live_docker_fails_closed_when_disk_quota_unsupported():
    """Verify that when require_disk_quota=True (production default), the environment fails closed.

    Proves that on standard Docker engines where --storage-opt is not enforced,
    candidate code execution is strictly refused and reports INFRASTRUCTURE_FAILURE.
    """
    docker_check = DockerSandbox(require_disk_quota=False)
    docker_ok, docker_reason = docker_check.is_available()
    if not docker_ok:
        pytest.skip(
            f"Live Docker daemon unavailable ({docker_reason}). "
            "Cannot probe disk quota enforcement on an unavailable Docker daemon."
        )

    sandbox = DockerSandbox(require_disk_quota=True)
    available, reason = sandbox.is_available()

    # The probe must detect that this Docker environment does NOT enforce disk quotas
    assert available is False
    assert "Missing enforceable disk quota" in reason

    with tempfile.TemporaryDirectory() as temp_repo:
        runner = VerificationRunner(sandbox=sandbox, repo_root=temp_repo)
        proposal = PatchProposal(
            status=PatchStatus.VALIDATED,
            validation=PatchValidationResult(is_valid=True),
            files=[],
        )
        result = runner.verify(proposal)
        assert result.status == VerificationStatus.INFRASTRUCTURE_FAILURE
        assert result.is_verified is False
        assert "Missing enforceable disk quota" in result.error_message


def test_real_docker_container_isolation():
    """Verify live Docker container isolation when a real Docker daemon is operational.

    Tests network denial, non-root user (UID 1000), dropped capabilities,
    and host filesystem boundaries directly against the live Docker daemon.
    """
    sandbox = DockerSandbox(require_disk_quota=False)
    available, reason = sandbox.is_available()

    if not available:
        pytest.skip(
            f"Live Docker daemon unavailable ({reason}). "
            "Skipping real container integration test. "
            "Real container isolation NOT demonstrated on this host."
        )

    # --- Live Docker Container Execution ---
    with tempfile.TemporaryDirectory() as temp_repo:
        # 1. Create benign test inside disposable workspace
        test_file = os.path.join(temp_repo, "test_live_sample.py")
        with open(test_file, "w") as f:
            f.write("def test_container_pass():\n    assert 1 + 1 == 2\n")

        # 2. Benign verification command execution inside container
        code, stdout, stderr = sandbox.execute(
            repo_dir=temp_repo,
            command=["python", "-m", "pytest", "test_live_sample.py"],
            timeout=60,
        )
        assert code == 0, f"Expected 0 inside container, got {code}. stderr: {stderr}"
        assert "passed" in stdout

        # 3. Verify network denial (--network none) inside container
        net_code, net_out, net_err = sandbox.execute(
            repo_dir=temp_repo,
            command=[
                "python", "-c",
                "import urllib.request; urllib.request.urlopen('http://1.1.1.1', timeout=2)",
            ],
            timeout=10,
        )
        assert net_code != 0, "Network connection unexpectedly succeeded with --network none!"
        combined_err = (net_out + net_err).lower()
        assert "unreachable" in combined_err or "urlerror" in combined_err or "failed" in combined_err

        # 4. Verify non-root user execution (--user 1000:1000)
        id_code, id_out, _ = sandbox.execute(
            repo_dir=temp_repo,
            command=["python", "-c", "import os; print(os.getuid())"],
            timeout=10,
        )
        assert id_code == 0
        assert id_out.strip() == "1000", f"Expected UID 1000, got: {id_out.strip()}"

        # 5. Verify host filesystem boundary: host roots and docker socket are inaccessible
        fs_code, fs_out, _ = sandbox.execute(
            repo_dir=temp_repo,
            command=[
                "python", "-c",
                "import os; print(os.path.exists('/var/run/docker.sock') or os.path.exists('/host'))",
            ],
            timeout=10,
        )
        assert fs_code == 0
        assert fs_out.strip() == "False", f"Host resources unexpectedly detected: {fs_out.strip()}"

        # 6. Verify dropped capabilities (--cap-drop=ALL): raw socket creation denied
        cap_code, cap_out, cap_err = sandbox.execute(
            repo_dir=temp_repo,
            command=[
                "python", "-c",
                "import socket; socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)",
            ],
            timeout=10,
        )
        assert cap_code != 0
        err_lower = (cap_out + cap_err).lower()
        assert "operation not permitted" in err_lower or "permissionerror" in err_lower

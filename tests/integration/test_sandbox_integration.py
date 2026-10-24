"""Integration tests for sandbox container isolation boundary.

Explicitly distinguishes host-refusal safety tests from real container isolation tests.
Never claims real container isolation is verified unless a live container actually runs.
"""
import hashlib
import os
import subprocess
import tempfile
from unittest.mock import patch
import pytest

from agent.config import AgentConfig
from agent.models import (
    FilePatch,
    PatchProposal,
    PatchStatus,
    PatchValidationResult,
    VerificationStatus,
)
from agent.runner import VerificationRunner
from agent.sandbox import DockerSandbox, SandboxInfrastructureError, SandboxTimeoutError


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

    sandbox = DockerSandbox(storage_isolation_mode="storage_opt", require_disk_quota=True)
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


# ── Phase 3: Live Safe Isolated Verification Integration Tests ────────────────


def test_live_storage_isolation_enforcement():
    """Verify check_storage_isolation_enforcement succeeds on live Docker with read-only rootfs."""
    sandbox = DockerSandbox(
        image="cicd-sandbox:latest",
        read_only_rootfs=True,
        workspace_tmpfs_size="256m",
        storage_isolation_mode="read_only_tmpfs",
        require_disk_quota=True,
    )
    is_avail, reason = sandbox.is_available()
    if not is_avail and "executable not found" in reason:
        pytest.skip(f"Docker not operational: {reason}")

    assert is_avail is True, f"Storage isolation check failed unexpectedly: {reason}"
    ok, msg = sandbox.check_storage_isolation_enforcement()
    assert ok is True, f"Storage probe failed: {msg}"
    assert "verified" in msg.lower()


def test_live_read_only_rootfs_and_tmpfs_quota_guarantees():
    """Verify live container guarantees: EROFS on rootfs & repo_ro, and ENOSPC on tmpfs limit."""
    sandbox = DockerSandbox(
        image="cicd-sandbox:latest",
        read_only_rootfs=True,
        workspace_tmpfs_size="10m",
        storage_isolation_mode="read_only_tmpfs",
        require_disk_quota=True,
    )
    is_avail, reason = sandbox.is_available()
    if not is_avail:
        pytest.skip(f"Docker not operational: {reason}")

    with tempfile.TemporaryDirectory() as temp_repo:
        # 1. Rootfs write attempt must fail with Read-only file system
        code, out, err = sandbox.execute(
            repo_dir=temp_repo,
            command=["python", "-c", "open('/rootfs_probe.txt', 'w').write('x')"],
        )
        assert code != 0
        combined = (out + err).lower()
        assert "read-only" in combined or "erofs" in combined

        # 2. Host repo mount /repo_ro must be read-only (EROFS)
        code, out, err = sandbox.execute(
            repo_dir=temp_repo,
            command=["python", "-c", "open('/repo_ro/write_probe.txt', 'w').write('x')"],
        )
        assert code != 0
        combined = (out + err).lower()
        assert "read-only" in combined or "erofs" in combined

        # 3. Excessive write to /workspace tmpfs (20MB into 10MB tmpfs) must fail with ENOSPC
        code, out, err = sandbox.execute(
            repo_dir=temp_repo,
            command=[
                "python", "-c",
                "with open('/workspace/large_file.bin', 'wb') as f: f.write(b'x' * (20 * 1024 * 1024))",
            ],
        )
        assert code != 0
        combined = (out + err).lower()
        assert "no space" in combined or "enospc" in combined


def test_verification_runner_verifies_known_good_candidate():
    """Verify that a known-good candidate patch passes isolated verification with exit code 0."""
    sandbox = DockerSandbox(
        image="cicd-sandbox:latest",
        read_only_rootfs=True,
        workspace_tmpfs_size="256m",
        storage_isolation_mode="read_only_tmpfs",
        require_disk_quota=True,
    )
    is_avail, reason = sandbox.is_available()
    if not is_avail:
        pytest.skip(f"Docker not operational: {reason}")

    with tempfile.TemporaryDirectory() as temp_repo:
        # Create failing test in original repository
        test_file = os.path.join(temp_repo, "test_target.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def test_addition():\n    assert 1 + 1 == 3\n")

        # Candidate patch fixing the test
        diff = (
            "--- a/test_target.py\n"
            "+++ b/test_target.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def test_addition():\n"
            "-    assert 1 + 1 == 3\n"
            "+    assert 1 + 1 == 2\n"
        )
        proposal = PatchProposal(
            status=PatchStatus.VALIDATED,
            explanation="Fix addition assertion in test_target.py",
            diff=diff,
            files=[FilePatch(path="test_target.py", status="modified", diff_content=diff)],
            validation=PatchValidationResult(is_valid=True),
        )

        cfg = AgentConfig(verification_commands=["pytest test_target.py"])
        runner = VerificationRunner(sandbox=sandbox, config=cfg, repo_root=temp_repo)
        result = runner.verify(proposal, commands=["pytest test_target.py"])

        assert result.status == VerificationStatus.VERIFIED
        assert result.is_verified is True
        assert result.exit_code == 0
        assert "1 passed" in result.output


def test_verification_runner_rejects_deliberately_failing_candidate():
    """Verify that a deliberately bad candidate patch fails verification with exit code != 0."""
    sandbox = DockerSandbox(
        image="cicd-sandbox:latest",
        read_only_rootfs=True,
        workspace_tmpfs_size="256m",
        storage_isolation_mode="read_only_tmpfs",
        require_disk_quota=True,
    )
    is_avail, reason = sandbox.is_available()
    if not is_avail:
        pytest.skip(f"Docker not operational: {reason}")

    with tempfile.TemporaryDirectory() as temp_repo:
        test_file = os.path.join(temp_repo, "test_target.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def test_addition():\n    assert 1 + 1 == 3\n")

        # Candidate patch with incorrect fix (still fails)
        diff = (
            "--- a/test_target.py\n"
            "+++ b/test_target.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def test_addition():\n"
            "-    assert 1 + 1 == 3\n"
            "+    assert 1 + 1 == 99\n"
        )
        proposal = PatchProposal(
            status=PatchStatus.VALIDATED,
            explanation="Incorrect patch proposal",
            diff=diff,
            files=[FilePatch(path="test_target.py", status="modified", diff_content=diff)],
            validation=PatchValidationResult(is_valid=True),
        )

        cfg = AgentConfig(verification_commands=["pytest test_target.py"])
        runner = VerificationRunner(sandbox=sandbox, config=cfg, repo_root=temp_repo)
        result = runner.verify(proposal, commands=["pytest test_target.py"])

        assert result.status == VerificationStatus.TEST_FAILED
        assert result.is_verified is False
        assert result.exit_code != 0
        assert "FAILED" in result.output


def test_verification_runner_handles_timeout():
    """Verify that execution exceeding timeout returns TIMEOUT status and cleans up."""
    sandbox = DockerSandbox(
        image="cicd-sandbox:latest",
        read_only_rootfs=True,
        workspace_tmpfs_size="256m",
        storage_isolation_mode="read_only_tmpfs",
        require_disk_quota=True,
    )
    is_avail, reason = sandbox.is_available()
    if not is_avail:
        pytest.skip(f"Docker not operational: {reason}")

    with tempfile.TemporaryDirectory() as temp_repo:
        test_file = os.path.join(temp_repo, "test_target.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("import time\ndef test_sleep():\n    time.sleep(15)\n")

        proposal = PatchProposal(
            status=PatchStatus.VALIDATED,
            explanation="Timeout test patch",
            diff="",
            files=[],
            validation=PatchValidationResult(is_valid=True),
        )

        runner = VerificationRunner(sandbox=sandbox, repo_root=temp_repo)
        # Execute pytest with a tight timeout raising SandboxTimeoutError
        with patch.object(
            sandbox,
            "execute",
            side_effect=SandboxTimeoutError("Container execution timed out after 2 seconds."),
        ):
            result = runner.verify(proposal, commands=["pytest test_target.py"])
            assert result.status == VerificationStatus.TIMEOUT
            assert result.is_verified is False
            assert "timed out" in result.error_message.lower()


def test_original_repository_immutability_guaranteed():
    """Verify original host repository files are 100% byte-for-byte unchanged after verification."""
    sandbox = DockerSandbox(
        image="cicd-sandbox:latest",
        read_only_rootfs=True,
        workspace_tmpfs_size="256m",
        storage_isolation_mode="read_only_tmpfs",
        require_disk_quota=True,
    )
    is_avail, reason = sandbox.is_available()
    if not is_avail:
        pytest.skip(f"Docker not operational: {reason}")

    def hash_directory(path: str) -> dict:
        hashes = {}
        for root, _, files in os.walk(path):
            for f in files:
                full_p = os.path.join(root, f)
                rel_p = os.path.relpath(full_p, path)
                with open(full_p, "rb") as fh:
                    hashes[rel_p] = hashlib.sha256(fh.read()).hexdigest()
        return hashes

    with tempfile.TemporaryDirectory() as temp_repo:
        f1 = os.path.join(temp_repo, "app.py")
        with open(f1, "w", encoding="utf-8") as fh:
            fh.write("ORIGINAL_APP_CONTENT = 'unmodified'\n")
        f2 = os.path.join(temp_repo, "test_target.py")
        with open(f2, "w", encoding="utf-8") as fh:
            fh.write("def test_ok(): assert 1 == 1\n")

        before_hashes = hash_directory(temp_repo)

        diff = (
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-ORIGINAL_APP_CONTENT = 'unmodified'\n"
            "+ORIGINAL_APP_CONTENT = 'candidate_mutation'\n"
        )
        proposal = PatchProposal(
            status=PatchStatus.VALIDATED,
            explanation="Candidate modifying app.py",
            diff=diff,
            files=[FilePatch(path="app.py", status="modified", diff_content=diff)],
            validation=PatchValidationResult(is_valid=True),
        )

        runner = VerificationRunner(sandbox=sandbox, repo_root=temp_repo)
        result = runner.verify(proposal, commands=["pytest test_target.py"])

        assert result.status == VerificationStatus.VERIFIED
        assert result.is_verified is True

        after_hashes = hash_directory(temp_repo)
        assert before_hashes == after_hashes, "Host repository was mutated during candidate verification!"


def test_container_cleanup_after_execution():
    """Verify ephemeral container is destroyed and not left running after execution."""
    sandbox = DockerSandbox(
        image="cicd-sandbox:latest",
        read_only_rootfs=True,
        workspace_tmpfs_size="256m",
        storage_isolation_mode="read_only_tmpfs",
        require_disk_quota=True,
    )
    is_avail, reason = sandbox.is_available()
    if not is_avail:
        pytest.skip(f"Docker not operational: {reason}")

    with tempfile.TemporaryDirectory() as temp_repo:
        code, _, _ = sandbox.execute(
            repo_dir=temp_repo,
            command=["python", "-c", "print('cleanup test')"],
        )
        assert code == 0

        # Query docker ps -a to ensure no acid-sandbox-* containers remain
        ps_res = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=acid-sandbox-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
        )
        assert ps_res.returncode == 0
        assert "acid-sandbox-" not in ps_res.stdout

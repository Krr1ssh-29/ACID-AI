"""Unit tests for Docker sandbox isolation backend (agent.sandbox)."""
import subprocess
from unittest.mock import patch, MagicMock
import pytest

from agent.sandbox import (
    DockerSandbox,
    sanitize_sandbox_env,
    SandboxInfrastructureError,
    SandboxTimeoutError,
    SandboxError,
    MAX_OUTPUT_CHARS,
)


def test_sanitize_sandbox_env_defaults():
    """Verify default sanitized environment contains baseline POSIX variables."""
    env = sanitize_sandbox_env()
    assert "PATH" in env
    assert "PYTHONPATH" in env
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["LANG"] == "C.UTF-8"
    assert "GITHUB_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "GEMINI_API_KEY" not in env


def test_sanitize_sandbox_env_strips_all_secrets():
    """Verify sanitize_sandbox_env strictly strips sensitive credentials."""
    dirty_env = {
        "GITHUB_TOKEN": "dummy_gh_token",
        "ANTHROPIC_API_KEY": "dummy_anthropic_key",
        "GEMINI_API_KEY": "dummy_gemini_key",
        "AWS_SECRET_ACCESS_KEY": "dummy_aws_secret",
        "AWS_ACCESS_KEY_ID": "dummy_aws_id",
        "SSH_AUTH_SOCK": "/tmp/ssh.sock",
        "AZURE_CLIENT_SECRET": "secret_azure",
        "DATABASE_PASSWORD": "supersecretpassword",
        "MY_AUTH_TOKEN": "auth123",
        "APP_SECRET": "appsecret",
        "SAFE_ENV_VAR": "harmless_value",
        "RUN_ENV": "ci",
    }
    clean = sanitize_sandbox_env(dirty_env)

    # Privileged credentials must NOT be present
    assert "GITHUB_TOKEN" not in clean
    assert "ANTHROPIC_API_KEY" not in clean
    assert "GEMINI_API_KEY" not in clean
    assert "AWS_SECRET_ACCESS_KEY" not in clean
    assert "AWS_ACCESS_KEY_ID" not in clean
    assert "SSH_AUTH_SOCK" not in clean
    assert "AZURE_CLIENT_SECRET" not in clean
    assert "DATABASE_PASSWORD" not in clean
    assert "MY_AUTH_TOKEN" not in clean
    assert "APP_SECRET" not in clean

    # Harmless variables are preserved
    assert clean["SAFE_ENV_VAR"] == "harmless_value"
    assert clean["RUN_ENV"] == "ci"


def test_docker_sandbox_init_defaults():
    """Verify default parameters for DockerSandbox."""
    sandbox = DockerSandbox()
    assert sandbox.image == "python:3.11-slim"
    assert sandbox.memory == "2g"
    assert sandbox.cpus == "2.0"
    assert sandbox.pids_limit == 100
    assert sandbox.user == "1000:1000"


def test_build_docker_command_hardening_flags():
    """Verify that build_docker_command includes all required hardening flags."""
    sandbox = DockerSandbox(
        image="python:3.11-slim",
        memory="1g",
        cpus="1.5",
        pids_limit=50,
        user="2000:2000",
    )
    cmd = sandbox.build_docker_command(
        repo_dir="/tmp/fake_repo",
        command=["pytest", "sample-app/tests/"],
        env={"TEST_MODE": "true"},
    )

    # Check container isolation flags
    assert "docker" == cmd[0]
    assert "run" == cmd[1]
    assert "--rm" in cmd
    assert "--network" in cmd
    assert cmd[cmd.index("--network") + 1] == "none"
    assert "--cap-drop=ALL" in cmd
    assert "--security-opt=no-new-privileges" in cmd
    assert "--user" in cmd
    assert cmd[cmd.index("--user") + 1] == "2000:2000"
    assert "--memory=1g" in cmd
    assert "--cpus=1.5" in cmd
    assert "--pids-limit=50" in cmd
    assert "--tmpfs" in cmd
    assert cmd[cmd.index("--tmpfs") + 1] == "/tmp:rw,noexec,nosuid,size=100m"
    assert "-w" in cmd
    assert cmd[cmd.index("-w") + 1] == "/workspace"

    # Check volume mount
    assert "-v" in cmd
    v_idx = cmd.index("-v")
    assert cmd[v_idx + 1].endswith(":/workspace:rw")

    # Check image and command placement at the end
    assert cmd[-3] == "python:3.11-slim"
    assert cmd[-2] == "pytest"
    assert cmd[-1] == "sample-app/tests/"


def test_is_available_success():
    """Verify is_available returns True when docker info and disk quota checks succeed."""
    sandbox = DockerSandbox()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Server Version: 24.0.0", stderr="")
        with patch.object(sandbox, "check_disk_quota_enforcement", return_value=(True, "Quota enforced")):
            available, reason = sandbox.is_available()
            assert available is True
            assert "running" in reason


def test_is_available_fails_closed_when_disk_quota_unsupported():
    """Verify is_available returns False when disk quota is not enforced."""
    sandbox = DockerSandbox()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Server Version: 24.0.0", stderr="")
        with patch.object(
            sandbox, "check_disk_quota_enforcement", return_value=(False, "Overlayfs ignores storage-opt")
        ):
            available, reason = sandbox.is_available()
            assert available is False
            assert "Missing enforceable disk quota" in reason
            assert "Failing closed" in reason


def test_check_disk_quota_enforcement_enforced_when_probe_fails():
    """Verify check_disk_quota_enforcement returns True when probe write is blocked by quota (nonzero exit)."""
    sandbox = DockerSandbox()
    with patch("subprocess.run") as mock_run:
        # Exit code 1 indicates write beyond quota failed as expected
        mock_run.return_value = MagicMock(returncode=1, stderr="No space left on device")
        enforced, msg = sandbox.check_disk_quota_enforcement()
        assert enforced is True
        assert "verified" in msg


def test_check_disk_quota_enforcement_unsupported_when_probe_succeeds():
    """Verify check_disk_quota_enforcement returns False when probe write succeeds despite quota (exit code 0)."""
    sandbox = DockerSandbox()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Wrote 10MB")
        enforced, msg = sandbox.check_disk_quota_enforcement()
        assert enforced is False
        assert "does not enforce" in msg


def test_is_available_nonzero():
    """Verify is_available returns False when docker info exits nonzero."""
    sandbox = DockerSandbox()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="daemon not running")
        available, reason = sandbox.is_available()
        assert available is False
        assert "daemon not running" in reason


def test_is_available_not_found():
    """Verify is_available returns False when docker executable is missing."""
    sandbox = DockerSandbox()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        available, reason = sandbox.is_available()
        assert available is False
        assert "not found" in reason


def test_is_available_timeout():
    """Verify is_available returns False when docker info hangs."""
    sandbox = DockerSandbox()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker info", 5)):
        available, reason = sandbox.is_available()
        assert available is False
        assert "timed out" in reason


def test_execute_refuses_when_docker_unavailable():
    """CRITICAL: execute must raise SandboxInfrastructureError if Docker is unavailable.

    Candidate code must NEVER be executed on the host runner.
    """
    sandbox = DockerSandbox()
    with patch.object(sandbox, "is_available", return_value=(False, "Docker daemon unavailable")):
        with pytest.raises(SandboxInfrastructureError) as exc_info:
            sandbox.execute(
                repo_dir="/tmp/repo",
                command=["pytest"],
            )
        assert "Refusing to execute unverified candidate code on host runner" in str(exc_info.value)


def test_execute_success():
    """Verify successful command execution via docker run subprocess."""
    sandbox = DockerSandbox()
    with patch.object(sandbox, "is_available", return_value=(True, "Ready")):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="3 passed in 0.05s",
                stderr="",
            )
            exit_code, stdout, stderr = sandbox.execute(
                repo_dir="/tmp/repo",
                command=["pytest"],
            )
            assert exit_code == 0
            assert "3 passed" in stdout
            assert stderr == ""


def test_execute_timeout_raises():
    """Verify execution timeout raises SandboxTimeoutError."""
    sandbox = DockerSandbox()
    with patch.object(sandbox, "is_available", return_value=(True, "Ready")):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker run", 10)):
            with pytest.raises(SandboxTimeoutError) as exc_info:
                sandbox.execute(
                    repo_dir="/tmp/repo",
                    command=["pytest"],
                    timeout=10,
                )
            assert "timed out after 10 seconds" in str(exc_info.value)


def test_execute_bounds_excessive_output():
    """Verify output longer than MAX_OUTPUT_CHARS is bounded to the most recent output."""
    sandbox = DockerSandbox()
    huge_stdout = "x" * (MAX_OUTPUT_CHARS + 5000)
    with patch.object(sandbox, "is_available", return_value=(True, "Ready")):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=huge_stdout,
                stderr="",
            )
            _, stdout, _ = sandbox.execute(
                repo_dir="/tmp/repo",
                command=["pytest"],
            )
            assert len(stdout) == MAX_OUTPUT_CHARS


def test_execute_generic_error_wrapped():
    """Verify unexpected subprocess exceptions are wrapped in SandboxError."""
    sandbox = DockerSandbox()
    with patch.object(sandbox, "is_available", return_value=(True, "Ready")):
        with patch("subprocess.run", side_effect=OSError("Disk failure")):
            with pytest.raises(SandboxError) as exc_info:
                sandbox.execute(
                    repo_dir="/tmp/repo",
                    command=["pytest"],
                )
            assert "Disk failure" in str(exc_info.value)


# ── Phase 3: Storage Isolation and Lifecycle Unit Tests ───────────────────────


def test_check_storage_isolation_enforcement_success():
    """Verify check_storage_isolation_enforcement returns True when probe succeeds (exit code 0)."""
    sandbox = DockerSandbox(image="cicd-sandbox:latest", read_only_rootfs=True)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        enforced, msg = sandbox.check_storage_isolation_enforcement()
        assert enforced is True
        assert "verified" in msg.lower()


def test_check_storage_isolation_enforcement_failure():
    """Verify check_storage_isolation_enforcement returns False when probe fails (exit code nonzero)."""
    sandbox = DockerSandbox(image="cicd-sandbox:latest", read_only_rootfs=True)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="Storage probe failed: ro=False", stderr="")
        enforced, msg = sandbox.check_storage_isolation_enforcement()
        assert enforced is False
        assert "not enforced" in msg.lower()


def test_build_docker_command_read_only_tmpfs():
    """Verify build_docker_command with read_only_rootfs=True emits immutable root and bounded tmpfs."""
    sandbox = DockerSandbox(
        image="cicd-sandbox:latest",
        read_only_rootfs=True,
        workspace_tmpfs_size="256m",
        storage_isolation_mode="read_only_tmpfs",
    )
    cmd = sandbox.build_docker_command(
        repo_dir="/host/disposable_dir",
        command=["pytest", "sample-app/tests/"],
        container_name="acid-sandbox-unit-test",
    )

    assert "--read-only" in cmd
    assert "--name" in cmd
    assert cmd[cmd.index("--name") + 1] == "acid-sandbox-unit-test"
    assert "--tmpfs" in cmd
    tmpfs_indices = [i for i, x in enumerate(cmd) if x == "--tmpfs"]
    tmpfs_specs = [cmd[i + 1] for i in tmpfs_indices]
    assert any("/workspace:rw" in spec and "size=256m" in spec for spec in tmpfs_specs)
    assert any("/tmp:rw" in spec for spec in tmpfs_specs)

    # Repository must be mounted read-only to /repo_ro:ro
    v_indices = [i for i, x in enumerate(cmd) if x == "-v"]
    v_specs = [cmd[i + 1] for i in v_indices]
    assert any(spec.endswith(":/repo_ro:ro") for spec in v_specs)

    # Wrapper script must copy /repo_ro to /workspace and exec command
    assert "sh" in cmd
    assert "-c" in cmd
    c_idx = cmd.index("-c")
    assert "cp -r /repo_ro/. /workspace/" in cmd[c_idx + 1]


def test_cleanup_container_calls_docker_rm():
    """Verify cleanup_container calls docker rm -f on the container name."""
    sandbox = DockerSandbox()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        sandbox.cleanup_container("acid-sandbox-1234")
        mock_run.assert_called_once_with(
            ["docker", "rm", "-f", "acid-sandbox-1234"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )


def test_cleanup_container_silently_handles_missing_container():
    """Verify cleanup_container does not raise if docker rm fails or times out."""
    sandbox = DockerSandbox()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker rm", 5)):
        # Must not raise
        sandbox.cleanup_container("acid-sandbox-missing")


def test_provision_dependencies_rejects_missing_manifest():
    """Verify provision_dependencies returns False when requirements file does not exist."""
    sandbox = DockerSandbox()
    ok, msg = sandbox.provision_dependencies(
        manifest_file="/nonexistent/requirements.txt",
    )
    assert ok is False
    assert "not found" in msg.lower()

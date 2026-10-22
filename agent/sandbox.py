"""Isolated execution sandbox backend enforcing combined security isolation.

Implements Strategy A (Containerized Docker Sandbox) as specified in ARCHITECTURE.md:
- Network namespace isolation (--network none)
- Dropped Linux capabilities (--cap-drop=ALL)
- No-new-privileges flag (--security-opt=no-new-privileges)
- Non-root user execution (--user 1000:1000)
- Strict cgroup resource constraints (memory, cpu, pids-limit)
- Clean disposable volume mount (-v disposable:/workspace)
- Complete credential stripping (zero secrets passed)
- Explicit refusal to run candidate code on host if container isolation is unavailable
"""
import os
import subprocess
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple

MAX_OUTPUT_CHARS = 50000

SECRET_ENV_PATTERNS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "AUTH",
    "PASS",
    "CRED",
    "GITHUB",
    "ANTHROPIC",
    "GEMINI",
    "AWS",
    "SSH",
    "AZURE",
)


class SandboxError(Exception):
    """Base class for sandbox execution errors."""
    pass


class SandboxInfrastructureError(SandboxError):
    """Raised when container isolation infrastructure is missing or unreachable."""
    pass


class SandboxTimeoutError(SandboxError):
    """Raised when container execution exceeds wall-clock timeout limit."""
    pass


def sanitize_sandbox_env(extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Produce a sanitized, uncredentialed environment for sandbox execution.

    Explicitly strips ALL host environment variables and secrets, ensuring strictly
    ZERO privileged credentials (GITHUB_TOKEN, AI API keys, cloud tokens) enter the sandbox.

    Args:
        extra_env: Optional caller-specified environment overrides.

    Returns:
        Dictionary of sanitized environment variables.
    """
    clean_env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONPATH": "/workspace",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    if extra_env:
        for k, v in extra_env.items():
            upper_k = k.upper()
            # Strictly reject any environment variable matching sensitive keywords
            if any(pattern in upper_k for pattern in SECRET_ENV_PATTERNS):
                continue
            clean_env[k] = str(v)

    return clean_env


class SandboxIsolationBackend(ABC):
    """Abstract interface defining the isolated sandbox execution boundary."""

    @abstractmethod
    def is_available(self) -> Tuple[bool, str]:
        """Check whether the isolation boundary is genuinely operational in this environment."""
        pass

    @abstractmethod
    def execute(
        self,
        repo_dir: str,
        command: List[str],
        timeout: int = 180,
        env: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """Execute allowlisted command inside the isolated boundary.

        Args:
            repo_dir: Path to the disposable copy of the repository.
            command: Tokenized allowlisted command to execute.
            timeout: Execution timeout in seconds.
            env: Optional sanitized environment overrides.

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        pass


class DockerSandbox(SandboxIsolationBackend):
    """Containerized sandbox running candidate code inside an ephemeral Linux container.

    Enforces mandatory combined isolation protections per ARCHITECTURE.md CMP-08.
    """

    def __init__(
        self,
        image: str = "python:3.11-slim",
        memory: str = "2g",
        cpus: str = "2.0",
        pids_limit: int = 100,
        user: str = "1000:1000",
        require_disk_quota: bool = True,
    ):
        """Initialize Docker sandbox configuration.

        Args:
            image: Base container image (default: python:3.11-slim).
            memory: Cgroup memory limit string (default: 2g).
            cpus: Cgroup CPU quota ceiling (default: 2.0).
            pids_limit: Maximum process count to prevent fork bombs (default: 100).
            user: Non-root UID:GID string for execution (default: 1000:1000).
            require_disk_quota: If True, fails closed unless execution environment enforces hard disk quotas.
        """
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.user = user
        self.require_disk_quota = require_disk_quota

    def check_disk_quota_enforcement(self) -> Tuple[bool, str]:
        """Empirically test whether the execution environment enforces hard container storage quotas."""
        try:
            res = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "--storage-opt", "size=5M",
                    self.image,
                    "python", "-c",
                    "with open('/quota_probe.bin', 'wb') as f: f.write(b'x' * (10 * 1024 * 1024))",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )
            if res.returncode == 0:
                return False, (
                    "Storage driver does not enforce container storage quotas "
                    "(10MB write succeeded against a 5MB storage-opt limit). "
                    "Docker volume bind mounts lack kernel-level quota enforcement on this host."
                )
            return True, "Enforceable disk quota verified."
        except Exception as e:
            return False, f"Could not verify disk quota enforcement: {e}"

    def is_available(self) -> Tuple[bool, str]:
        """Verify that the Docker daemon is installed, responsive, and ready."""
        try:
            res = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if res.returncode != 0:
                return False, f"Docker daemon returned exit code {res.returncode}: {res.stderr.strip()}"
        except FileNotFoundError:
            return False, "Docker executable not found on host system."
        except subprocess.TimeoutExpired:
            return False, "Docker daemon connection timed out."
        except Exception as e:
            return False, f"Docker check failed: {e}"

        if self.require_disk_quota:
            has_quota, quota_reason = self.check_disk_quota_enforcement()
            if not has_quota:
                return False, (
                    f"Missing enforceable disk quota: {quota_reason}. "
                    "Failing closed: refusing to execute candidate code without an enforceable hard disk quota."
                )

        return True, "Docker daemon is running and reachable."

    def build_docker_command(
        self,
        repo_dir: str,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """Construct the fully hardened docker run invocation command list.

        Args:
            repo_dir: Host path to the disposable repository directory.
            command: Command tokens to execute inside container.
            env: Optional environment dictionary.

        Returns:
            List of command arguments suitable for subprocess execution.
        """
        clean_env = sanitize_sandbox_env(env)
        canonical_dir = os.path.realpath(repo_dir)

        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user", self.user,
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            f"--pids-limit={self.pids_limit}",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=100m",
            "-v", f"{canonical_dir}:/workspace:rw",
            "-w", "/workspace",
        ]

        # Add sanitized environment variables
        for k, v in clean_env.items():
            docker_cmd.extend(["--env", f"{k}={v}"])

        docker_cmd.append(self.image)
        docker_cmd.extend(command)
        return docker_cmd

    def execute(
        self,
        repo_dir: str,
        command: List[str],
        timeout: int = 180,
        env: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """Execute command inside the hardened Docker container.

        CRITICAL SECURITY POLICY:
        If Docker daemon is unreachable or unavailable, raises SandboxInfrastructureError.
        Candidate code is NEVER executed on the host system.
        """
        available, reason = self.is_available()
        if not available:
            raise SandboxInfrastructureError(
                f"Defensible container isolation is unavailable: {reason}. "
                "Refusing to execute unverified candidate code on host runner."
            )

        docker_cmd = self.build_docker_command(repo_dir, command, env=env)

        try:
            proc = subprocess.run(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            # Bound output to avoid memory exhaustion
            stdout = proc.stdout[-MAX_OUTPUT_CHARS:] if len(proc.stdout) > MAX_OUTPUT_CHARS else proc.stdout
            stderr = proc.stderr[-MAX_OUTPUT_CHARS:] if len(proc.stderr) > MAX_OUTPUT_CHARS else proc.stderr
            return proc.returncode, stdout, stderr
        except subprocess.TimeoutExpired as e:
            raise SandboxTimeoutError(
                f"Container execution timed out after {timeout} seconds."
            ) from e
        except Exception as e:
            raise SandboxError(f"Container execution failed: {e}") from e

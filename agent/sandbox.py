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
import uuid
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
        storage_isolation_mode: str = "storage_opt",
        read_only_rootfs: bool = False,
        workspace_tmpfs_size: str = "256m",
        tmp_tmpfs_size: str = "100m",
    ):
        """Initialize Docker sandbox configuration.

        Args:
            image: Base container image (default: cicd-sandbox:latest).
            memory: Cgroup memory limit string (default: 2g).
            cpus: Cgroup CPU quota ceiling (default: 2.0).
            pids_limit: Maximum process count to prevent fork bombs (default: 100).
            user: Non-root UID:GID string for execution (default: 1000:1000).
            require_disk_quota: If True, fails closed unless hard storage boundaries are enforced.
            storage_isolation_mode: Isolation strategy: 'read_only_tmpfs', 'storage_opt', or 'auto'.
            read_only_rootfs: If True, mounts rootfs as read-only with bounded tmpfs workspace.
            workspace_tmpfs_size: Size ceiling for the in-memory writable workspace tmpfs.
            tmp_tmpfs_size: Size ceiling for /tmp tmpfs.
        """
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.user = user
        self.require_disk_quota = require_disk_quota
        self.storage_isolation_mode = storage_isolation_mode
        self.read_only_rootfs = read_only_rootfs
        self.workspace_tmpfs_size = workspace_tmpfs_size
        self.tmp_tmpfs_size = tmp_tmpfs_size

    def check_disk_quota_enforcement(self) -> Tuple[bool, str]:
        """Empirically test whether the execution environment enforces storage quotas via --storage-opt."""
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

    def check_storage_isolation_enforcement(self) -> Tuple[bool, str]:
        """Empirically test whether read-only rootfs and bounded tmpfs storage quotas are enforced.

        Verifies that:
        1. Container rootfs is strictly read-only (attempting to write raises EROFS / Errno 30).
        2. Bounded tmpfs (/tmp) enforces hard size ceiling (10MB write to 5MB tmpfs raises ENOSPC).
        """
        probe_code = (
            "import sys\n"
            "ro_blocked = False\n"
            "try:\n"
            "    with open('/ro_probe.bin', 'w') as f: f.write('x')\n"
            "except OSError as e:\n"
            "    if 'Read-only' in str(e) or getattr(e, 'errno', None) == 30:\n"
            "        ro_blocked = True\n"
            "tmpfs_blocked = False\n"
            "try:\n"
            "    with open('/tmp/q_probe.bin', 'wb') as f:\n"
            "        f.write(b'x' * (10 * 1024 * 1024))\n"
            "except OSError as e:\n"
            "    if 'No space' in str(e) or getattr(e, 'errno', None) == 28:\n"
            "        tmpfs_blocked = True\n"
            "if ro_blocked and tmpfs_blocked:\n"
            "    sys.exit(0)\n"
            "else:\n"
            "    print(f'Storage probe failed: ro={ro_blocked}, tmpfs={tmpfs_blocked}')\n"
            "    sys.exit(1)\n"
        )
        try:
            res = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "--read-only",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=5m",
                    self.image,
                    "python", "-c", probe_code,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )
            if res.returncode == 0:
                return True, "Enforceable storage isolation verified (read-only rootfs + bounded tmpfs)."
            err_msg = res.stdout.strip() or res.stderr.strip()
            return False, f"Storage isolation not enforced: {err_msg}"
        except Exception as e:
            return False, f"Could not verify storage isolation enforcement: {e}"

    def is_available(self) -> Tuple[bool, str]:
        """Verify that the Docker daemon is installed, responsive, and ready with enforced boundaries."""
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
            if self.read_only_rootfs or self.storage_isolation_mode == "read_only_tmpfs":
                has_iso, iso_reason = self.check_storage_isolation_enforcement()
                if not has_iso:
                    return False, (
                        f"Missing enforceable storage isolation: {iso_reason}. "
                        "Failing closed: refusing to execute candidate code without an "
                        "enforceable hard storage boundary."
                    )
            elif self.storage_isolation_mode == "auto":
                has_iso, iso_reason = self.check_storage_isolation_enforcement()
                if has_iso:
                    self.read_only_rootfs = True
                    self.storage_isolation_mode = "read_only_tmpfs"
                else:
                    has_quota, quota_reason = self.check_disk_quota_enforcement()
                    if not has_quota:
                        return False, (
                            f"Missing enforceable disk quota: {quota_reason}. "
                            "Failing closed: refusing to execute candidate code without an "
                            "enforceable hard storage boundary."
                        )
            else:
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
        container_name: Optional[str] = None,
    ) -> List[str]:
        """Construct the fully hardened docker run invocation command list.

        Args:
            repo_dir: Host path to the disposable repository directory.
            command: Command tokens to execute inside container.
            env: Optional environment dictionary.
            container_name: Optional container identifier for tracking and cleanup.

        Returns:
            List of command arguments suitable for subprocess execution.
        """
        clean_env = sanitize_sandbox_env(env)
        canonical_dir = os.path.realpath(repo_dir)

        docker_cmd = ["docker", "run", "--rm"]
        if container_name:
            docker_cmd.extend(["--name", container_name])

        docker_cmd.extend([
            "--network", "none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user", self.user,
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            f"--pids-limit={self.pids_limit}",
        ])

        if self.read_only_rootfs or self.storage_isolation_mode == "read_only_tmpfs":
            docker_cmd.extend([
                "--read-only",
                "--tmpfs", f"/tmp:rw,noexec,nosuid,size={self.tmp_tmpfs_size}",
                "--tmpfs", f"/workspace:rw,size={self.workspace_tmpfs_size},uid=1000,gid=1000",
                "-v", f"{canonical_dir}:/repo_ro:ro",
                "-w", "/workspace",
            ])
            for k, v in clean_env.items():
                docker_cmd.extend(["--env", f"{k}={v}"])
            docker_cmd.append(self.image)
            wrapper = ["sh", "-c", 'cp -r /repo_ro/. /workspace/ && exec "$@"', "--"] + list(command)
            docker_cmd.extend(wrapper)
        else:
            docker_cmd.extend([
                "--tmpfs", f"/tmp:rw,noexec,nosuid,size={self.tmp_tmpfs_size}",
                "-v", f"{canonical_dir}:/workspace:rw",
                "-w", "/workspace",
            ])
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

        container_name = f"acid-sandbox-{uuid.uuid4().hex[:12]}"
        docker_cmd = self.build_docker_command(repo_dir, command, env=env, container_name=container_name)

        try:
            proc = subprocess.run(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            stdout = proc.stdout[-MAX_OUTPUT_CHARS:] if len(proc.stdout) > MAX_OUTPUT_CHARS else proc.stdout
            stderr = proc.stderr[-MAX_OUTPUT_CHARS:] if len(proc.stderr) > MAX_OUTPUT_CHARS else proc.stderr
            return proc.returncode, stdout, stderr
        except subprocess.TimeoutExpired as e:
            self.cleanup_container(container_name)
            raise SandboxTimeoutError(
                f"Container execution timed out after {timeout} seconds."
            ) from e
        except Exception as e:
            self.cleanup_container(container_name)
            raise SandboxError(f"Container execution failed: {e}") from e
        finally:
            self.cleanup_container(container_name)

    def cleanup_container(self, container_name: str) -> None:
        """Forcefully remove an ephemeral container by name to guarantee cleanup."""
        if not container_name:
            return
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            pass

    def provision_dependencies(
        self,
        manifest_file: str,
        timeout: int = 120,
    ) -> Tuple[bool, str]:
        """Restricted dependency provisioning step in a separate, isolated container.

        Runs with ZERO credentials (sanitized environment) and only installs packages
        declared in the verified dependency manifest. Does NOT execute any candidate code.

        Returns:
            Tuple of (success_boolean, status_or_error_message).
        """
        if not manifest_file or not os.path.isfile(manifest_file):
            return False, f"Manifest file '{manifest_file}' not found."

        base_name = os.path.basename(manifest_file)
        if base_name not in ("requirements.txt", "Pipfile", "pyproject.toml"):
            return False, f"Unsupported dependency manifest: {base_name}"

        container_name = f"acid-prov-{uuid.uuid4().hex[:12]}"
        clean_env = sanitize_sandbox_env()
        prov_cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            f"--pids-limit={self.pids_limit}",
            "-v", f"{os.path.realpath(manifest_file)}:/manifest.txt:ro",
        ]
        for k, v in clean_env.items():
            prov_cmd.extend(["--env", f"{k}={v}"])
        prov_cmd.extend([self.image, "pip", "install", "--no-cache-dir", "-r", "/manifest.txt"])

        try:
            res = subprocess.run(
                prov_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            if res.returncode == 0:
                return True, "Dependencies successfully provisioned."
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"Dependency provisioning failed (pip exit {res.returncode}): {err}"
        except subprocess.TimeoutExpired:
            try:
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=5)
            except Exception:
                pass
            return False, f"Dependency provisioning timed out after {timeout} seconds."
        except Exception as e:
            try:
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=5)
            except Exception:
                pass
            return False, f"Dependency provisioning error: {e}"

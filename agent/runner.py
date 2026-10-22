"""Verification runner and self-correction loop for isolated patch verification.

Applies validated candidate patches strictly to disposable workspace directories,
enforces command allowlisting, executes within an isolated container sandbox,
and guarantees zero filesystem mutation of the user's working tree.
"""
import os
import re
import shlex
import shutil
import tempfile
from typing import List, Optional, Tuple

from agent.models import (
    AgentConfig,
    AnalysisResult,
    PatchProposal,
    PatchStatus,
    VerificationResult,
    VerificationStatus,
)
from agent.providers import BaseAIProvider
from agent.patcher import generate_patch
from agent.sandbox import (
    SandboxIsolationBackend,
    DockerSandbox,
    SandboxTimeoutError,
    SandboxError,
)
from agent.validator import _extract_hunks

MAX_COMBINED_OUTPUT_CHARS = 50000
MAX_WORKSPACE_DISK_BYTES = 500 * 1024 * 1024  # 500 MB workspace ceiling

ALLOWLISTED_EXECUTABLES = {
    "pytest",
    "flake8",
}

SAFE_PYTEST_OPTIONS = {
    "-v",
    "-vv",
    "-q",
    "-qq",
    "-s",
    "-x",
    "--exitfirst",
    "--verbose",
    "--quiet",
    "--disable-warnings",
}

SAFE_PYTEST_PREFIX_OPTIONS = (
    "--tb=",
    "--color=",
)

SAFE_FLAKE8_OPTIONS = {
    "-v",
    "-q",
    "--verbose",
    "--quiet",
    "--show-source",
}

SAFE_FLAKE8_PREFIX_OPTIONS = (
    "--max-line-length=",
    "--select=",
    "--ignore=",
)

SAFE_TARGET_DIR_PREFIXES = (
    "sample-app",
    "sample_app",
    "tests",
    "test",
    "src",
    "app",
    "lib",
    "agent",
)

DANGEROUS_SHELL_PATTERNS = [
    r";",
    r"&&",
    r"\|\|",
    r"\|",
    r">",
    r"<",
    r"`",
    r"\$\(",
    r"\${",
    r"\beval\b",
    r"\bexec\b",
    r"\bsh\b",
    r"\bbash\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bnc\b",
]

IGNORED_COPY_PATTERNS = shutil.ignore_patterns(
    ".git",
    ".git*",
    ".venv*",
    "venv*",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".env*",
    "*.key",
    "*.pem",
    "id_rsa*",
)


def get_dir_size_bytes(dir_path: str) -> int:
    """Calculate the total size in bytes of all files within a directory tree."""
    total = 0
    try:
        for root, _, files in os.walk(dir_path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except OSError:
        pass
    return total


def is_command_allowlisted(command_str: str) -> bool:
    """Verify that a verification command matches pre-approved test/lint executables and arguments.

    Enforces strict executable and option allowlisting. Rejects pytest plugins, configuration
    overrides, arbitrary file paths, shell syntax, subshells, and unapproved tools.

    Args:
        command_str: Single command string (e.g. 'pytest sample-app/tests/').

    Returns:
        True if command is safely allowlisted, False otherwise.
    """
    clean = command_str.strip()
    if not clean:
        return False

    # 1. Deny shell injection metacharacters
    for danger in DANGEROUS_SHELL_PATTERNS:
        if re.search(danger, clean):
            return False

    # 2. Tokenize command safely
    try:
        tokens = shlex.split(clean)
    except Exception:
        return False

    if not tokens:
        return False

    # 3. Parse executable and trailing arguments
    if tokens[0] in ("python", "python3"):
        if len(tokens) >= 3 and tokens[1] == "-m" and tokens[2] in ALLOWLISTED_EXECUTABLES:
            exe = tokens[2]
            args = tokens[3:]
        else:
            return False
    elif tokens[0] in ALLOWLISTED_EXECUTABLES:
        exe = tokens[0]
        args = tokens[1:]
    else:
        return False

    # 4. Strictly validate each argument
    for arg in args:
        if arg.startswith("-"):
            if exe == "pytest":
                if arg in SAFE_PYTEST_OPTIONS:
                    continue
                if any(arg.startswith(prefix) for prefix in SAFE_PYTEST_PREFIX_OPTIONS):
                    continue
                # Explicitly reject plugin, config, and arbitrary flags
                return False
            elif exe == "flake8":
                if arg in SAFE_FLAKE8_OPTIONS:
                    continue
                if any(arg.startswith(prefix) for prefix in SAFE_FLAKE8_PREFIX_OPTIONS):
                    continue
                return False
            else:
                return False
        else:
            # Positional path validation: must not be absolute or traverse
            if arg.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", arg):
                return False
            if ".." in arg:
                return False
            norm = arg.replace("\\", "/").strip("./")
            if norm == "":
                continue
            if not any(norm.startswith(prefix) for prefix in SAFE_TARGET_DIR_PREFIXES):
                return False

    return True


def copy_disposable_repo(source_root: str, target_dir: str) -> None:
    """Copy repository files into an ephemeral workspace, excluding git and sensitive files.

    Args:
        source_root: Path to the clean source repository root.
        target_dir: Disposable temporary destination directory.
    """
    for item in os.listdir(source_root):
        s_item = os.path.join(source_root, item)
        d_item = os.path.join(target_dir, item)

        # Skip ignored files and folders
        if item.startswith((".git", ".env", ".venv", "venv")) or item in ("__pycache__", ".pytest_cache"):
            continue

        if os.path.isdir(s_item):
            shutil.copytree(s_item, d_item, ignore=IGNORED_COPY_PATTERNS, dirs_exist_ok=True)
        else:
            shutil.copy2(s_item, d_item)


def apply_patch_to_disposable_tree(
    target_dir: str,
    patch: PatchProposal,
) -> Tuple[bool, str]:
    """Apply candidate patch modifications strictly to files within the disposable workspace.

    Args:
        target_dir: Path to the disposable copy of the repository.
        patch: Validated PatchProposal containing file modifications.

    Returns:
        Tuple of (success_boolean, error_message).
    """
    for fp in patch.files:
        full_path = os.path.join(target_dir, fp.path)

        if fp.status == "added":
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            # Reconstruct added file content from + lines in diff
            added_lines = []
            for line in fp.diff_content.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    added_lines.append(line[1:])
            try:
                with open(full_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write("\n".join(added_lines) + ("\n" if added_lines else ""))
            except OSError as e:
                return False, f"Could not create file '{fp.path}': {e}"
            continue

        if fp.status == "modified":
            if not os.path.isfile(full_path):
                return False, f"Target file '{fp.path}' not found in disposable copy."

            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    current_lines = f.read().splitlines()
            except OSError as e:
                return False, f"Could not read target file '{fp.path}': {e}"

            hunks = _extract_hunks(fp.diff_content)
            modified_lines = list(current_lines)

            # Apply hunks
            for orig_start, orig_count, hunk_lines in hunks:
                expected_orig = [hl[1:] for hl in hunk_lines if hl.startswith((" ", "-"))]
                replacement = [hl[1:] for hl in hunk_lines if hl.startswith((" ", "+"))]

                start_idx = max(0, orig_start - 1)
                matched_idx = None

                # Exact match
                if modified_lines[start_idx: start_idx + len(expected_orig)] == expected_orig:
                    matched_idx = start_idx
                else:
                    # Scan for matching context lines
                    for idx in range(max(0, len(modified_lines) - len(expected_orig) + 1)):
                        if modified_lines[idx: idx + len(expected_orig)] == expected_orig:
                            matched_idx = idx
                            break

                if matched_idx is None:
                    return False, f"Hunk context at line {orig_start} in '{fp.path}' failed to match."

                # Splice replacement
                modified_lines[matched_idx: matched_idx + len(expected_orig)] = replacement

            try:
                with open(full_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write("\n".join(modified_lines) + "\n")
            except OSError as e:
                return False, f"Could not write patched content to '{fp.path}': {e}"

    return True, ""


class VerificationRunner:
    """Coordinates isolated test suite execution and verification outcome determination."""

    def __init__(
        self,
        sandbox: Optional[SandboxIsolationBackend] = None,
        config: Optional[AgentConfig] = None,
        repo_root: Optional[str] = None,
    ):
        """Initialize runner with sandbox isolation backend and repository context."""
        from agent.config import load_config
        self.config = config or load_config()
        self.sandbox = sandbox or DockerSandbox(
            image=self.config.sandbox_image,
            memory=self.config.sandbox_memory_limit,
            cpus=self.config.sandbox_cpu_limit,
            pids_limit=self.config.sandbox_pids_limit,
        )
        self.repo_root = repo_root or "."

    def verify(
        self,
        patch: PatchProposal,
        commands: Optional[List[str]] = None,
        attempt: int = 1,
    ) -> VerificationResult:
        """Execute candidate patch verification inside the isolated sandbox.

        CRITICAL SAFETY ASSURANCES:
        1. Never modifies the user's working tree in self.repo_root.
        2. Executes ONLY allowlisted commands inside the isolation boundary.
        3. Never marks a patch verified unless all checks exit with code 0 inside the sandbox.
        4. Guarantees ephemeral directory destruction upon completion or failure.

        Args:
            patch: Candidate PatchProposal to verify.
            commands: Optional list of verification commands (defaults to config).
            attempt: Current attempt number in self-correction loop.

        Returns:
            Truthful VerificationResult model.
        """
        # 1. Reject unvalidated or rejected patch proposals immediately
        if patch.status != PatchStatus.VALIDATED or not patch.validation or not patch.validation.is_valid:
            return VerificationResult(
                status=VerificationStatus.PATCH_REJECTED,
                is_verified=False,
                exit_code=1,
                error_message="Cannot verify patch: failed safety policy validation.",
                attempt=attempt,
            )

        # 2. Check sandbox availability before touching anything
        is_avail, avail_reason = self.sandbox.is_available()
        if not is_avail:
            return VerificationResult(
                status=VerificationStatus.INFRASTRUCTURE_FAILURE,
                is_verified=False,
                exit_code=1,
                error_message=(
                    f"Sandbox container isolation is unavailable: {avail_reason}. "
                    "Refusing to execute unverified code on host runner."
                ),
                attempt=attempt,
            )

        cmd_list = commands or self.config.verification_commands
        executed_cmds: List[str] = []
        captured_output: List[str] = []

        # 3. Create disposable workspace
        with tempfile.TemporaryDirectory() as disposable_dir:
            try:
                copy_disposable_repo(self.repo_root, disposable_dir)
            except Exception as e:
                return VerificationResult(
                    status=VerificationStatus.INFRASTRUCTURE_FAILURE,
                    is_verified=False,
                    exit_code=1,
                    error_message=f"Failed to prepare disposable repository copy: {e}",
                    attempt=attempt,
                )

            # 4. Apply patch to disposable copy
            apply_ok, apply_err = apply_patch_to_disposable_tree(disposable_dir, patch)
            if not apply_ok:
                return VerificationResult(
                    status=VerificationStatus.PATCH_REJECTED,
                    is_verified=False,
                    exit_code=1,
                    error_message=f"Failed to apply patch to isolated workspace: {apply_err}",
                    attempt=attempt,
                )

            # Check workspace disk usage ceiling before execution
            if get_dir_size_bytes(disposable_dir) > MAX_WORKSPACE_DISK_BYTES:
                return VerificationResult(
                    status=VerificationStatus.INFRASTRUCTURE_FAILURE,
                    is_verified=False,
                    exit_code=1,
                    error_message=(
                        f"Disposable workspace exceeded disk quota ceiling ({MAX_WORKSPACE_DISK_BYTES} bytes)."
                    ),
                    attempt=attempt,
                )

            # 5. Execute allowlisted verification commands inside sandbox
            for cmd_str in cmd_list:
                if not is_command_allowlisted(cmd_str):
                    return VerificationResult(
                        status=VerificationStatus.INFRASTRUCTURE_FAILURE,
                        is_verified=False,
                        exit_code=1,
                        executed_commands=executed_cmds,
                        error_message=(
                            f"Command '{cmd_str}' is forbidden; not in strict verification allowlist."
                        ),
                        attempt=attempt,
                    )

                cmd_tokens = shlex.split(cmd_str)
                executed_cmds.append(cmd_str)

                try:
                    exit_code, stdout, stderr = self.sandbox.execute(
                        repo_dir=disposable_dir,
                        command=cmd_tokens,
                        timeout=self.config.verification_timeout_seconds,
                    )
                except SandboxTimeoutError as e:
                    return VerificationResult(
                        status=VerificationStatus.TIMEOUT,
                        is_verified=False,
                        exit_code=124,
                        executed_commands=executed_cmds,
                        output="\n".join(captured_output),
                        error_message=str(e),
                        attempt=attempt,
                    )
                except SandboxError as e:
                    return VerificationResult(
                        status=VerificationStatus.INFRASTRUCTURE_FAILURE,
                        is_verified=False,
                        exit_code=1,
                        executed_commands=executed_cmds,
                        output="\n".join(captured_output),
                        error_message=str(e),
                        attempt=attempt,
                    )

                cmd_out = f"=== RUN: {cmd_str} (exit {exit_code}) ===\n"
                if stdout:
                    cmd_out += f"STDOUT:\n{stdout}\n"
                if stderr:
                    cmd_out += f"STDERR:\n{stderr}\n"
                captured_output.append(cmd_out)

                # Check workspace disk usage ceiling after command execution
                if get_dir_size_bytes(disposable_dir) > MAX_WORKSPACE_DISK_BYTES:
                    return VerificationResult(
                        status=VerificationStatus.INFRASTRUCTURE_FAILURE,
                        is_verified=False,
                        exit_code=1,
                        executed_commands=executed_cmds,
                        output="\n".join(captured_output),
                        error_message=(
                            f"Command '{cmd_str}' caused workspace to exceed disk quota ceiling "
                            f"({MAX_WORKSPACE_DISK_BYTES} bytes)."
                        ),
                        attempt=attempt,
                    )

                if exit_code != 0:
                    combined_out = "\n".join(captured_output)
                    bounded_out = combined_out[-MAX_COMBINED_OUTPUT_CHARS:]
                    return VerificationResult(
                        status=VerificationStatus.TEST_FAILED,
                        is_verified=False,
                        exit_code=exit_code,
                        executed_commands=executed_cmds,
                        output=bounded_out,
                        error_message=f"Verification command '{cmd_str}' failed with exit code {exit_code}.",
                        attempt=attempt,
                    )

        # All commands succeeded with exit code 0
        combined_out = "\n".join(captured_output)
        bounded_out = combined_out[-MAX_COMBINED_OUTPUT_CHARS:]
        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            is_verified=True,
            exit_code=0,
            executed_commands=executed_cmds,
            output=bounded_out,
            error_message=None,
            attempt=attempt,
        )


def run_repair_loop(
    diagnosis: AnalysisResult,
    repo_root: str,
    config: Optional[AgentConfig] = None,
    sandbox: Optional[SandboxIsolationBackend] = None,
    provider: Optional[BaseAIProvider] = None,
    commands: Optional[List[str]] = None,
) -> Tuple[PatchProposal, VerificationResult]:
    """Execute the bounded 2-attempt self-correction repair loop.

    Attempt 1:
      1. Generates candidate patch from structured diagnosis.
      2. Validates patch safety policies.
      3. Verifies patch execution inside container sandbox.
      4. If exit code 0: returns verified patch.
    Attempt 2 (Self-Correction):
      If Attempt 1 verification failed, feeds failure output back to AI model
      for one bounded correction attempt before clean termination.

    Args:
        diagnosis: Phase 03 structured AnalysisResult.
        repo_root: Root directory of target repository.
        config: Optional AgentConfig instance.
        sandbox: Optional sandbox isolation backend.
        provider: Optional AI provider backend.
        commands: Optional verification command overrides.

    Returns:
        Tuple of (final_patch_proposal, final_verification_result).
    """
    runner = VerificationRunner(sandbox=sandbox, config=config, repo_root=repo_root)

    # --- Attempt 1 ---
    patch_1 = generate_patch(
        diagnosis=diagnosis,
        config=config,
        provider=provider,
        repo_root=repo_root,
    )

    verif_1 = runner.verify(patch_1, commands=commands, attempt=1)
    if verif_1.is_verified:
        return patch_1, verif_1

    # If patch was rejected by policy or infrastructure failed, do not retry blindly
    if verif_1.status in (VerificationStatus.PATCH_REJECTED, VerificationStatus.INFRASTRUCTURE_FAILURE):
        return patch_1, verif_1

    # --- Attempt 2: Self-Correction with verification feedback ---
    failure_feedback = (
        f"Attempt 1 patch verification failed with output:\n{verif_1.output[-3000:]}\n"
        f"Error: {verif_1.error_message}"
    )

    patch_2 = generate_patch(
        diagnosis=diagnosis,
        config=config,
        provider=provider,
        repo_root=repo_root,
        source_snippets=failure_feedback,
    )

    verif_2 = runner.verify(patch_2, commands=commands, attempt=2)
    return patch_2, verif_2

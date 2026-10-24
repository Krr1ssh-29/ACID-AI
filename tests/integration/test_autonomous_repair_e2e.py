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


def test_e2e_real_sandbox_verified_success_enables_draft_pr_publication():
    """Verify that a candidate patch genuinely verified in a live Docker sandbox unlocks Draft PR publication."""
    from unittest.mock import patch
    from agent.models import PublishStatus
    from agent.publisher import publish_repair_pr, RECURSION_TAG

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
            max_repair_attempts=2,
            enable_repair_pr=True,
            github_token="ghp_test_token_1234567890",
            repo_name="org/repo",
            run_id="9999",
            base_branch="main",
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        )

        final_patch, final_result = run_repair_loop(
            diagnosis=diagnosis,
            repo_root=host_repo,
            sandbox=sandbox,
            provider=mock_provider,
            config=cfg,
            commands=["pytest sample-app/test_target.py"],
        )

        # Confirm genuine sandbox verification
        assert final_result.status == VerificationStatus.VERIFIED
        assert final_result.is_verified is True
        assert final_result.exit_code == 0

        # Test Phase 06 publication with mocked GitHub responses
        def mock_github_api(url, *args, **kwargs):
            mock_resp = MagicMock()
            if "git/ref/heads/agent/fix" in url:
                mock_resp.status_code = 404
            elif "git/ref/heads/main" in url:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"object": {"sha": "base_commit_sha"}}
            elif "git/commits/base_commit_sha" in url:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"tree": {"sha": "base_tree_sha"}}
            elif "git/trees" in url:
                mock_resp.status_code = 201
                mock_resp.json.return_value = {"sha": "new_tree_sha"}
            elif "git/commits" in url:
                mock_resp.status_code = 201
                mock_resp.json.return_value = {"sha": "new_commit_sha"}
            elif "git/refs" in url:
                mock_resp.status_code = 201
                mock_resp.json.return_value = {"ref": "refs/heads/agent/fix-test-9999"}
            elif "pulls" in url:
                mock_resp.status_code = 201
                mock_resp.json.return_value = {
                    "number": 105,
                    "html_url": "https://github.com/org/repo/pull/105",
                    "draft": True,
                }
            else:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {}
            return mock_resp

        with patch("requests.get", side_effect=mock_github_api), \
             patch("requests.post", side_effect=mock_github_api) as mock_post:
            pub_result = publish_repair_pr(
                patch=final_patch,
                verification=final_result,
                diagnosis=diagnosis.model_dump(),
                config=cfg,
                repo_root=host_repo,
            )

        assert pub_result.status == PublishStatus.PUBLISHED
        assert pub_result.pr_number == 105
        assert pub_result.is_draft is True
        assert "agent/fix-test-9999" in pub_result.branch_name

        # Verify anti-recursion tag was injected into commit payload
        commit_calls = [c for c in mock_post.call_args_list if "git/commits" in c[0][0]]
        assert len(commit_calls) == 1
        commit_payload = commit_calls[0][1]["json"]
        assert RECURSION_TAG in commit_payload["message"]

        # Verify draft flag in PR payload
        pr_calls = [c for c in mock_post.call_args_list if "pulls" in c[0][0]]
        assert len(pr_calls) == 1
        pr_payload = pr_calls[0][1]["json"]
        assert pr_payload["draft"] is True
        assert RECURSION_TAG in pr_payload["title"]


def test_e2e_real_sandbox_verification_failure_strictly_blocks_publication():
    """Verify that a patch that fails in the live container cannot be published as a Draft PR."""
    from unittest.mock import patch
    from agent.models import PublishStatus
    from agent.publisher import publish_repair_pr

    sandbox = get_live_sandbox()

    diagnosis = AnalysisResult(
        severity="high",
        failure_types=["test"],
        root_cause="AssertionError in test_target: expected 2, got 3",
        fixes=[FixSuggestion(type="test", title="Fix assertion", description="Change 3 to 2")],
        confidence="high",
    )

    # Patch that still fails inside the container
    diff_broken = (
        "--- a/sample-app/test_target.py\n"
        "+++ b/sample-app/test_target.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def test_addition():\n"
        "-    assert 1 + 1 == 3\n"
        "+    assert 1 + 1 == 77\n"
    )
    patch_json = '{"explanation": "Still broken", "diff": "' + diff_broken.replace('\n', '\\n') + '"}'

    mock_provider = MagicMock()
    mock_provider.generate_text.return_value = patch_json

    with tempfile.TemporaryDirectory() as host_repo:
        os.makedirs(os.path.join(host_repo, "sample-app"), exist_ok=True)
        test_file = os.path.join(host_repo, "sample-app", "test_target.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def test_addition():\n    assert 1 + 1 == 3\n")

        cfg = AgentConfig(
            verification_commands=["pytest sample-app/test_target.py"],
            max_repair_attempts=1,
            enable_repair_pr=True,
            github_token="ghp_test_token_1234567890",
            repo_name="org/repo",
            run_id="9999",
            base_branch="main",
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        )

        final_patch, final_result = run_repair_loop(
            diagnosis=diagnosis,
            repo_root=host_repo,
            sandbox=sandbox,
            provider=mock_provider,
            config=cfg,
            commands=["pytest sample-app/test_target.py"],
        )

        # Confirm verification failed inside the container
        assert final_result.status == VerificationStatus.TEST_FAILED
        assert final_result.is_verified is False
        assert final_result.exit_code != 0

        # Attempt to publish: must be refused
        with patch("requests.post") as mock_post:
            pub_result = publish_repair_pr(
                patch=final_patch,
                verification=final_result,
                diagnosis=diagnosis.model_dump(),
                config=cfg,
                repo_root=host_repo,
            )

        assert pub_result.status == PublishStatus.SKIPPED_UNVERIFIED
        assert "Refusing to publish repair PR" in pub_result.message
        mock_post.assert_not_called()

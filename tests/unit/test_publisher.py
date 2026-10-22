"""Unit tests for GitHub repair integration and Draft PR publisher in agent.publisher."""
import requests
from unittest.mock import MagicMock, patch
from agent.models import (
    AgentConfig,
    PatchProposal,
    PatchStatus,
    FilePatch,
    PatchValidationResult,
    VerificationResult,
    VerificationStatus,
    PublishStatus,
)
from agent.publisher import (
    sanitize_branch_slug,
    is_recursive_trigger,
    format_repair_pr_title,
    format_repair_pr_body,
    publish_repair_pr,
    get_patched_file_content,
    handle_fork_fallback,
    RECURSION_TAG,
)


def _make_valid_patch() -> PatchProposal:
    """Helper to construct a validated PatchProposal model."""
    diff_text = (
        "--- a/sample-app/app.py\n"
        "+++ b/sample-app/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-def old_func():\n"
        "+def new_func():\n"
        "     return True\n"
    )
    fp = FilePatch(
        path="sample-app/app.py",
        diff_content=diff_text,
        status="modified",
        additions=1,
        deletions=1,
        hunks_count=1,
    )
    return PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Update function name to new_func",
        diff=diff_text,
        files=[fp],
        validation=PatchValidationResult(is_valid=True),
        is_verified=True,
    )


def _make_verified_result() -> VerificationResult:
    """Helper to construct a passing VerificationResult model."""
    return VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
        executed_commands=["pytest sample-app/tests/", "flake8 sample-app/"],
        output="=== RUN: pytest (exit 0) ===\n3 passed in 0.4s",
        error_message=None,
    )


# ── 1. Unit Tests for Helpers ─────────────────────────────────────


def test_sanitize_branch_slug():
    """Verify branch slug sanitization removes illegal characters and limits length."""
    assert sanitize_branch_slug("test_failure") == "test_failure"
    assert sanitize_branch_slug("Lint: E501 line-too-long!") == "lint-e501-line-too-long"
    assert sanitize_branch_slug("feature/foo..bar@{}") == "feature-foo-bar"
    assert sanitize_branch_slug("") == "repair"
    assert sanitize_branch_slug(None) == "repair"
    assert len(sanitize_branch_slug("a" * 100)) <= 30


def test_is_recursive_trigger_bot_actors():
    """Verify bot actors are detected as recursive triggers."""
    cfg_bot = AgentConfig(github_actor="github-actions[bot]")
    assert is_recursive_trigger(cfg_bot) is True

    cfg_other_bot = AgentConfig(github_actor="dependabot[bot]")
    assert is_recursive_trigger(cfg_other_bot) is True

    cfg_user = AgentConfig(github_actor="octocat")
    assert is_recursive_trigger(cfg_user) is False


def test_is_recursive_trigger_commit_message(tmp_path):
    """Verify commit message inspection detects anti-recursion tag."""
    cfg = AgentConfig(commit_sha="abcdef123456")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=f"fix: repair bug {RECURSION_TAG}")
        # Pass tmp_path as repo_root with mock .git
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        assert is_recursive_trigger(cfg, repo_root=str(tmp_path)) is True

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="feat: regular feature commit")
        assert is_recursive_trigger(cfg, repo_root=str(tmp_path)) is False


def test_format_repair_pr_title():
    """Verify Draft PR title includes anti-recursion tag."""
    title = format_repair_pr_title("test", "98765")
    assert title == "[ai-agent-repair] Fix test failure in run #98765"


def test_format_repair_pr_body_contents():
    """Verify PR description contains diagnosed failure, fix, and actual verification evidence."""
    patch = _make_valid_patch()
    verif = _make_verified_result()
    diag = {
        "failure_types": ["test"],
        "root_cause": "AssertionError: expected True got False in test_app.py",
    }
    cfg = AgentConfig(repo_name="owner/repo", run_id="12345", commit_sha="abc12345")

    body = format_repair_pr_body(diag, patch, verif, cfg)

    # Diagnosed failure
    assert "[12345](https://github.com/owner/repo/actions/runs/12345)" in body
    assert "AssertionError: expected True got False" in body
    assert "`test`" in body

    # Proposed fix
    assert "Update function name to new_func" in body
    assert "sample-app/app.py" in body
    assert "```diff" in body

    # Verification evidence
    assert "`VERIFIED`" in body or "`VERIFIED_SUCCESS`" in body
    assert "`0`" in body
    assert "pytest sample-app/tests/" in body
    assert "3 passed in 0.4s" in body

    # Anti-recursion tag and Draft notice
    assert RECURSION_TAG in body
    assert "Draft Pull Request Notice" in body
    assert "Passing verification proves ONLY that the executed test suite returned exit code 0" in body


def test_get_patched_file_content_added():
    """Verify added file content is reconstructed accurately."""
    diff = "--- /dev/null\n+++ b/new_file.py\n@@ -0,0 +1,2 @@\n+print('hello')\n+x = 1\n"
    fp = FilePatch(path="new_file.py", diff_content=diff, status="added")
    content = get_patched_file_content(fp)
    assert content == "print('hello')\nx = 1\n"


def test_get_patched_file_content_modified(tmp_path):
    """Verify modified file hunks are applied in-memory without host mutation."""
    original = "line 1\ndef old_func():\n    return False\nline 4\n"
    target_file = tmp_path / "app.py"
    target_file.write_text(original, encoding="utf-8")

    diff = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -2,2 +2,2 @@\n"
        "-def old_func():\n"
        "-    return False\n"
        "+def new_func():\n"
        "+    return True\n"
    )
    fp = FilePatch(path="app.py", diff_content=diff, status="modified")
    new_content = get_patched_file_content(fp, repo_root=str(tmp_path))

    assert "def new_func():" in new_content
    assert "return True" in new_content
    # Crucial: verify host file on disk remained completely untouched
    assert target_file.read_text(encoding="utf-8") == original


# ── 2. Critical Policy Gate Tests ─────────────────────────────────


def test_publish_repair_pr_refuses_when_verification_is_infrastructure_failure():
    """CRITICAL POLICY: Refuse to publish repair PR when verification failed due to disk quotas / infra.

    In the current environment, disk-quota enforcement blocks candidate execution and returns
    INFRASTRUCTURE_FAILURE. Ensure this condition CANNOT produce a published PR.
    """
    patch = _make_valid_patch()
    verif = VerificationResult(
        status=VerificationStatus.INFRASTRUCTURE_FAILURE,
        is_verified=False,
        exit_code=1,
        error_message="Missing enforceable disk quota: failing closed.",
    )
    diag = {"failure_types": ["test"], "root_cause": "Test failure"}
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", run_id="100")

    result = publish_repair_pr(patch, verif, diag, cfg)

    assert result.status == PublishStatus.SKIPPED_UNVERIFIED
    assert "Refusing to publish repair PR" in result.message
    assert "infrastructure_failure" in result.message
    assert result.pr_number is None
    assert result.branch_name is None


def test_publish_repair_pr_refuses_when_test_failed():
    """CRITICAL POLICY: Refuse to publish repair PR when test suite failed."""
    patch = _make_valid_patch()
    verif = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        exit_code=1,
        error_message="pytest failed with exit code 1",
    )
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", run_id="101")

    result = publish_repair_pr(patch, verif, diag, cfg)
    assert result.status == PublishStatus.SKIPPED_UNVERIFIED
    assert "Refusing to publish repair PR" in result.message


def test_publish_repair_pr_refuses_when_timeout():
    """CRITICAL POLICY: Refuse to publish repair PR when verification timed out."""
    patch = _make_valid_patch()
    verif = VerificationResult(
        status=VerificationStatus.TIMEOUT,
        is_verified=False,
        exit_code=124,
        error_message="Sandbox timeout after 180s",
    )
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", run_id="102")

    result = publish_repair_pr(patch, verif, diag, cfg)
    assert result.status == PublishStatus.SKIPPED_UNVERIFIED


def test_publish_repair_pr_refuses_unvalidated_or_rejected_patch():
    """Refuse to publish repair PR when patch was rejected by safety policy."""
    patch = PatchProposal(
        status=PatchStatus.REJECTED,
        explanation="Rejected patch",
        validation=PatchValidationResult(is_valid=False),
    )
    verif = _make_verified_result()
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", run_id="103")

    result = publish_repair_pr(patch, verif, diag, cfg)
    assert result.status == PublishStatus.SKIPPED_UNVERIFIED


# ── 3. Anti-Recursion Gate Tests ──────────────────────────────────


def test_publish_repair_pr_aborts_on_bot_actor():
    """Verify publish_repair_pr aborts immediately when workflow was triggered by a bot."""
    patch_obj = _make_valid_patch()
    verif = _make_verified_result()
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(
        github_token="test_github_token",
        repo_name="owner/repo",
        run_id="104",
        github_actor="github-actions[bot]",
    )

    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        result = publish_repair_pr(patch_obj, verif, diag, cfg)
        assert result.status == PublishStatus.SKIPPED_RECURSION
        assert "bot actor 'github-actions[bot]'" in result.message
        # Verify 0 GitHub API calls were made
        mock_get.assert_not_called()
        mock_post.assert_not_called()


# ── 4. Credentials & Configuration Tests ──────────────────────────


def test_publish_repair_pr_missing_credentials():
    """Verify publish_repair_pr reports PERMISSION_ERROR when token or repo is missing."""
    patch = _make_valid_patch()
    verif = _make_verified_result()
    diag = {"failure_types": ["test"]}

    # Missing token
    cfg_no_token = AgentConfig(github_token=None, repo_name="owner/repo")
    res1 = publish_repair_pr(patch, verif, diag, cfg_no_token)
    assert res1.status == PublishStatus.PERMISSION_ERROR

    # Missing repo
    cfg_no_repo = AgentConfig(github_token="test_github_token", repo_name=None)
    res2 = publish_repair_pr(patch, verif, diag, cfg_no_repo)
    assert res2.status == PublishStatus.PERMISSION_ERROR


def test_publish_repair_pr_disabled_in_config():
    """Verify publish_repair_pr returns SKIPPED_UNVERIFIED when enable_repair_pr is False."""
    patch = _make_valid_patch()
    verif = _make_verified_result()
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(
        github_token="test_github_token",
        repo_name="owner/repo",
        enable_repair_pr=False,
    )
    result = publish_repair_pr(patch, verif, diag, cfg)
    assert result.status == PublishStatus.SKIPPED_UNVERIFIED
    assert "disabled in configuration" in result.message


# ── 5. Idempotency Tests ──────────────────────────────────────────


def test_publish_repair_pr_existing_branch_and_pr():
    """Verify idempotency: existing branch and open PR returns SKIPPED_ALREADY_EXISTS."""
    patch_obj = _make_valid_patch()
    verif = _make_verified_result()
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", run_id="555")

    def mock_requests_get(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "/git/ref/heads/agent/fix-test-555" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"object": {"sha": "existing_sha"}}
            return mock_resp
        if "/pulls" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = [{"number": 42, "html_url": "https://github.com/owner/repo/pull/42"}]
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    with patch("requests.get", side_effect=mock_requests_get), patch("requests.post") as mock_post:
        result = publish_repair_pr(patch_obj, verif, diag, cfg)
        assert result.status == PublishStatus.SKIPPED_ALREADY_EXISTS
        assert result.pr_number == 42
        assert "already exists" in result.message
        # No post requests made to create branch or PR
        mock_post.assert_not_called()


# ── 6. Fork & Permission Limitation Fallback Tests ─────────────────


def test_publish_repair_pr_fork_403_on_branch_creation_triggers_fallback(tmp_path, monkeypatch):
    """Verify 403 Forbidden on branch creation triggers fork fallback and returns FORK_LIMITATION."""
    monkeypatch.chdir(tmp_path)
    patch_obj = _make_valid_patch()
    verif = _make_verified_result()
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(
        github_token="test_github_token",
        repo_name="owner/repo",
        run_id="777",
        pr_number="15",
    )

    def mock_requests_get(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "/git/ref/heads/agent/fix-test-777" in url:
            mock_resp.status_code = 404
            return mock_resp
        if "/git/ref/heads/main" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"object": {"sha": "base_commit_sha"}}
            return mock_resp
        if "/git/commits/base_commit_sha" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"tree": {"sha": "base_tree_sha"}}
            return mock_resp
        if "/contents/" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "content": "def old_func():\n    return True\n",
                "encoding": "utf-8",
            }
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    def mock_requests_post(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "/git/trees" in url:
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"sha": "new_tree_sha"}
            return mock_resp
        if "/git/commits" in url:
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"sha": "new_commit_sha"}
            return mock_resp
        if "/git/refs" in url:
            # 403 Forbidden on branch creation (e.g. fork repository)
            mock_resp.status_code = 403
            mock_resp.text = "Resource not accessible by integration"
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    with patch("requests.get", side_effect=mock_requests_get):
        with patch("requests.post", side_effect=mock_requests_post):
            with patch("agent.github.post_pr_comment") as mock_comment:
                result = publish_repair_pr(patch_obj, verif, diag, cfg)
                assert result.status == PublishStatus.FORK_LIMITATION
                assert "fork limitation" in result.message.lower()

                # Verify fallback artifact was created
                diff_file = tmp_path / "agent-patch.diff"
                assert diff_file.exists()
                assert diff_file.read_text(encoding="utf-8") == patch_obj.diff

                # Verify fallback PR comment was posted to existing PR
                mock_comment.assert_called_once()


# ── 7. Verified Success Flow: Full Draft PR Creation ──────────────


def test_publish_repair_pr_success_creates_draft_pr():
    """Verify successful creation of dedicated branch, commit, and reviewable Draft PR."""
    patch_obj = _make_valid_patch()
    verif = _make_verified_result()
    diag = {
        "failure_types": ["test"],
        "root_cause": "AssertionError in sample-app/app.py",
    }
    cfg = AgentConfig(
        github_token="test_secret_token",
        repo_name="owner/repo",
        run_id="999",
        base_branch="main",
        commit_sha="source_sha_123",
    )

    posted_payloads = {}

    def mock_requests_get(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "/git/ref/heads/agent/fix-test-999" in url:
            mock_resp.status_code = 404  # Branch does not exist yet
            return mock_resp
        if "/git/ref/heads/main" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"object": {"sha": "base_sha_abc"}}
            return mock_resp
        if "/git/commits/base_sha_abc" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"tree": {"sha": "base_tree_sha_xyz"}}
            return mock_resp
        if "/contents/" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "content": "def old_func():\n    return True\n",
                "encoding": "utf-8",
            }
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    def mock_requests_post(url, *args, **kwargs):
        mock_resp = MagicMock()
        json_data = kwargs.get("json", {})
        if "/git/trees" in url:
            posted_payloads["tree"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"sha": "new_tree_sha_1"}
            return mock_resp
        if "/git/commits" in url:
            posted_payloads["commit"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"sha": "new_commit_sha_1"}
            return mock_resp
        if "/git/refs" in url:
            posted_payloads["ref"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"ref": "refs/heads/agent/fix-test-999"}
            return mock_resp
        if "/pulls" in url:
            posted_payloads["pull"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {
                "number": 101,
                "html_url": "https://github.com/owner/repo/pull/101",
            }
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    with patch("requests.get", side_effect=mock_requests_get):
        with patch("requests.post", side_effect=mock_requests_post):
            result = publish_repair_pr(patch_obj, verif, diag, cfg)

            assert result.status == PublishStatus.PUBLISHED
            assert result.pr_number == 101
            assert result.pr_url == "https://github.com/owner/repo/pull/101"
            assert result.commit_sha == "new_commit_sha_1"
            assert result.branch_name == "agent/fix-test-999"
            assert result.is_draft is True

            # Verify commit anti-recursion tag
            assert RECURSION_TAG in posted_payloads["commit"]["message"]

            # CRITICAL VERIFICATION: verify Draft PR payload
            pr_req = posted_payloads["pull"]
            assert pr_req["draft"] is True
            assert pr_req["head"] == "agent/fix-test-999"
            assert pr_req["base"] == "main"
            assert RECURSION_TAG in pr_req["title"]
            assert RECURSION_TAG in pr_req["body"]
            assert "Draft Pull Request Notice" in pr_req["body"]
            assert "Isolated Sandbox Verification Evidence" in pr_req["body"]


# ── 8. Network and API Exception Handling ─────────────────────────


def test_publish_repair_pr_network_exception_handled():
    """Verify network exceptions return API_ERROR without raising unhandled exceptions."""
    patch_obj = _make_valid_patch()
    verif = _make_verified_result()
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", run_id="333")

    with patch("requests.get", side_effect=requests.RequestException("Connection reset")):
        result = publish_repair_pr(patch_obj, verif, diag, cfg)
        assert result.status == PublishStatus.API_ERROR
        assert "Network error" in result.message


# ── 9. Audit Fix Regression Tests ─────────────────────────────────


def test_handle_fork_fallback_disclaimer_truthfulness(tmp_path, monkeypatch):
    """Regression test 1: Fork fallback never claims verification without genuine VERIFIED_SUCCESS.

    Verifies that unverified patches state UNVERIFIED, while verified patches include
    the explicit Threat Model T-13 truthfulness disclaimer.
    """
    monkeypatch.chdir(tmp_path)
    patch_obj = _make_valid_patch()
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", pr_number="99")

    # Case A: Unverified / blocked candidate fix
    unverified = VerificationResult(
        status=VerificationStatus.INFRASTRUCTURE_FAILURE,
        is_verified=False,
        exit_code=1,
    )
    with patch("agent.github.post_pr_comment") as mock_comment:
        handle_fork_fallback(patch_obj, cfg, "403 Forbidden", verification=unverified)
        mock_comment.assert_called_once()
        comment_body = mock_comment.call_args[0][0]
        assert "UNVERIFIED CANDIDATE FIX" in comment_body
        assert "verified in an isolated sandbox" not in comment_body

    # Case B: Genuinely verified fix (VERIFIED_SUCCESS, exit code 0)
    verified = _make_verified_result()
    with patch("agent.github.post_pr_comment") as mock_comment:
        handle_fork_fallback(patch_obj, cfg, "403 Forbidden", verification=verified)
        mock_comment.assert_called_once()
        comment_body = mock_comment.call_args[0][0]
        assert "verified in an isolated sandbox with exit code 0" in comment_body
        assert "Truthful verification notice" in comment_body
        assert "Passing verification proves ONLY that the executed test suite returned exit code 0" in comment_body


def test_get_patched_file_content_unmatched_hunk_raises_value_error(tmp_path):
    """Regression test 2: In-memory hunk matching raises ValueError on unmatched content."""
    original = "line a\nline b\nline c\n"
    target_file = tmp_path / "app.py"
    target_file.write_text(original, encoding="utf-8")

    # Diff expects "def nonexistent_function():" which is NOT in original file
    mismatched_diff = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -10,2 +10,2 @@\n"
        "-def nonexistent_function():\n"
        "-    return 42\n"
        "+def new_function():\n"
        "+    return 43\n"
    )
    fp = FilePatch(path="app.py", diff_content=mismatched_diff, status="modified")

    import pytest
    with pytest.raises(ValueError, match="did not match base content"):
        get_patched_file_content(fp, repo_root=str(tmp_path))


def test_publish_repair_pr_unmatched_hunk_aborts_tree_generation():
    """Regression test 2b: Unmatched hunk aborts tree generation and never publishes partial patch."""
    patch_obj = _make_valid_patch()
    verif = _make_verified_result()
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", run_id="444")

    def mock_requests_get(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "/git/ref/heads/agent/fix-test-444" in url:
            mock_resp.status_code = 404
            return mock_resp
        if "/git/ref/heads/main" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"object": {"sha": "base_sha"}}
            return mock_resp
        if "/git/commits/base_sha" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"tree": {"sha": "base_tree_sha"}}
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    with patch("requests.get", side_effect=mock_requests_get):
        with patch("agent.publisher.get_patched_file_content", side_effect=ValueError("Hunk did not match")):
            with patch("requests.post") as mock_post:
                result = publish_repair_pr(patch_obj, verif, diag, cfg)
                assert result.status == PublishStatus.API_ERROR
                assert "Tree generation aborted due to unmatched patch hunk" in result.message
                # Asserts tree, commit, and ref posts were NOT executed
                mock_post.assert_not_called()


def test_publish_repair_pr_recovers_from_partial_publication_success():
    """Regression test 3: Safely recover from partial failure when branch exists and PR was missing."""
    patch_obj = _make_valid_patch()
    verif = _make_verified_result()
    diag = {"failure_types": ["test"], "root_cause": "Bug in app"}
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", run_id="888")

    def mock_requests_get(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "/git/ref/heads/agent/fix-test-888" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"object": {"sha": "existing_commit_sha_888"}}
            return mock_resp
        if "/pulls" in url:
            # No open PR exists yet for this branch
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
            return mock_resp
        if "/git/commits/existing_commit_sha_888" in url:
            # Commit message confirms it was created for this run ID and includes anti-recursion tag
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "message": f"fix: resolve test CI/CD failure {RECURSION_TAG}\nAutomated for run 888",
            }
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    posted_urls = []

    def mock_requests_post(url, *args, **kwargs):
        posted_urls.append(url)
        mock_resp = MagicMock()
        if "/pulls" in url:
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"number": 88, "html_url": "https://github.com/owner/repo/pull/88"}
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    with patch("requests.get", side_effect=mock_requests_get):
        with patch("requests.post", side_effect=mock_requests_post):
            result = publish_repair_pr(patch_obj, verif, diag, cfg)
            assert result.status == PublishStatus.PUBLISHED
            assert result.pr_number == 88
            assert result.commit_sha == "existing_commit_sha_888"
            assert result.is_draft is True
            assert "Recovered from partial publication" in result.message
            # Verified only /pulls was called; no tree or commit was redundantly posted
            assert len(posted_urls) == 1
            assert "/pulls" in posted_urls[0]


def test_publish_repair_pr_recovers_from_partial_publication_unvalidated_branch_fails_safely():
    """Regression test 3b: Existing branch differing from expected run/metadata is refused."""
    patch_obj = _make_valid_patch()
    verif = _make_verified_result()
    diag = {"failure_types": ["test"]}
    cfg = AgentConfig(github_token="test_github_token", repo_name="owner/repo", run_id="888")

    def mock_requests_get(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "/git/ref/heads/agent/fix-test-888" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"object": {"sha": "unrelated_commit_sha"}}
            return mock_resp
        if "/pulls" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
            return mock_resp
        if "/git/commits/unrelated_commit_sha" in url:
            # Commit is NOT authored by agent for run 888
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"message": "unrelated manual commit on branch"}
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    with patch("requests.get", side_effect=mock_requests_get):
        with patch("requests.post") as mock_post:
            result = publish_repair_pr(patch_obj, verif, diag, cfg)
            assert result.status == PublishStatus.API_ERROR
            assert "Refusing to create PR on unvalidated branch" in result.message
            mock_post.assert_not_called()

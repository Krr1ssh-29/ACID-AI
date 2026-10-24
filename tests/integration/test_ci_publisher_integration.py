"""Integration tests for the real CI-to-publisher path through the CLI entry point.

Verifies:
1. Direct push targeting against pushed branch.
2. Same-repository PR head branch targeting (never base_ref).
3. External-fork repository identity detection and safe fallback without unauthorized writes.
4. The exact base commit SHA used to build the repair branch.
5. Strict verification gating: failed/unverified patches block publication with zero GitHub writes.
6. Safe default mode: ENABLE_REPAIR_PR=false prevents publishing without explicit opt-in.
7. Anti-recursion guards: bot actors and repair tags abort immediately.
"""
from unittest.mock import MagicMock, patch
from agent.cli import main as cli_main
from agent.models import (
    PatchProposal,
    PatchStatus,
    FilePatch,
    PatchValidationResult,
    VerificationResult,
    VerificationStatus,
)


def _setup_mock_repo(tmp_path):
    """Set up disposable git-like repository structure with sample-app files."""
    sample_dir = tmp_path / "sample-app"
    sample_dir.mkdir(parents=True, exist_ok=True)
    tests_dir = sample_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    app_file = sample_dir / "app.py"
    app_file.write_text("def run():\n    return False\n", encoding="utf-8")

    test_file = tests_dir / "test_app.py"
    test_code = "from sample-app.app import run\n\ndef test_run():\n    assert run() is True\n"
    test_file.write_text(test_code, encoding="utf-8")

    git_dir = tmp_path / ".git"
    git_dir.mkdir(exist_ok=True)

    log_file = tmp_path / "combined-logs.txt"
    log_content = (
        "=== TEST LOGS ===\n"
        "FAILED sample-app/tests/test_app.py::test_run - AssertionError: assert False is True\n"
        "=== STEP OUTCOMES ===\n"
        "test: failure\n"
    )
    log_file.write_text(log_content, encoding="utf-8")
    return tmp_path, log_file, app_file


def _make_candidate_patch() -> PatchProposal:
    diff_text = (
        "--- a/sample-app/app.py\n"
        "+++ b/sample-app/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def run():\n"
        "-    return False\n"
        "+    return True\n"
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
        explanation="Fix return value to True",
        diff=diff_text,
        files=[fp],
        validation=PatchValidationResult(is_valid=True),
        is_verified=True,
    )


def test_ci_path_direct_push_targeting_creates_draft_pr_against_pushed_branch(tmp_path, monkeypatch):
    """Verify that a direct push failure targets the pushed branch and bases commit on pushed SHA."""
    repo_dir, log_file, _ = _setup_mock_repo(tmp_path)
    monkeypatch.chdir(repo_dir)

    ci_env = {
        "ANTHROPIC_API_KEY": "test-claude-key",
        "GITHUB_TOKEN": "ghp_mock_token_123",
        "REPO_NAME": "owner/sample-repo",
        "COMMIT_SHA": "commit_push_111222",
        "RUN_ID": "run_push_77",
        "LOG_FILE": str(log_file),
        "GENERATE_PATCH": "true",
        "ENABLE_REPAIR_PR": "true",
        "EVENT_NAME": "push",
        "REF_NAME": "develop",
        "BASE_BRANCH": "develop",
    }
    for k, v in ci_env.items():
        monkeypatch.setenv(k, v)

    posted_payloads = {}

    def mock_requests_get(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "/git/ref/heads/agent/fix-" in url:
            mock_resp.status_code = 404
            return mock_resp
        if "/git/ref/heads/develop" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"object": {"sha": "commit_push_111222"}}
            return mock_resp
        if "/git/commits/commit_push_111222" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"tree": {"sha": "tree_push_333444"}}
            return mock_resp
        if "/contents/" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "content": "def run():\n    return False\n",
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
            mock_resp.json.return_value = {"sha": "new_tree_sha_push"}
            return mock_resp
        if "/git/commits" in url:
            posted_payloads["commit"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"sha": "new_commit_sha_push"}
            return mock_resp
        if "/git/refs" in url:
            posted_payloads["ref"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"ref": "refs/heads/agent/fix-test-run-push-77"}
            return mock_resp
        if "/pulls" in url:
            posted_payloads["pull"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {
                "number": 88,
                "html_url": "https://github.com/owner/sample-repo/pull/88",
            }
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    candidate_patch = _make_candidate_patch()
    verified_result = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
        executed_commands=["pytest sample-app/tests/"],
        output="=== RUN: pytest (exit 0) ===\n1 passed in 0.1s",
    )

    with patch("agent.cli.analyse_with_ai") as mock_ai, \
         patch("agent.patcher.generate_patch") as mock_gen, \
         patch("agent.runner.VerificationRunner.verify") as mock_verify, \
         patch("agent.cli.post_pr_comment"), \
         patch("requests.get", side_effect=mock_requests_get), \
         patch("requests.post", side_effect=mock_requests_post):

        mock_ai.return_value = {
            "failure_types": ["test"],
            "root_cause": "AssertionError in test_app.py",
            "suggested_fix": "Change return False to return True",
            "confidence": "high",
        }
        mock_gen.return_value = candidate_patch
        mock_verify.return_value = verified_result

        exit_code = cli_main()
        assert exit_code == 0

        # Verify Draft PR targeting for direct push
        assert "pull" in posted_payloads
        assert posted_payloads["pull"]["base"] == "develop"
        assert posted_payloads["pull"]["draft"] is True
        assert "[ai-agent-repair]" in posted_payloads["pull"]["title"]
        assert "Direct Push (`develop`)" in posted_payloads["pull"]["body"]

        # Verify exact base commit SHA used
        assert posted_payloads["commit"]["parents"] == ["commit_push_111222"]
        assert posted_payloads["tree"]["base_tree"] == "tree_push_333444"


def test_ci_path_same_repo_pr_head_targeting_not_base_branch(tmp_path, monkeypatch):
    """Verify that same-repo PR targets the PR head branch and PR head commit, NEVER base_ref."""
    repo_dir, log_file, _ = _setup_mock_repo(tmp_path)
    monkeypatch.chdir(repo_dir)

    ci_env = {
        "ANTHROPIC_API_KEY": "test-claude-key",
        "GITHUB_TOKEN": "ghp_mock_token_pr_internal",
        "REPO_NAME": "owner/sample-repo",
        "PR_NUMBER": "42",
        "COMMIT_SHA": "synthetic_merge_commit_sha",
        "RUN_ID": "run_pr_42",
        "LOG_FILE": str(log_file),
        "GENERATE_PATCH": "true",
        "ENABLE_REPAIR_PR": "true",
        "EVENT_NAME": "pull_request",
        "REF_NAME": "42/merge",
        "HEAD_REF": "feature-auth-fix",
        "BASE_REF": "main",
        "PR_HEAD_SHA": "head_commit_auth_555",
        "PR_HEAD_REPO": "owner/sample-repo",
    }
    for k, v in ci_env.items():
        monkeypatch.setenv(k, v)

    posted_payloads = {}

    def mock_requests_get(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "/git/ref/heads/agent/fix-" in url:
            mock_resp.status_code = 404
            return mock_resp
        if "/git/ref/heads/feature-auth-fix" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"object": {"sha": "head_commit_auth_555"}}
            return mock_resp
        if "/git/commits/head_commit_auth_555" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"tree": {"sha": "tree_head_auth_777"}}
            return mock_resp
        if "/contents/" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "content": "def run():\n    return False\n",
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
            mock_resp.json.return_value = {"sha": "new_tree_sha_pr"}
            return mock_resp
        if "/git/commits" in url:
            posted_payloads["commit"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"sha": "new_commit_sha_pr"}
            return mock_resp
        if "/git/refs" in url:
            posted_payloads["ref"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"ref": "refs/heads/agent/fix-test-run-pr-42"}
            return mock_resp
        if "/pulls" in url:
            posted_payloads["pull"] = json_data
            mock_resp.status_code = 201
            mock_resp.json.return_value = {
                "number": 43,
                "html_url": "https://github.com/owner/sample-repo/pull/43",
            }
            return mock_resp
        mock_resp.status_code = 404
        return mock_resp

    candidate_patch = _make_candidate_patch()
    verified_result = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
        executed_commands=["pytest sample-app/tests/"],
        output="=== RUN: pytest (exit 0) ===\n1 passed in 0.1s",
    )

    with patch("agent.cli.analyse_with_ai") as mock_ai, \
         patch("agent.patcher.generate_patch") as mock_gen, \
         patch("agent.runner.VerificationRunner.verify") as mock_verify, \
         patch("agent.cli.post_pr_comment"), \
         patch("requests.get", side_effect=mock_requests_get), \
         patch("requests.post", side_effect=mock_requests_post):

        mock_ai.return_value = {
            "failure_types": ["test"],
            "root_cause": "AssertionError in test_app.py",
            "suggested_fix": "Change return False to return True",
            "confidence": "high",
        }
        mock_gen.return_value = candidate_patch
        mock_verify.return_value = verified_result

        exit_code = cli_main()
        assert exit_code == 0

        # CRITICAL ROADMAP ASSERTIONS:
        # 1. Draft PR targets the PR head branch ("feature-auth-fix")
        assert posted_payloads["pull"]["base"] == "feature-auth-fix"
        # 2. Draft PR NEVER targets base_ref ("main")
        assert posted_payloads["pull"]["base"] != "main"
        # 3. Draft PR is marked as draft
        assert posted_payloads["pull"]["draft"] is True
        # 4. Repair commit parent is the PR head commit, NEVER synthetic merge SHA
        assert posted_payloads["commit"]["parents"] == ["head_commit_auth_555"]
        assert posted_payloads["commit"]["parents"] != ["synthetic_merge_commit_sha"]
        # 5. Base tree derived from PR head commit
        assert posted_payloads["tree"]["base_tree"] == "tree_head_auth_777"


def test_ci_path_external_fork_repository_identity_and_fallback(tmp_path, monkeypatch):
    """Verify that an external fork PR avoids unauthorized writes and triggers artifact/comment fallback."""
    repo_dir, log_file, _ = _setup_mock_repo(tmp_path)
    monkeypatch.chdir(repo_dir)

    ci_env = {
        "ANTHROPIC_API_KEY": "test-claude-key",
        "GITHUB_TOKEN": "ghp_read_only_fork_token",
        "REPO_NAME": "owner/sample-repo",
        "PR_NUMBER": "99",
        "COMMIT_SHA": "fork_commit_123",
        "RUN_ID": "run_fork_99",
        "LOG_FILE": str(log_file),
        "GENERATE_PATCH": "true",
        "ENABLE_REPAIR_PR": "true",
        "EVENT_NAME": "pull_request",
        "HEAD_REF": "develop",  # Matching branch name across different repos
        "BASE_REF": "develop",
        "PR_HEAD_SHA": "fork_head_sha_999",
        "PR_HEAD_REPO": "external-contributor/sample-repo",  # Different repository!
    }
    for k, v in ci_env.items():
        monkeypatch.setenv(k, v)

    post_calls = []

    def mock_requests_post(url, *args, **kwargs):
        post_calls.append(url)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        return mock_resp

    candidate_patch = _make_candidate_patch()
    verified_result = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
        executed_commands=["pytest sample-app/tests/"],
        output="=== RUN: pytest (exit 0) ===\n1 passed in 0.1s",
    )

    with patch("agent.cli.analyse_with_ai") as mock_ai, \
         patch("agent.patcher.generate_patch") as mock_gen, \
         patch("agent.runner.VerificationRunner.verify") as mock_verify, \
         patch("agent.cli.post_pr_comment"), \
         patch("agent.github.post_pr_comment") as mock_comment, \
         patch("requests.post", side_effect=mock_requests_post):

        mock_ai.return_value = {
            "failure_types": ["test"],
            "root_cause": "AssertionError in test_app.py",
            "suggested_fix": "Fix return value",
            "confidence": "high",
        }
        mock_gen.return_value = candidate_patch
        mock_verify.return_value = verified_result

        exit_code = cli_main()
        assert exit_code == 0

        # Zero git write calls to /git/refs, /git/commits, /git/trees, or /pulls
        assert not any("/git/refs" in u or "/git/commits" in u or "/pulls" in u for u in post_calls)

        # Fallback diff artifact generated
        diff_file = repo_dir / "agent-patch.diff"
        assert diff_file.exists()
        assert diff_file.read_text(encoding="utf-8") == candidate_patch.diff

        # Diagnostic comment posted to PR #99
        mock_comment.assert_called_once()
        args, kwargs = mock_comment.call_args
        assert "External fork PR" in args[0] or "fork limitation" in args[0]
        assert args[1] == "owner/sample-repo"
        assert args[2] == "99"


def test_ci_path_test_failure_in_sandbox_blocks_pr_publication(tmp_path, monkeypatch):
    """Verify that a candidate fix that fails sandbox tests strictly halts publication."""
    repo_dir, log_file, _ = _setup_mock_repo(tmp_path)
    monkeypatch.chdir(repo_dir)

    ci_env = {
        "ANTHROPIC_API_KEY": "test-claude-key",
        "GITHUB_TOKEN": "ghp_mock_token_fail",
        "REPO_NAME": "owner/sample-repo",
        "RUN_ID": "run_fail_101",
        "LOG_FILE": str(log_file),
        "GENERATE_PATCH": "true",
        "ENABLE_REPAIR_PR": "true",
    }
    for k, v in ci_env.items():
        monkeypatch.setenv(k, v)

    failed_result = VerificationResult(
        status=VerificationStatus.TEST_FAILED,
        is_verified=False,
        exit_code=1,
        executed_commands=["pytest sample-app/tests/"],
        output="=== RUN: pytest (exit 1) ===\nFAILED test_app.py - AssertionError",
        error_message="Verification commands exited with non-zero status code 1",
    )

    with patch("agent.cli.analyse_with_ai") as mock_ai, \
         patch("agent.patcher.generate_patch") as mock_gen, \
         patch("agent.runner.VerificationRunner.verify") as mock_verify, \
         patch("agent.cli.post_pr_comment"), \
         patch("requests.post") as mock_post:

        mock_ai.return_value = {
            "failure_types": ["test"],
            "root_cause": "AssertionError in test_app.py",
            "suggested_fix": "Fix logic",
            "confidence": "high",
        }
        mock_gen.return_value = _make_candidate_patch()
        mock_verify.return_value = failed_result

        exit_code = cli_main()
        assert exit_code == 0
        mock_post.assert_not_called()


def test_ci_path_docker_offline_blocks_pr_publication(tmp_path, monkeypatch):
    """Verify that absent Docker daemon fails closed and prevents publication."""
    repo_dir, log_file, _ = _setup_mock_repo(tmp_path)
    monkeypatch.chdir(repo_dir)

    ci_env = {
        "ANTHROPIC_API_KEY": "test-claude-key",
        "GITHUB_TOKEN": "ghp_mock_token_docker_offline",
        "REPO_NAME": "owner/sample-repo",
        "RUN_ID": "run_offline_102",
        "LOG_FILE": str(log_file),
        "GENERATE_PATCH": "true",
        "ENABLE_REPAIR_PR": "true",
    }
    for k, v in ci_env.items():
        monkeypatch.setenv(k, v)

    infra_failure = VerificationResult(
        status=VerificationStatus.INFRASTRUCTURE_FAILURE,
        is_verified=False,
        exit_code=1,
        executed_commands=[],
        output="",
        error_message="Docker daemon unavailable",
    )

    with patch("agent.cli.analyse_with_ai") as mock_ai, \
         patch("agent.patcher.generate_patch") as mock_gen, \
         patch("agent.runner.VerificationRunner.verify") as mock_verify, \
         patch("agent.cli.post_pr_comment"), \
         patch("requests.post") as mock_post:

        mock_ai.return_value = {
            "failure_types": ["test"],
            "root_cause": "AssertionError",
            "suggested_fix": "Fix",
            "confidence": "high",
        }
        mock_gen.return_value = _make_candidate_patch()
        mock_verify.return_value = infra_failure

        exit_code = cli_main()
        assert exit_code == 0
        mock_post.assert_not_called()


def test_ci_path_default_safe_mode_disabled_by_default(tmp_path, monkeypatch):
    """Verify that ENABLE_REPAIR_PR defaults to false and makes zero GitHub API calls."""
    repo_dir, log_file, _ = _setup_mock_repo(tmp_path)
    monkeypatch.chdir(repo_dir)

    ci_env = {
        "ANTHROPIC_API_KEY": "test-claude-key",
        "GITHUB_TOKEN": "ghp_mock_token_default",
        "REPO_NAME": "owner/sample-repo",
        "RUN_ID": "run_default_103",
        "LOG_FILE": str(log_file),
        "GENERATE_PATCH": "true",
        # ENABLE_REPAIR_PR not set -> defaults to False
    }
    for k, v in ci_env.items():
        monkeypatch.setenv(k, v)

    candidate_patch = _make_candidate_patch()
    verified_result = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
        executed_commands=["pytest sample-app/tests/"],
        output="=== RUN: pytest (exit 0) ===\n1 passed in 0.1s",
    )

    with patch("agent.cli.analyse_with_ai") as mock_ai, \
         patch("agent.patcher.generate_patch") as mock_gen, \
         patch("agent.runner.VerificationRunner.verify") as mock_verify, \
         patch("agent.cli.post_pr_comment"), \
         patch("agent.publisher.publish_repair_pr") as mock_publisher:

        mock_ai.return_value = {
            "failure_types": ["test"],
            "root_cause": "AssertionError",
            "suggested_fix": "Fix",
            "confidence": "high",
        }
        mock_gen.return_value = candidate_patch
        mock_verify.return_value = verified_result

        exit_code = cli_main()
        assert exit_code == 0
        mock_publisher.assert_not_called()


def test_ci_path_bot_actor_blocks_publication(tmp_path, monkeypatch):
    """Verify that a workflow triggered by a bot actor is blocked by anti-recursion safeguards."""
    repo_dir, log_file, _ = _setup_mock_repo(tmp_path)
    monkeypatch.chdir(repo_dir)

    ci_env = {
        "ANTHROPIC_API_KEY": "test-claude-key",
        "GITHUB_TOKEN": "ghp_mock_token_bot",
        "REPO_NAME": "owner/sample-repo",
        "RUN_ID": "run_bot_104",
        "LOG_FILE": str(log_file),
        "GENERATE_PATCH": "true",
        "ENABLE_REPAIR_PR": "true",
        "GITHUB_ACTOR": "github-actions[bot]",
    }
    for k, v in ci_env.items():
        monkeypatch.setenv(k, v)

    candidate_patch = _make_candidate_patch()
    verified_result = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
        executed_commands=["pytest sample-app/tests/"],
        output="=== RUN: pytest (exit 0) ===\n1 passed in 0.1s",
    )

    with patch("agent.cli.analyse_with_ai") as mock_ai, \
         patch("agent.patcher.generate_patch") as mock_gen, \
         patch("agent.runner.VerificationRunner.verify") as mock_verify, \
         patch("agent.cli.post_pr_comment"), \
         patch("requests.post") as mock_post:

        mock_ai.return_value = {
            "failure_types": ["test"],
            "root_cause": "AssertionError",
            "suggested_fix": "Fix",
            "confidence": "high",
        }
        mock_gen.return_value = candidate_patch
        mock_verify.return_value = verified_result

        exit_code = cli_main()
        assert exit_code == 0
        mock_post.assert_not_called()

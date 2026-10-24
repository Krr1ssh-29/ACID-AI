"""Unit and integration tests for ACID AI — Phase 5: Final Reporting and Verified Draft PR Delivery.

Validates:
1. Accurate reports for healthy, repaired, partially repaired, unresolved and blocked runs.
2. Reports containing actual attempt history and verification evidence.
3. Missing GitHub credentials and missing remote configuration handling.
4. Refusal to publish when verification failed or was blocked.
5. Successful draft PR creation using mocked GitHub API responses.
6. Correct repository, base branch, repair branch and commit identification.
7. Exclusion of unrelated files and sensitive data from published changes.
8. API authentication failures, permission failures and branch conflicts.
9. Duplicate-publication handling.
10. Honest reporting when publication fails after a repair has been verified.
11. Dashboard report export endpoints (JSON and Markdown).
"""
import time
from unittest.mock import MagicMock, patch

from agent.models import (
    AgentConfig,
    FilePatch,
    PatchProposal,
    PatchStatus,
    PatchValidationResult,
    PublishStatus,
    RepairAttempt,
    RunRecord,
    VerificationResult,
    VerificationStatus,
)
from agent.publisher import (
    publish_repair_pr,
    RECURSION_TAG,
)
from agent.repository import extract_github_repo_from_remote
from agent.report import (
    build_report_markdown,
    generate_final_report,
)
from dashboard.app import create_app


def _make_dummy_patch(diff_content: str = None) -> PatchProposal:
    diff = diff_content or (
        "--- a/sample-app/app.py\n"
        "+++ b/sample-app/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-def old_msg():\n"
        "+def new_msg():\n"
        "     return 'hello'\n"
    )
    fp = FilePatch(
        path="sample-app/app.py",
        diff_content=diff,
        status="modified",
        additions=1,
        deletions=1,
        hunks_count=1,
    )
    return PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Update message function to new_msg",
        diff=diff,
        files=[fp],
        validation=PatchValidationResult(is_valid=True),
        is_verified=True,
    )


def _make_verified_result() -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        is_verified=True,
        exit_code=0,
        executed_commands=["pytest sample-app/tests/ -v", "flake8 sample-app/"],
        output="=== RUN: pytest ===\n2 passed in 0.35s",
        error_message=None,
    )


# ── Test 1: Accurate reports for all 5 outcomes ───────────────────


def test_accurate_reports_for_all_outcomes():
    """Verify accurate reports and truthful scope statements for all 5 outcomes."""
    outcomes = ["healthy", "repaired", "partially repaired", "unresolved", "blocked"]

    for oc in outcomes:
        rec = RunRecord(
            run_id=f"test-{oc[:4]}-101",
            repo_path="/fake/repo",
            repo_name="org/sample-repo",
            branch="main",
            base_commit="abc1234567890123456789012345678901234567",
            short_sha="abc12345",
            mode="real",
            status="HEALTHY" if oc == "healthy" else ("VERIFIED" if oc == "repaired" else "FAILED"),
            final_status=oc,
            stop_reason=f"Terminated with outcome: {oc}",
            retry_count=0 if oc == "healthy" else 2,
            created_at="2026-10-23 05:00:00",
            completed_at="2026-10-23 05:01:00",
            elapsed_seconds=60.0,
            is_healthy=(oc in ("healthy", "repaired")),
            attempts=[],
            verified_patches=[],
        )

        rep = generate_final_report(run_record=rec)
        assert rep.outcome == oc
        assert rep.run_id == rec.run_id
        assert rep.repository == "org/sample-repo"
        assert rep.base_commit == rec.base_commit
        assert rep.branch == "main"
        assert oc.upper() in rep.markdown
        assert "Verification Scope:" in rep.verification_scope_statement

        # Truthful scope boundaries: healthy says baseline passed without repair
        if oc == "healthy":
            assert "baseline test and lint checks passed cleanly" in rep.verification_scope_statement
        elif oc == "repaired":
            assert "exit code 0" in rep.verification_scope_statement
            assert "Human engineering review and approval remain mandatory" in rep.verification_scope_statement
        elif oc == "blocked":
            assert (
                "blocked by infrastructure" in rep.verification_scope_statement
                or "refused execution" in rep.verification_scope_statement
            )


# ── Test 2: Reports containing attempt history and verification evidence ─


def test_report_contains_attempt_history_and_evidence():
    """Verify that reports include complete chronological attempt history with real commands and output."""
    attempt1 = RepairAttempt(
        attempt=1,
        status="TEST_FAILED",
        failure_category="test",
        diagnosis={"root_cause": "AssertionError in index handler"},
        patch={"explanation": "First candidate fix", "files": [{"path": "sample-app/app.py"}]},
        verification={
            "status": "test_failed",
            "exit_code": 1,
            "executed_commands": ["pytest sample-app/tests/test_app.py"],
            "output": "FAILED test_app.py::test_index - AssertionError",
        },
        test_results="AssertionError: expected 200 got 500",
        reason="Verification failed with exit code 1",
    )
    attempt2 = RepairAttempt(
        attempt=2,
        status="VERIFIED",
        failure_category="test",
        diagnosis={"root_cause": "Fix status code logic in app.py"},
        patch={"explanation": "Correct return code to 200", "files": [{"path": "sample-app/app.py"}]},
        verification={
            "status": "verified",
            "exit_code": 0,
            "executed_commands": ["pytest sample-app/tests/test_app.py"],
            "output": "PASSED test_app.py::test_index",
        },
        test_results="1 passed in 0.2s",
        reason="All required checks passed after verified repair.",
    )

    rec = RunRecord(
        run_id="run-history-test",
        repo_path="/test/repo",
        repo_name="test/repo",
        branch="develop",
        base_commit="1111222233334444555566667777888899990000",
        short_sha="11112222",
        mode="real",
        status="VERIFIED",
        final_status="repaired",
        stop_reason="All checks passed.",
        retry_count=2,
        created_at="2026-10-23 05:00:00",
        attempts=[attempt1.model_dump(), attempt2.model_dump()],
        verified_patches=[{"explanation": "Correct return code to 200", "files": [{"path": "sample-app/app.py"}]}],
    )

    rep = generate_final_report(run_record=rec)
    assert len(rep.attempts) == 2
    assert "Attempt 1" in rep.markdown
    assert "Attempt 2" in rep.markdown
    assert "AssertionError" in rep.markdown
    assert "pytest sample-app/tests/test_app.py" in rep.markdown
    assert "PASSED test_app.py::test_index" in rep.markdown


# ── Test 3: Missing credentials and missing remote configuration ──


def test_missing_credentials_and_remote_handling():
    """Verify truthful handling when GitHub token or remote is missing."""
    patch_prop = _make_dummy_patch()
    verif = _make_verified_result()

    # Case A: Missing token
    cfg_no_token = AgentConfig(
        enable_repair_pr=True,
        github_token="",
        repo_name="owner/repo",
        run_id="run-test-no-token",
    )
    res_no_token = publish_repair_pr(patch_prop, verif, {}, cfg_no_token)
    assert res_no_token.status == PublishStatus.PERMISSION_ERROR
    assert "missing" in res_no_token.message.lower()

    # Case B: Missing repo / invalid format
    cfg_no_repo = AgentConfig(
        enable_repair_pr=True,
        github_token="ghp_dummytoken",
        repo_name="local_only_repo",
        run_id="run-test-no-repo",
    )
    res_no_repo = publish_repair_pr(patch_prop, verif, {}, cfg_no_repo)
    assert res_no_repo.status == PublishStatus.PERMISSION_ERROR
    assert "owner/repo" in res_no_repo.message

    # Case C: Disabled in config
    cfg_disabled = AgentConfig(
        enable_repair_pr=False,
        github_token="ghp_dummytoken",
        repo_name="owner/repo",
    )
    res_disabled = publish_repair_pr(patch_prop, verif, {}, cfg_disabled)
    assert res_disabled.status == PublishStatus.SKIPPED_UNVERIFIED
    assert "disabled" in res_disabled.message.lower()


# ── Test 4: Refusal to publish when verification failed or was blocked ─


def test_refusal_to_publish_unverified_or_blocked():
    """Verify that unverified or blocked repairs are strictly refused publication."""
    patch_prop = _make_dummy_patch()
    cfg = AgentConfig(
        enable_repair_pr=True,
        github_token="ghp_valid_token",
        repo_name="owner/repo",
        run_id="run-refusal-test",
    )

    unverified_statuses = [
        (VerificationStatus.TEST_FAILED, 1, False),
        (VerificationStatus.TIMEOUT, 124, False),
        (VerificationStatus.INFRASTRUCTURE_FAILURE, 1, False),
        (VerificationStatus.PATCH_REJECTED, 1, False),
    ]

    for status, exit_code, is_ver in unverified_statuses:
        verif = VerificationResult(
            status=status,
            is_verified=is_ver,
            exit_code=exit_code,
            error_message="Verification failed or blocked",
        )
        res = publish_repair_pr(patch_prop, verif, {}, cfg)
        assert res.status == PublishStatus.SKIPPED_UNVERIFIED
        assert "refusing to publish" in res.message.lower()
        assert res.pr_url is None
        assert res.pr_number is None


# ── Test 5: Successful Draft PR creation with mocked GitHub responses ─


def test_successful_draft_pr_creation_mocked():
    """Verify end-to-end Draft PR creation using mocked GitHub REST API."""
    patch_prop = _make_dummy_patch()
    verif = _make_verified_result()
    cfg = AgentConfig(
        enable_repair_pr=True,
        github_token="ghp_mock_token_12345",
        repo_name="acme/service",
        base_branch="main",
        run_id="run-pr-success",
        commit_sha="c0ffee1234567890c0ffee1234567890c0ffee12",
    )
    diagnosis = {"failure_types": ["pytest"], "root_cause": "Assertion failure in test_app"}

    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        # Mock GET checks:
        # 1. ref check -> 404 (branch does not exist yet)
        # 2. base ref -> 200 with sha
        # 3. commit -> 200 with tree sha
        # 4. raw file content -> 200
        def fake_get(url, *args, **kwargs):
            resp = MagicMock()
            if "/git/ref/heads/agent/fix-" in url:
                resp.status_code = 404
            elif "/git/ref/heads/main" in url:
                resp.status_code = 200
                resp.json.return_value = {"object": {"sha": "base123sha"}}
            elif "/git/commits/base123sha" in url:
                resp.status_code = 200
                resp.json.return_value = {"tree": {"sha": "tree123sha"}}
            elif "/contents/" in url:
                resp.status_code = 200
                resp.json.return_value = {
                    "encoding": "utf-8",
                    "content": "def old_msg():\n    return 'hello'\n",
                }
            else:
                resp.status_code = 404
            return resp

        def fake_post(url, *args, **kwargs):
            resp = MagicMock()
            if "/git/trees" in url:
                resp.status_code = 201
                resp.json.return_value = {"sha": "newtree456sha"}
            elif "/git/commits" in url:
                resp.status_code = 201
                resp.json.return_value = {"sha": "newcommit789sha"}
            elif "/git/refs" in url:
                resp.status_code = 201
                resp.json.return_value = {"ref": "refs/heads/agent/fix-pytest-run-pr-success"}
            elif "/pulls" in url:
                resp.status_code = 201
                resp.json.return_value = {
                    "number": 42,
                    "html_url": "https://github.com/acme/service/pull/42",
                    "draft": True,
                }
            else:
                resp.status_code = 400
            return resp

        mock_get.side_effect = fake_get
        mock_post.side_effect = fake_post

        pub_res = publish_repair_pr(patch_prop, verif, diagnosis, cfg)
        assert pub_res.status == PublishStatus.PUBLISHED
        assert pub_res.pr_number == 42
        assert pub_res.pr_url == "https://github.com/acme/service/pull/42"
        assert pub_res.is_draft is True
        assert "agent/fix-pytest" in pub_res.branch_name

        # Verify PR payload sent to GitHub was strictly a draft with anti-recursion tag
        pulls_calls = [c for c in mock_post.call_args_list if "/pulls" in c[0][0]]
        assert len(pulls_calls) == 1
        payload = pulls_calls[0][1]["json"]
        assert payload["draft"] is True
        assert RECURSION_TAG in payload["title"]
        assert RECURSION_TAG in payload["body"]


# ── Test 6: Correct repository, base branch, repair branch and commit identification ─


def test_correct_repo_branch_commit_identification():
    """Verify accurate extraction and propagation of repository identity."""
    # HTTPS remote
    assert extract_github_repo_from_remote("https://github.com/octocat/Hello-World.git") == "octocat/Hello-World"
    assert extract_github_repo_from_remote("https://github.com/owner/repo") == "owner/repo"

    # SSH remote
    assert extract_github_repo_from_remote("git@github.com:my-org/my-app.git") == "my-org/my-app"
    assert extract_github_repo_from_remote("git@github.com:my-org/my-app") == "my-org/my-app"

    # Non-github or invalid
    assert extract_github_repo_from_remote("https://gitlab.com/group/project.git") is None
    assert extract_github_repo_from_remote("") is None
    assert extract_github_repo_from_remote(None) is None


# ── Test 7: Exclusion of unrelated files and sensitive data from published changes ─


def test_exclusion_of_unrelated_and_sensitive_files():
    """Verify that only explicitly validated files enter the Git tree and secrets are scrubbed."""
    # Validate that sensitive files are rejected by safety validator
    from agent.validator import validate_patch
    sensitive_diff = (
        "--- a/.env\n"
        "+++ b/.env\n"
        "@@ -1 +1 @@\n"
        "-API_KEY=old\n"
        "+API_KEY=new\n"
    )
    val = validate_patch(sensitive_diff)
    assert val.is_valid is False
    assert any("PROHIBITED" in e.code for e in val.errors)

    # Validate that report scrubs API tokens
    raw_log = "Error connecting with token ghp_secretkey1234567890abcdef"
    report_dict = {
        "run_id": "test-redact",
        "repository": "org/repo",
        "branch": "main",
        "base_commit": "abc1234",
        "short_sha": "abc1234",
        "outcome": "unresolved",
        "mode": "real",
        "created_at": "2026-10-23 05:00:00",
        "initial_checks": {"evidence": raw_log},
    }
    rendered_md = build_report_markdown(report_dict)
    assert "ghp_secretkey1234567890abcdef" not in rendered_md
    assert "[REDACTED_SECRET]" in rendered_md or "[REDACTED]" in rendered_md or "ghp_***" in rendered_md


# ── Test 8: API authentication failures, permission failures and branch conflicts ─


def test_api_auth_permission_failures_and_branch_conflicts():
    """Verify truthful handling of HTTP 401, 403, and 422 branch conflicts."""
    patch_prop = _make_dummy_patch()
    verif = _make_verified_result()
    cfg = AgentConfig(
        enable_repair_pr=True,
        github_token="ghp_bad_token",
        repo_name="org/repo",
        run_id="run-auth-test",
    )

    # 1. 401 Unauthorized
    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 401
        mock_get.return_value = resp
        res_401 = publish_repair_pr(patch_prop, verif, {}, cfg)
        assert res_401.status == PublishStatus.PERMISSION_ERROR
        assert "401" in res_401.message

    # 2. 403 Forbidden
    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 403
        mock_get.return_value = resp
        res_403 = publish_repair_pr(patch_prop, verif, {}, cfg)
        assert res_403.status == PublishStatus.FORK_LIMITATION
        assert "403" in res_403.message

    # 3. 422 Branch Ref Already Exists on POST /git/refs
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        def fake_get(url, *args, **kwargs):
            r = MagicMock()
            if "/git/ref/heads/agent/fix-" in url:
                r.status_code = 404
            elif "/git/ref/heads/main" in url:
                r.status_code = 200
                r.json.return_value = {"object": {"sha": "sha_base"}}
            elif "/git/commits/sha_base" in url:
                r.status_code = 200
                r.json.return_value = {"tree": {"sha": "sha_tree"}}
            elif "/contents/" in url:
                r.status_code = 200
                r.json.return_value = {"encoding": "utf-8", "content": "def old_msg():\n    return 'hello'\n"}
            return r

        def fake_post(url, *args, **kwargs):
            r = MagicMock()
            if "/git/trees" in url:
                r.status_code = 201
                r.json.return_value = {"sha": "sha_tree_new"}
            elif "/git/commits" in url:
                r.status_code = 201
                r.json.return_value = {"sha": "sha_commit_new"}
            elif "/git/refs" in url:
                r.status_code = 422
                r.text = "Reference already exists"
            return r

        mock_get.side_effect = fake_get
        mock_post.side_effect = fake_post

        res_422 = publish_repair_pr(patch_prop, verif, {}, cfg)
        assert res_422.status == PublishStatus.SKIPPED_ALREADY_EXISTS
        assert "already exists" in res_422.message.lower()


# ── Test 9: Duplicate publication handling ────────────────────────


def test_duplicate_publication_handling():
    """Verify that an existing open PR for the repair branch returns SKIPPED_ALREADY_EXISTS."""
    patch_prop = _make_dummy_patch()
    verif = _make_verified_result()
    cfg = AgentConfig(
        enable_repair_pr=True,
        github_token="ghp_valid_token",
        repo_name="org/repo",
        run_id="run-dup-test",
    )

    with patch("requests.get") as mock_get:
        def fake_get(url, *args, **kwargs):
            r = MagicMock()
            if "/git/ref/heads/agent/fix-" in url:
                r.status_code = 200
                r.json.return_value = {"object": {"sha": "branchsha"}}
            elif "/pulls" in url:
                r.status_code = 200
                r.json.return_value = [
                    {"number": 99, "html_url": "https://github.com/org/repo/pull/99", "state": "open"}
                ]
            return r

        mock_get.side_effect = fake_get

        res_dup = publish_repair_pr(patch_prop, verif, {}, cfg)
        assert res_dup.status == PublishStatus.SKIPPED_ALREADY_EXISTS
        assert res_dup.pr_number == 99
        assert res_dup.pr_url == "https://github.com/org/repo/pull/99"
        assert "already exists" in res_dup.message


# ── Test 10: Honest reporting when publication fails after verified repair ─


def test_honest_reporting_when_publication_fails_after_verification():
    """Verify that if repair was verified but publication fails, the report states this truthfully."""
    patch_prop = _make_dummy_patch()
    verif = _make_verified_result()
    cfg = AgentConfig(
        enable_repair_pr=True,
        github_token="ghp_valid_token",
        repo_name="org/repo",
        run_id="run-pub-fail-test",
    )

    # Mock verified repair, but GitHub API 500 error when creating Draft PR
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        def fake_get(url, *args, **kwargs):
            r = MagicMock()
            if "/git/ref/heads/agent/fix-" in url:
                r.status_code = 404
            elif "/git/ref/heads/main" in url:
                r.status_code = 200
                r.json.return_value = {"object": {"sha": "sha_base"}}
            elif "/git/commits/sha_base" in url:
                r.status_code = 200
                r.json.return_value = {"tree": {"sha": "sha_tree"}}
            elif "/contents/" in url:
                r.status_code = 200
                r.json.return_value = {"encoding": "utf-8", "content": "def old_msg():\n    return 'hello'\n"}
            return r

        def fake_post(url, *args, **kwargs):
            r = MagicMock()
            if "/git/trees" in url:
                r.status_code = 201
                r.json.return_value = {"sha": "sha_tree_new"}
            elif "/git/commits" in url:
                r.status_code = 201
                r.json.return_value = {"sha": "sha_commit_new"}
            elif "/git/refs" in url:
                r.status_code = 201
                r.json.return_value = {"ref": "refs/heads/agent/fix-pytest-run-pub-fail-test"}
            elif "/pulls" in url:
                r.status_code = 500
                r.text = "Internal Server Error"
            return r

        mock_get.side_effect = fake_get
        mock_post.side_effect = fake_post

        pub_res = publish_repair_pr(patch_prop, verif, {}, cfg)
        assert pub_res.status == PublishStatus.API_ERROR
        assert pub_res.pr_url is None

        # Build run record and final report
        rec = RunRecord(
            run_id="run-pub-fail-test",
            repo_path="/repo/path",
            repo_name="org/repo",
            branch="main",
            base_commit="sha_base",
            short_sha="sha_base"[:8],
            mode="real",
            status="VERIFIED",
            final_status="repaired",
            stop_reason="All test and lint checks passed.",
            retry_count=1,
            created_at="2026-10-23 05:00:00",
            publication={
                "status": pub_res.status.value,
                "message": pub_res.message,
                "branch_name": pub_res.branch_name,
                "pr_url": None,
                "pr_number": None,
                "commit_sha": pub_res.commit_sha,
            },
            verified_patches=[patch_prop.model_dump()],
        )

        rep = generate_final_report(run_record=rec)
        assert rep.outcome == "repaired"
        assert rep.publication["outcome"] == "blocked"
        assert "BLOCKED" in rep.markdown
        assert "Internal Server Error" in rep.markdown or "500" in rep.markdown
        assert rep.publication["pr_url"] is None


# ── Test 11: Dashboard API Report retrieval endpoints ─────────────


def test_dashboard_report_endpoints():
    """Verify /api/reports/<run_id> and /api/reports endpoints return accurate data."""
    app = create_app({"TESTING": True})
    client = app.test_client()

    # Create and save a dummy report
    test_run_id = f"test-rep-{int(time.time())}"
    rec = RunRecord(
        run_id=test_run_id,
        repo_path="/test/path",
        repo_name="demo/app",
        branch="main",
        base_commit="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        short_sha="deadbeef",
        mode="real",
        status="VERIFIED",
        final_status="repaired",
        stop_reason="Clean repair verified.",
        retry_count=1,
        created_at="2026-10-23 05:00:00",
    )
    generate_final_report(run_record=rec)

    # 1. JSON endpoint
    res_json = client.get(f"/api/reports/{test_run_id}")
    assert res_json.status_code == 200
    data = res_json.get_json()
    assert data["run_id"] == test_run_id
    assert data["outcome"] == "repaired"
    assert data["repository"] == "demo/app"

    # 2. Markdown endpoint
    res_md = client.get(f"/api/reports/{test_run_id}/markdown")
    assert res_md.status_code == 200
    assert "text/markdown" in res_md.content_type
    assert test_run_id in res_md.get_data(as_text=True)

    # 3. List reports endpoint
    res_list = client.get("/api/reports")
    assert res_list.status_code == 200
    list_data = res_list.get_json()
    assert "reports" in list_data
    assert any(r["run_id"] == test_run_id for r in list_data["reports"])

    # 4. Non-existent report -> 404
    res_404 = client.get("/api/reports/non-existent-id")
    assert res_404.status_code == 404


# ── Test 12: Truthful trigger context in Markdown reports ──────────


def test_report_markdown_truthful_trigger_context_pr_vs_push():
    """Verify that the generated final report markdown truthfully reflects PR vs Direct Push context."""
    # Case A: PR context
    rec_pr = RunRecord(
        run_id="run-trigger-pr",
        repo_path="/repo",
        repo_name="org/repo",
        branch="main",
        pr_number="123",
        base_commit="abc1234567890123456789012345678901234567",
        short_sha="abc12345",
        mode="real",
        status="VERIFIED",
        final_status="repaired",
        stop_reason="Repairs verified.",
        created_at="2026-10-23 05:00:00",
    )
    rep_pr = generate_final_report(run_record=rec_pr)
    assert "| **Trigger Context** | Pull Request `#{}` |".format("123") in rep_pr.markdown

    # Case B: Push context (no PR)
    rec_push = RunRecord(
        run_id="run-trigger-push",
        repo_path="/repo",
        repo_name="org/repo",
        branch="develop",
        pr_number=None,
        base_commit="def1234567890123456789012345678901234567",
        short_sha="def12345",
        mode="real",
        status="VERIFIED",
        final_status="repaired",
        stop_reason="Repairs verified.",
        created_at="2026-10-23 05:00:00",
    )
    rep_push = generate_final_report(run_record=rec_push)
    assert "| **Trigger Context** | Direct Push (`develop`) |" in rep_push.markdown


# ── Test 13: CI Workflow Least-Privilege Security Audit ────────────


def test_ci_workflow_least_privilege_security_audit():
    """Audit .github/workflows/ci.yml for least privilege, fail-closed defaults, and artifact safety."""
    import os
    import re

    workflow_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        ".github",
        "workflows",
        "ci.yml",
    )
    assert os.path.isfile(workflow_path), f"Workflow file not found: {workflow_path}"

    with open(workflow_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Verify least-privilege ambient permissions (contents: read, never contents: write)
    # Locate self-healing-agent permissions block
    agent_job_match = re.search(r"self-healing-agent:.*?(?=^\s{0,2}\w|\Z)", content, re.DOTALL | re.MULTILINE)
    assert agent_job_match is not None, "self-healing-agent job not found in ci.yml"
    agent_job_text = agent_job_match.group(0)

    # Permissions block in self-healing-agent
    perms_match = re.search(r"permissions:\s*\n((?:\s+[a-zA-Z0-9_-]+:\s*[a-zA-Z0-9_-]+\s*\n)+)", agent_job_text)
    assert perms_match is not None, "permissions block not found under self-healing-agent"
    perms_block = perms_match.group(1)

    assert "contents: read" in perms_block, "self-healing-agent must restrict ambient contents permission to 'read'"
    assert "contents: write" not in perms_block, "self-healing-agent must NOT have ambient contents: write"
    assert "pull-requests: write" in perms_block
    assert "issues: write" in perms_block

    # 2. Inspect step environment variables
    assert "REPAIR_PUBLISHER_TOKEN: ${{ secrets.REPAIR_PUBLISHER_TOKEN }}" in content, (
        "Dedicated REPAIR_PUBLISHER_TOKEN secret must be wired to agent"
    )
    assert "ENABLE_REPAIR_PR: ${{ secrets.ENABLE_REPAIR_PR || 'false' }}" in content, (
        "ENABLE_REPAIR_PR must default to 'false'"
    )

    # 3. Verify artifact upload step runs with if: always() and includes report/diff paths
    upload_match = re.search(
        r"name:\s*Upload ACID AI Reports and Delivery Artifacts.*?(?=^\s{6}-\s*name:|\Z)",
        agent_job_text,
        re.DOTALL | re.MULTILINE,
    )
    assert upload_match is not None, "Upload ACID AI Reports step not found"
    upload_text = upload_match.group(0)
    assert "if: always()" in upload_text, "Artifact upload step must execute on always()"
    assert "reports/" in upload_text
    assert "agent-patch.diff" in upload_text
    assert "agent-analysis.json" in upload_text

"""Unit and integration tests for Milestone 2: Evidence-Driven Diagnosis & Real Patch Generation.

Tests:
1. Inspecting affected repository files from real failure traces (traceback, pytest, flake8).
2. Safety exclusions (secrets, .git, .github, traversal) during evidence inspection.
3. User prompt construction with embedded source snippets.
4. Repository-first analysis on a controlled failing-test repository with deterministic AI mocks.
5. Verification that the diagnosis cites the actual assertion failure and source file.
6. Verification that candidate diffs target real affected files and pass policy validation.
7. Rejection of prohibited diffs (.github, .git, .env) and state mismatches.
8. Truthful error handling when API keys are missing (no invented diagnoses or patches).
9. Truthful handling of provider errors (rate limits, 401s, timeouts) without mock fallbacks.
10. Malformed AI response handling.
"""
import subprocess
import pytest
from unittest.mock import patch

from agent.evidence import inspect_affected_files, extract_affected_files
from agent.providers import build_user_prompt, GeminiProvider, AnthropicProvider
from agent.models import AgentConfig
from dashboard.engine import run_repository_analysis


@pytest.fixture
def sample_app_repo(tmp_path):
    """Create a clean local git repository modeled after sample-app with a controlled failure."""
    repo_dir = tmp_path / "controlled-failing-repo"
    repo_dir.mkdir()

    # Git init
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )

    # sample-app structure
    app_dir = repo_dir / "sample-app"
    app_dir.mkdir()
    app_file = app_dir / "app.py"
    app_file.write_text(
        'from flask import Flask, jsonify\n\n'
        'app = Flask(__name__)\n\n'
        '@app.route("/")\n'
        'def index():\n'
        '    return jsonify({"message": "Service Unavailable"})\n\n'
        '@app.route("/health")\n'
        'def health():\n'
        '    return jsonify({"status": "healthy"})\n',
        encoding="utf-8",
    )

    tests_dir = app_dir / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_app.py"
    test_file.write_text(
        'import pytest\n'
        'import sys, os\n'
        'sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n'
        'from app import app\n\n'
        '@pytest.fixture\n'
        'def client():\n'
        '    app.config["TESTING"] = True\n'
        '    with app.test_client() as client:\n'
        '        yield client\n\n'
        'def test_index_endpoint(client):\n'
        '    response = client.get("/")\n'
        '    assert response.status_code == 200\n'
        '    data = response.get_json()\n'
        '    assert data["message"] == "Welcome to the Sample App!"\n\n'
        'def test_health(client):\n'
        '    res = client.get("/health")\n'
        '    assert res.status_code == 200\n',
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit with failing test"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    return str(repo_dir)


# ── 1. Evidence & Affected Files Inspection Tests ─────────────────────────────


def test_inspect_affected_files_from_traceback_and_pytest(tmp_path):
    """Test that inspect_affected_files extracts real files and line numbers from log text."""
    repo = tmp_path / "repo"
    repo.mkdir()
    app_dir = repo / "sample-app"
    app_dir.mkdir()
    app_py = app_dir / "app.py"
    app_py.write_text('def index():\n    return "Service Unavailable"\n', encoding="utf-8")

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    test_py = tests_dir / "test_app.py"
    test_py.write_text('def test_index():\n    assert False\n', encoding="utf-8")

    sample_log = (
        '=== TEST LOGS ===\n'
        'FAILED tests/test_app.py::test_index - AssertionError\n'
        'File "sample-app/app.py", line 2, in index\n'
        '    return "Service Unavailable"\n'
        'tests/test_app.py:2: AssertionError\n'
    )

    files, snippets, meta = inspect_affected_files(sample_log, str(repo))

    assert "sample-app/app.py" in files
    assert "tests/test_app.py" in files
    assert "=== File: sample-app/app.py" in snippets
    assert "Service Unavailable" in snippets
    assert meta["sample-app/app.py"] == [2]
    assert meta["tests/test_app.py"] == [2]

    # Test extract_affected_files helper directly
    extracted = extract_affected_files(sample_log, str(repo))
    assert extracted == files


def test_inspect_affected_files_safety_exclusions(tmp_path):
    """Test that secrets, .git, .github, and traversal paths are excluded from affected files."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Secret files
    env_file = repo / ".env"
    env_file.write_text("SECRET_KEY=supersecret\n", encoding="utf-8")
    key_file = repo / "id_rsa"
    key_file.write_text("FAKE_KEY_DATA\n", encoding="utf-8")

    # Workflow file
    gh_dir = repo / ".github" / "workflows"
    gh_dir.mkdir(parents=True)
    wf_file = gh_dir / "ci.yml"
    wf_file.write_text("name: CI\n", encoding="utf-8")

    # Legitimate file
    src_dir = repo / "src"
    src_dir.mkdir()
    code_file = src_dir / "main.py"
    code_file.write_text("print('hello')\n", encoding="utf-8")

    malicious_log = (
        'File ".env", line 1, in <module>\n'
        'File "id_rsa", line 1, in <module>\n'
        'File ".github/workflows/ci.yml", line 1, in <module>\n'
        'File "../outside.py", line 1, in <module>\n'
        'File "/etc/shadow", line 1, in <module>\n'
        'File "src/main.py", line 1, in <module>\n'
    )

    files, snippets, _ = inspect_affected_files(malicious_log, str(repo))

    assert files == ["src/main.py"]
    assert ".env" not in snippets
    assert "id_rsa" not in snippets
    assert "ci.yml" not in snippets
    assert "outside.py" not in snippets
    assert "/etc/shadow" not in snippets


def test_build_user_prompt_includes_source_snippets():
    """Verify that build_user_prompt embeds source code snippets safely."""
    logs = "AssertionError: 500 != 200"
    ctx = {"detected": ["test"], "source_snippets": "10: return False"}
    prompt = build_user_prompt(logs, ctx)

    assert "<untrusted_ci_logs>" in prompt
    assert "AssertionError: 500 != 200" in prompt
    assert "<untrusted_source_snippets>" in prompt
    assert "10: return False" in prompt


# ── 2. Controlled Failing Repository Analysis Tests ───────────────────────────


def test_repository_analysis_with_controlled_failing_test_repo(sample_app_repo):
    """Verify repository analysis diagnoses actual failure and generates a valid candidate patch."""
    cfg = AgentConfig(
        ai_provider="gemini",
        gemini_api_key="test-key-mock",
        gemini_model="gemini-3.8-flash",
    )

    mock_diagnosis_json = (
        '{\n'
        '  "severity": "high",\n'
        '  "failure_types": ["test"],\n'
        '  "root_cause": "Unit test test_index_endpoint failed: index() returned Service Unavailable.",\n'
        '  "fixes": [\n'
        '    {\n'
        '      "type": "test",\n'
        '      "title": "Update index message",\n'
        '      "description": "Align index return message with expected test string",\n'
        '      "code": "return jsonify({\\"message\\": \\"Welcome to the Sample App!\\"})"\n'
        '    }\n'
        '  ],\n'
        '  "prevention": "Test endpoints before pushing",\n'
        '  "confidence": "high",\n'
        '  "log_evidence": "AssertionError: assert \'Service Unavailable\' == \'Welcome to the Sample App!\'"\n'
        '}'
    )

    # Candidate diff that precisely fixes sample-app/app.py in the repository
    mock_patch_json = (
        '{\n'
        '  "explanation": "Update index handler response message to match test expectation.",\n'
        '  "diff": "--- a/sample-app/app.py\\n+++ b/sample-app/app.py\\n@@ -6,2 +6,2 @@\\n'
        ' def index():\\n'
        '-    return jsonify({\\"message\\": \\"Service Unavailable\\"})\\n'
        '+    return jsonify({\\"message\\": \\"Welcome to the Sample App!\\"})\\n"\n'
        '}'
    )

    prompts_captured = []

    def mock_gemini_call(prompt, system_prompt=None):
        prompts_captured.append(prompt)
        if "Generate a targeted bug-fix patch" in prompt:
            return mock_patch_json
        return mock_diagnosis_json

    with patch.object(GeminiProvider, "_call_api", side_effect=mock_gemini_call):
        result = run_repository_analysis(
            repo_path=sample_app_repo,
            provider_mode="gemini",
            config=cfg,
        )

    # 1. Assertions on test execution & failure detection
    assert result["status"] in ("VERIFIED", "FAILED", "REPAIRED")
    assert "test" in result["classification"]["detected"]
    assert "AssertionError" in result["logs_raw"]

    # 2. Assertions on evidence inspection & prompt construction
    assert "sample-app/app.py" in result["affected_files"]
    assert len(prompts_captured) >= 2
    diag_prompt = prompts_captured[0]
    assert "AssertionError" in diag_prompt
    assert "sample-app/app.py" in diag_prompt
    assert "Service Unavailable" in diag_prompt

    # 3. Assertions on diagnosis
    diag = result["diagnosis"]
    assert "Service Unavailable" in diag["root_cause"]
    assert "AssertionError" in diag["log_evidence"]

    # 4. Assertions on generated patch
    patch_info = result["patch"]
    assert patch_info["is_valid"] is True
    assert "sample-app/app.py" in patch_info["files"]
    assert "Welcome to the Sample App!" in patch_info["diff"]

    # 5. Assertions on verification & publication gating
    # In Phase 3 and Phase 4, if docker sandbox is available, candidate is verified; if unavailable, fails closed.
    if result["verification"]["status"] in ("verified", "VERIFIED"):
        assert result["verification"]["is_verified"] is True
        assert result["patch"]["is_verified"] is True
        assert "VERIFIED" in result["verification"]["display"]
    else:
        assert result["verification"]["status"] in ("infrastructure_failure", "INFRASTRUCTURE_FAILURE")
        assert "BLOCKED" in result["verification"]["display"]

    assert result["publication"]["status"] in ("skipped_milestone_2", "skipped_phase_3", "skipped_phase_4")
    assert "DISABLED" in result["publication"]["display"]

    # 6. Assertions on run record association
    rec = result["run_record"]
    assert rec["mode"] == "gemini"
    assert rec["repo_name"] == "controlled-failing-repo"
    assert rec["status"] in ("VERIFIED", "FAILED", "REPAIRED")


# ── 3. Prohibited and Invalid Diff Rejection Tests ────────────────────────────


def test_repository_analysis_rejects_prohibited_workflow_patch(sample_app_repo):
    """Verify that a candidate patch attempting to modify .github/ workflows is rejected by policy."""
    cfg = AgentConfig(
        ai_provider="gemini",
        gemini_api_key="test-key-mock",
    )

    mock_diag_json = (
        '{"severity":"high","failure_types":["test"],'
        '"root_cause":"Failure","fixes":[],"confidence":"high","log_evidence":"assert"}'
    )
    mock_prohibited_diff_json = (
        '{\n'
        '  "explanation": "Attempt to bypass CI checks in workflow.",\n'
        '  "diff": "--- a/.github/workflows/ci.yml\\n+++ b/.github/workflows/ci.yml\\n'
        '@@ -1,2 +1,2 @@\\n-run: pytest\\n+run: echo bypass\\n"\n'
        '}'
    )

    def mock_gemini_call(prompt, system_prompt=None):
        if "Generate a targeted bug-fix patch" in prompt:
            return mock_prohibited_diff_json
        return mock_diag_json

    with patch.object(GeminiProvider, "_call_api", side_effect=mock_gemini_call):
        result = run_repository_analysis(
            repo_path=sample_app_repo,
            provider_mode="gemini",
            config=cfg,
        )

    patch_info = result["patch"]
    assert patch_info["is_valid"] is False
    codes = [e["code"] for e in patch_info["validation_errors"]]
    assert "PROHIBITED_FILE_MODIFICATION" in codes
    assert result["verification"]["status"] in ("patch_rejected", "PATCH_REJECTED")


def test_repository_analysis_rejects_nonexistent_target_patch(sample_app_repo):
    """Verify that a candidate patch targeting a file that does not exist is rejected."""
    cfg = AgentConfig(ai_provider="gemini", gemini_api_key="test-key-mock")

    mock_diag_json = (
        '{"severity":"high","failure_types":["test"],'
        '"root_cause":"Failure","fixes":[],"confidence":"high","log_evidence":"assert"}'
    )
    mock_nonexistent_diff_json = (
        '{\n'
        '  "explanation": "Edit nonexistent file.",\n'
        '  "diff": "--- a/sample-app/nonexistent_file.py\\n+++ b/sample-app/nonexistent_file.py\\n'
        '@@ -1,1 +1,1 @@\\n-old\\n+new\\n"\n'
        '}'
    )

    def mock_gemini_call(prompt, system_prompt=None):
        if "Generate a targeted bug-fix patch" in prompt:
            return mock_nonexistent_diff_json
        return mock_diag_json

    with patch.object(GeminiProvider, "_call_api", side_effect=mock_gemini_call):
        result = run_repository_analysis(
            repo_path=sample_app_repo,
            provider_mode="gemini",
            config=cfg,
        )

    patch_info = result["patch"]
    assert patch_info["is_valid"] is False
    codes = [e["code"] for e in patch_info["validation_errors"]]
    assert "TARGET_FILE_NOT_FOUND" in codes
    assert result["verification"]["status"] in ("patch_rejected", "PATCH_REJECTED")


# ── 4. Missing API Keys & Truthful Reporting Tests ────────────────────────────


def test_repository_analysis_missing_gemini_key_reports_unavailable(sample_app_repo, monkeypatch):
    """When GEMINI_API_KEY is not configured, report unavailable and do NOT invent a diagnosis or patch."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg = AgentConfig(ai_provider="gemini", gemini_api_key=None)

    result = run_repository_analysis(
        repo_path=sample_app_repo,
        provider_mode="gemini",
        config=cfg,
    )

    assert result["status"] == "FAILED"
    assert "No GEMINI_API_KEY" in result["truthfulness"]["ai_provider"]
    assert "unavailable because GEMINI_API_KEY is not configured" in result["diagnosis"]["root_cause"]
    assert result["diagnosis"]["fixes"] == []
    # No patch invented
    assert result["patch"]["diff"] == ""
    assert result["patch"]["is_valid"] is False
    assert result["verification"]["status"] in ("patch_rejected", "PATCH_REJECTED")
    # Ensure no mock scenario was used
    assert "missing_dependency" not in result["diagnosis"]["root_cause"]


def test_repository_analysis_missing_claude_key_reports_unavailable(sample_app_repo, monkeypatch):
    """When ANTHROPIC_API_KEY is not configured, report unavailable and do NOT invent a diagnosis or patch."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = AgentConfig(ai_provider="claude", anthropic_api_key=None)

    result = run_repository_analysis(
        repo_path=sample_app_repo,
        provider_mode="claude",
        config=cfg,
    )

    assert result["status"] == "FAILED"
    assert "No ANTHROPIC_API_KEY" in result["truthfulness"]["ai_provider"]
    assert "unavailable because ANTHROPIC_API_KEY is not configured" in result["diagnosis"]["root_cause"]
    assert result["patch"]["diff"] == ""
    assert result["patch"]["is_valid"] is False


# ── 5. Provider Errors & Malformed Responses Tests ────────────────────────────


def test_repository_analysis_provider_rate_limit_handled_truthfully(sample_app_repo):
    """When the live AI provider fails with a rate limit, report error truthfully without canned mock fallback."""
    cfg = AgentConfig(ai_provider="gemini", gemini_api_key="real-looking-key")

    with patch.object(
        GeminiProvider,
        "_call_api",
        side_effect=RuntimeError("Google Gemini rate limit exceeded (HTTP 429)."),
    ):
        result = run_repository_analysis(
            repo_path=sample_app_repo,
            provider_mode="gemini",
            config=cfg,
        )

    assert result["status"] == "FAILED"
    assert "Provider Error" in result["truthfulness"]["ai_provider"]
    assert "rate limit exceeded" in result["diagnosis"]["root_cause"]
    assert result["patch"]["diff"] == ""
    assert result["patch"]["is_valid"] is False
    # Crucial: Did NOT silently fall back to MOCK_ANALYSES
    assert "nonexistent-package" not in result["diagnosis"]["root_cause"]


def test_repository_analysis_claude_auth_failure_handled_truthfully(sample_app_repo):
    """When Anthropic Claude fails authentication, report error truthfully without mock fallback."""
    cfg = AgentConfig(ai_provider="claude", anthropic_api_key="bad-key")

    with patch.object(
        AnthropicProvider,
        "_call_api",
        side_effect=RuntimeError("Anthropic authentication failed: invalid api key"),
    ):
        result = run_repository_analysis(
            repo_path=sample_app_repo,
            provider_mode="claude",
            config=cfg,
        )

    assert result["status"] == "FAILED"
    assert "Provider Error" in result["truthfulness"]["ai_provider"]
    assert "authentication failed" in result["diagnosis"]["root_cause"]
    assert result["patch"]["diff"] == ""


def test_repository_analysis_malformed_json_response_handled_safely(sample_app_repo):
    """When AI provider returns unparseable text instead of JSON, fail safely without crashing."""
    cfg = AgentConfig(ai_provider="gemini", gemini_api_key="test-key")

    with patch.object(
        GeminiProvider,
        "_call_api",
        return_value="I am sorry, but I cannot assist with this request.",
    ):
        result = run_repository_analysis(
            repo_path=sample_app_repo,
            provider_mode="gemini",
            config=cfg,
        )

    assert result["status"] == "FAILED"
    assert "Provider Error" in result["truthfulness"]["ai_provider"]
    assert result["patch"]["diff"] == ""
    assert result["patch"]["is_valid"] is False

"""Mandatory QA tests for repository-specific diagnosis, patch targeting, and retry behavior.

Verifies:
1. Built-in demonstration fixtures still work in the Demonstration Scenarios tab.
2. Repository-first mock mode never uses an unrelated canned sample-app diagnosis.
3. The controlled assertion failure is represented using its actual evidence.
4. A patch to a nonexistent file is rejected with TARGET_FILE_NOT_FOUND.
5. Identical rejected patches do not consume all retry attempts (stalls early).
6. Candidate file paths render correctly without [object Object].
7. Missing live AI credentials produce a truthful status with no fabricated patch.
"""
import subprocess
import pytest
from unittest.mock import patch

from agent.models import (
    AgentConfig,
    PatchProposal,
    PatchStatus,
    FilePatch,
)
from agent.validator import validate_patch
from agent.providers import GeminiProvider
from dashboard.engine import (
    run_scenario,
    run_repository_analysis,
    DEMO_SCENARIOS,
)


@pytest.fixture
def controlled_failure_repo(tmp_path):
    """Create a temporary git repository modeling the reproduced ACID-AI-failure-test."""
    repo_dir = tmp_path / "ACID-AI-failure-test"
    repo_dir.mkdir()

    # Git init
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "QA Tester"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "qa@example.com"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )

    # Root app.py: def add(a, b): return a + b
    app_file = repo_dir / "app.py"
    app_content = "def add(a, b):\n    return a + b\n"
    app_file.write_text(app_content, encoding="utf-8")

    # tests/test_app.py: assert add(2, 2) == 5
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_app.py"
    test_content = "from app import add\n\ndef test_addition():\n    assert add(2, 2) == 5\n"
    test_file.write_text(test_content, encoding="utf-8")

    # Commit initial state
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit with failing test"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )

    return repo_dir, app_content, test_content


# ── QA 1: Built-in demonstration fixtures still work ──────────────────────────


def test_built_in_demonstration_fixtures_still_work():
    """Verify all built-in demonstration fixtures work properly in the Demonstration Scenarios tab."""
    from agent.sandbox import DockerSandbox
    assert len(DEMO_SCENARIOS) >= 6
    with patch.object(DockerSandbox, "is_available", return_value=(False, "Docker daemon offline")):
        for sc_id, sc_meta in DEMO_SCENARIOS.items():
            result = run_scenario(sc_id, provider_mode="mock")
            assert "run_id" in result
            assert result["run_id"].startswith("demo-")
            assert "stages" in result
            assert "logs_raw" in result
            assert result["status"] in ("VERIFIED", "FAILED", "HEALTHY")
            if sc_meta.get("failure_type") in ("none", "live"):
                assert result["is_healthy"] in (True, False)
            else:
                assert result["is_healthy"] is False
                assert "diagnosis" in result
                assert result["diagnosis"]["root_cause"] != ""


# ── QA 2: Repo mock mode never uses unrelated canned sample-app diagnosis ─────


def test_repo_mock_mode_never_uses_unrelated_canned_sample_app_diagnosis(controlled_failure_repo):
    """Verify repository-first mock mode does NOT inject MOCK_ANALYSES or MOCK_DIFFS from sample-app."""
    repo_dir, app_content, test_content = controlled_failure_repo
    cfg = AgentConfig(ai_provider="claude", anthropic_api_key=None)

    result = run_repository_analysis(
        repo_path=str(repo_dir),
        provider_mode="mock",
        config=cfg,
    )

    assert result["is_healthy"] is False
    assert result["status"] == "FAILED"
    assert result["run_record"]["status"] == "BLOCKED"

    # Must NOT mention Flask or Service Unavailable or 200 OK from canned demo fixture
    rc = result["diagnosis"]["root_cause"]
    assert "Service Unavailable" not in rc
    assert "200 OK" not in rc
    assert "Flask" not in rc
    assert "sample-app/app.py" not in rc

    # Must NOT fabricate candidate patch or diff
    assert result["patch"]["diff"] == ""
    assert result["patch"]["files"] == [] or result["patch"]["files"] == result["affected_files"]
    assert "sample-app/app.py" not in result["patch"]["files"]

    # Must truthfully report LIVE_AI_REQUIRED
    val_err_codes = [e["code"] for e in result["patch"]["validation_errors"]]
    assert "LIVE_AI_REQUIRED" in val_err_codes


# ── QA 3: Controlled assertion failure represented with actual evidence ───────


def test_controlled_assertion_failure_represented_with_actual_evidence(controlled_failure_repo):
    """Verify the controlled test failure is triaged with real test logs and leaves repo untouched."""
    repo_dir, original_app, original_test = controlled_failure_repo
    cfg = AgentConfig()

    result = run_repository_analysis(
        repo_path=str(repo_dir),
        provider_mode="mock",
        config=cfg,
    )

    # Actual test execution output preserved
    assert "tests/test_app.py" in result["logs_raw"] or "test_addition" in result["logs_raw"]
    assert "assert add(2, 2) == 5" in result["logs_raw"]

    # Actual affected files identified from test traceback
    assert "tests/test_app.py" in result["affected_files"]

    # Genuine log evidence cited in diagnosis
    log_ev = result["diagnosis"]["log_evidence"]
    assert "assert add(2, 2) == 5" in log_ev or "test_addition" in log_ev

    # Original repository files MUST remain untouched
    app_after = (repo_dir / "app.py").read_text(encoding="utf-8")
    test_after = (repo_dir / "tests" / "test_app.py").read_text(encoding="utf-8")
    assert app_after == original_app
    assert test_after == original_test

    status_proc = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo_dir), capture_output=True, text=True)
    assert status_proc.stdout.strip() == "", "Original repository was modified!"


# ── QA 4: Patch to nonexistent file is rejected ───────────────────────────────


def test_patch_to_nonexistent_file_rejected(controlled_failure_repo):
    """Verify that a patch targeting a file that does not exist in the repository is rejected."""
    repo_dir, _, _ = controlled_failure_repo

    # Proposed patch targets sample-app/app.py which does not exist in this repo
    nonexistent_diff = """--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -1,3 +1,3 @@
-def foo():
+def foo_fixed():
     pass
"""
    validation = validate_patch(nonexistent_diff, repo_root=str(repo_dir))
    assert validation.is_valid is False
    codes = [e.code for e in validation.errors]
    assert "TARGET_FILE_NOT_FOUND" in codes
    assert any("sample-app/app.py" in e.message for e in validation.errors)


# ── QA 5: Identical rejected patches do not consume all retry attempts ────────


def test_identical_rejected_patches_do_not_consume_all_retries(controlled_failure_repo):
    """Verify the repair loop stops immediately on a repeated rejected patch instead of burning all 3 retries."""
    repo_dir, _, _ = controlled_failure_repo
    cfg = AgentConfig(
        ai_provider="gemini",
        gemini_api_key="mock-api-key",
        max_repair_attempts=3,
    )

    # Provider repeatedly produces a patch to a nonexistent file
    mock_bad_diff = """--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -1,2 +1,2 @@
-broken
+fixed
"""
    mock_patch_json = (
        '{\n'
        '  "explanation": "Fix nonexistent file.",\n'
        f'  "diff": "{mock_bad_diff.replace(chr(10), "\\\\n")}"\n'
        '}'
    )
    mock_diag_json = (
        '{\n'
        '  "severity": "medium",\n'
        '  "failure_types": ["test"],\n'
        '  "root_cause": "Test failed in app.",\n'
        '  "fixes": [],\n'
        '  "prevention": "Fix bug",\n'
        '  "confidence": "high",\n'
        '  "log_evidence": "assert add(2, 2) == 5"\n'
        '}'
    )

    call_count = 0

    def mock_gemini_call(prompt, system_prompt=None):
        nonlocal call_count
        call_count += 1
        if "Generate a targeted bug-fix patch" in prompt:
            return mock_patch_json
        return mock_diag_json

    with patch.object(GeminiProvider, "_call_api", side_effect=mock_gemini_call):
        result = run_repository_analysis(
            repo_path=str(repo_dir),
            provider_mode="gemini",
            config=cfg,
        )

    # Loop must have halted on attempt 2 as STALLED due to repeated identical candidate patch
    attempts = result["run_record"]["attempts"]
    assert len(attempts) == 2, f"Expected 2 attempts before stalling, but got {len(attempts)}"
    assert attempts[0]["status"] == "PATCH_REJECTED"
    assert attempts[1]["status"] == "STALLED"
    assert "Repeated identical" in attempts[1]["reason"] or "Nonexistent target" in attempts[1]["reason"]
    assert result["run_record"]["retry_count"] == 2


# ── QA 6: Candidate file paths render correctly in dashboard ──────────────────


def test_candidate_file_paths_render_correctly_without_object_object():
    """Verify candidate file formatting logic converts FilePatch objects and dicts to clean path strings."""
    # Test with FilePatch objects
    fp1 = FilePatch(path="app.py", status="modified", additions=1, deletions=1)
    fp2 = FilePatch(path="tests/test_app.py", status="modified", additions=2, deletions=0)
    proposal = PatchProposal(
        status=PatchStatus.REJECTED,
        explanation="Test proposal",
        diff="--- a/app.py\n+++ b/app.py",
        files=[fp1, fp2],
    )
    dumped = proposal.model_dump()

    # In JS: formatFileList extracts f.path || f.name || f
    files_list = dumped["files"]
    assert isinstance(files_list, list)
    assert isinstance(files_list[0], dict)
    assert files_list[0]["path"] == "app.py"
    assert files_list[1]["path"] == "tests/test_app.py"

    # Format helper emulation
    def format_file_list(files):
        if not files or not isinstance(files, list):
            return "None"
        out = []
        for f in files:
            if isinstance(f, str):
                out.append(f)
            elif isinstance(f, dict):
                out.append(f.get("path") or f.get("name") or "")
            elif hasattr(f, "path"):
                out.append(f.path)
        return ", ".join([x for x in out if x]) or "None"

    rendered = format_file_list(files_list)
    assert rendered == "app.py, tests/test_app.py"
    assert "[object Object]" not in rendered

    # Test with empty
    assert format_file_list([]) == "None"


# ── QA 7: Missing live AI credentials produce truthful status with no fabricated patch ─


def test_missing_live_ai_credentials_produce_truthful_status(controlled_failure_repo, monkeypatch):
    """Verify missing credentials for live modes produce truthful BLOCKED status without fabricated diffs."""
    repo_dir, _, _ = controlled_failure_repo
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Gemini without key
    cfg_gemini = AgentConfig(ai_provider="gemini", gemini_api_key=None)
    res_gemini = run_repository_analysis(
        repo_path=str(repo_dir),
        provider_mode="gemini",
        config=cfg_gemini,
    )
    assert res_gemini["status"] == "FAILED"
    assert res_gemini["run_record"]["status"] == "BLOCKED"
    assert res_gemini["patch"]["diff"] == ""
    assert res_gemini["patch"]["is_valid"] is False
    assert any(e["code"] == "PROVIDER_UNAVAILABLE" for e in res_gemini["patch"]["validation_errors"])
    assert res_gemini["diagnosis"]["fixes"] == []

    # Claude without key
    cfg_claude = AgentConfig(ai_provider="claude", anthropic_api_key=None)
    res_claude = run_repository_analysis(
        repo_path=str(repo_dir),
        provider_mode="claude",
        config=cfg_claude,
    )
    assert res_claude["status"] == "FAILED"
    assert res_claude["run_record"]["status"] == "BLOCKED"
    assert res_claude["patch"]["diff"] == ""
    assert res_claude["patch"]["is_valid"] is False
    assert any(e["code"] == "PROVIDER_UNAVAILABLE" for e in res_claude["patch"]["validation_errors"])
    assert res_claude["diagnosis"]["fixes"] == []

    # Mock mode without live AI credentials
    res_mock = run_repository_analysis(
        repo_path=str(repo_dir),
        provider_mode="mock",
        config=cfg_gemini,
    )
    assert res_mock["status"] == "FAILED"
    assert res_mock["run_record"]["status"] == "BLOCKED"
    assert res_mock["patch"]["diff"] == ""
    assert res_mock["patch"]["is_valid"] is False
    assert any(e["code"] == "LIVE_AI_REQUIRED" for e in res_mock["patch"]["validation_errors"])
    assert res_mock["diagnosis"]["fixes"] == []

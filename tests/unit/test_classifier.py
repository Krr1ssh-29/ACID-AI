"""Tests for accurate failure classification in agent.classifier."""
import os
from agent.classifier import classify_failures
from agent.models import PipelineStatus, StepOutcome

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_classify_healthy_run():
    """Verify classification on clean healthy CI run without error keywords."""
    logs = load_fixture("healthy_run.txt")
    result = classify_failures(logs)
    assert result.status == PipelineStatus.HEALTHY
    assert result.detected == []
    assert not any(result.raw.values())


def test_healthy_run_with_tool_names_not_flagged_as_failure():
    """Verify passing logs mentioning 'pip', 'flake8', 'pytest', and 'step' are recognized as healthy.

    This resolves the Phase 01 false-positive defect where generic tool names triggered failures.
    """
    passing_log_with_tool_mentions = (
        "Running pip install -r requirements.txt: 100% complete\n"
        "flake8 passed: 0 errors\n"
        "pytest run: 3 passed in 0.5s\n"
        "Step 1/5: Docker image created\n"
        "=== PIPELINE RUN SUMMARY ===\n"
        "All checks passed successfully.\n"
    )
    result = classify_failures(passing_log_with_tool_mentions)
    assert result.status == PipelineStatus.HEALTHY
    assert result.detected == []
    assert result.raw["install"] is False
    assert result.raw["lint"] is False
    assert result.raw["test"] is False
    assert result.raw["docker"] is False


def test_classify_authoritative_step_outcomes_all_success():
    """Verify that authoritative step outcomes showing all successes yield HEALTHY status."""
    log_text = (
        "Build logs...\n"
        "=== STEP OUTCOMES ===\n"
        "install: success\n"
        "lint: success\n"
        "test: success\n"
        "docker: success\n"
    )
    result = classify_failures(log_text)
    assert result.status == PipelineStatus.HEALTHY
    assert result.detected == []
    assert result.step_outcomes["install"] == StepOutcome.SUCCESS
    assert result.step_outcomes["test"] == StepOutcome.SUCCESS


def test_classify_authoritative_step_outcomes_with_failure():
    """Verify that authoritative step outcomes flag only the failing step."""
    log_text = (
        "Build logs...\n"
        "=== STEP OUTCOMES ===\n"
        "install: success\n"
        "lint: failure\n"
        "test: success\n"
        "docker: skipped\n"
    )
    result = classify_failures(log_text)
    assert result.status == PipelineStatus.FAILED
    assert result.detected == ["lint"]
    assert result.raw["lint"] is True
    assert result.raw["install"] is False
    assert result.raw["test"] is False


def test_classify_authoritative_step_outcomes_cancelled():
    """Verify cancelled pipeline step yields INCONCLUSIVE status."""
    log_text = (
        "=== STEP OUTCOMES ===\n"
        "install: success\n"
        "lint: cancelled\n"
        "test: skipped\n"
    )
    result = classify_failures(log_text)
    assert result.status == PipelineStatus.INCONCLUSIVE
    assert "cancelled" in result.details.lower()


def test_classify_authoritative_step_outcomes_failure_takes_precedence_over_cancellation():
    """Verify that when both failure and cancellation occur, failure takes precedence."""
    log_text = (
        "=== STEP OUTCOMES ===\n"
        "install: failure\n"
        "lint: cancelled\n"
        "test: skipped\n"
        "docker: skipped\n"
    )
    result = classify_failures(log_text)
    assert result.status == PipelineStatus.FAILED
    assert "install" in result.detected
    assert result.raw["install"] is True


def test_classify_authoritative_step_outcomes_multiple_failures_and_cancelled():
    """Verify multiple failing steps are all reported even if other steps are cancelled."""
    log_text = (
        "=== STEP OUTCOMES ===\n"
        "install: failure\n"
        "lint: success\n"
        "test: failure\n"
        "docker: cancelled\n"
    )
    result = classify_failures(log_text)
    assert result.status == PipelineStatus.FAILED
    assert set(result.detected) == {"install", "test"}
    assert result.raw["install"] is True
    assert result.raw["test"] is True
    assert result.raw["lint"] is False


def test_classify_authoritative_step_outcomes_all_skipped():
    """Verify that when all pipeline steps are skipped, status is INCONCLUSIVE."""
    log_text = (
        "=== STEP OUTCOMES ===\n"
        "install: skipped\n"
        "lint: skipped\n"
        "test: skipped\n"
        "docker: skipped\n"
    )
    result = classify_failures(log_text)
    assert result.status == PipelineStatus.INCONCLUSIVE
    assert "skipped" in result.details.lower()


def test_classify_authoritative_step_outcomes_success_with_intentional_skip():
    """Verify that executed successful steps with an intentionally skipped step remain HEALTHY."""
    log_text = (
        "=== STEP OUTCOMES ===\n"
        "install: success\n"
        "lint: success\n"
        "test: success\n"
        "docker: skipped\n"
    )
    result = classify_failures(log_text)
    assert result.status == PipelineStatus.HEALTHY
    assert result.detected == []


def test_workflow_truthful_pipeline_status_enforcement():
    """Verify .github/workflows/ci.yml enforces failure, cancellation, and unexpected skip."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    workflow_path = os.path.join(repo_root, ".github", "workflows", "ci.yml")
    with open(workflow_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Enforce truthful pipeline status" in content
    assert "check_step" in content
    assert "cancelled)" in content
    assert "failure)" in content
    assert "skipped)" in content
    assert 'check_step "install"' in content
    assert 'check_step "lint"' in content
    assert 'check_step "test"' in content
    assert 'check_step "docker"' in content


def test_classify_missing_dependency():
    """Verify detection of dependency installation failure via narrow regex."""
    logs = load_fixture("missing_dependency.txt")
    result = classify_failures(logs)
    assert result.status == PipelineStatus.FAILED
    assert "install" in result.detected
    assert result.raw["install"] is True


def test_classify_lint_flake8_error():
    """Verify detection of flake8 linting violations via narrow regex."""
    logs = load_fixture("lint_flake8_error.txt")
    result = classify_failures(logs)
    assert result.status == PipelineStatus.FAILED
    assert "lint" in result.detected
    assert result.raw["lint"] is True


def test_classify_pytest_assertion_failure():
    """Verify detection of pytest test assertion failures via narrow regex."""
    logs = load_fixture("pytest_assertion_failure.txt")
    result = classify_failures(logs)
    assert result.status == PipelineStatus.FAILED
    assert "test" in result.detected
    assert result.raw["test"] is True


def test_classify_docker_build_failure():
    """Verify detection of container/docker build failure via narrow regex."""
    logs = load_fixture("docker_build_failure.txt")
    result = classify_failures(logs)
    assert result.status == PipelineStatus.FAILED
    assert "docker" in result.detected
    assert result.raw["docker"] is True


def test_classify_multiple_failures():
    """Verify multiple simultaneous failure types are all detected."""
    combined = (
        "ERROR: No matching distribution found for packageX\n"
        "sample-app/app.py:10:1: E101 indentation error\n"
        "FAILED tests/test_app.py::test_fn - AssertionError\n"
        "The command '/bin/sh -c pip install' returned a non-zero code: 1\n"
    )
    result = classify_failures(combined)
    assert result.status == PipelineStatus.FAILED
    assert set(result.detected) == {"install", "lint", "test", "docker"}


def test_classify_empty_or_whitespace_log():
    """Verify empty or missing log text produces INCONCLUSIVE status, not false healthy."""
    result = classify_failures("")
    assert result.status == PipelineStatus.INCONCLUSIVE
    assert result.detected == []

    result_ws = classify_failures("   \n   \t  ")
    assert result_ws.status == PipelineStatus.INCONCLUSIVE


def test_classify_error_reading_log():
    """Verify file read errors result in ERROR status."""
    result = classify_failures("Error reading log file 'combined-logs.txt': Permission denied")
    assert result.status == PipelineStatus.ERROR
    assert result.detected == []


def test_classify_ambiguous_log_without_completion_markers():
    """Verify truncated log without failure or success markers is deemed INCONCLUSIVE."""
    ambiguous_text = "Starting worker process 1024...\nLoading system configuration...\n"
    result = classify_failures(ambiguous_text)
    assert result.status == PipelineStatus.INCONCLUSIVE
    assert result.detected == []

"""Unit tests for contract ambiguity handling and truthful root-cause analysis (QA Fix 2).

Verifies:
1. Ambiguous contracts between implementation and test assertions are detected and flagged.
2. The agent refuses to blindly guess or alter the test or application to get a green pipeline.
3. Root cause explicitly cites contract ambiguity and confidence is marked low.
4. Candidate patch generation is skipped or rejected with an evidence-backed justification.
5. Unambiguous defects (e.g., return a + b + 1 vs expected a + b) are properly distinguished.
"""
import subprocess
import pytest

from agent.models import (
    AgentConfig,
    AnalysisResult,
)
from dashboard.engine import (
    run_repository_analysis,
    RepositoryEvidenceMockProvider,
)


@pytest.fixture
def ambiguous_repo(tmp_path):
    """Controlled repo with ambiguous contract: add(2, 2) == 5 vs def add(a, b): return a + b."""
    repo_dir = tmp_path / "ambiguous-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "tester@example.com"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )

    (repo_dir / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    ambiguous_test = "from app import add\n\ndef test_addition():\n    assert add(2, 2) == 5\n"
    (tests_dir / "test_app.py").write_text(ambiguous_test, encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)
    return repo_dir


@pytest.fixture
def unambiguous_defect_repo(tmp_path):
    """Controlled repo with unambiguous defect: def add returns a + b + 1, test correctly expects a + b."""
    repo_dir = tmp_path / "unambiguous-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "tester@example.com"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )

    # Deliberately faulty implementation with clear docstring defining specification
    (repo_dir / "app.py").write_text(
        'def add(a, b):\n    """Return the arithmetic sum of a and b."""\n    return a + b + 1\n',
        encoding="utf-8",
    )
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "from app import add\n\ndef test_addition():\n    assert add(2, 2) == 4\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)
    return repo_dir


def test_repository_mock_provider_detects_contract_ambiguity():
    """Verify RepositoryEvidenceMockProvider detects ambiguous assertion and marks confidence low."""
    failure_logs = (
        "def test_addition():\n"
        ">       assert add(2, 2) == 5\n"
        "E       AssertionError: assert 4 == 5\n"
    )
    provider = RepositoryEvidenceMockProvider(cited_evidence="assert add(2, 2) == 5")
    analysis: AnalysisResult = provider.diagnose(failure_logs)

    assert analysis.confidence == "low"
    assert "contract ambiguity" in analysis.root_cause.lower()
    assert "assert add(2, 2) == 5" in analysis.log_evidence
    assert analysis.fixes == []


def test_ambiguous_contract_repo_run_reports_ambiguity_without_guessing(ambiguous_repo):
    """Verify repository analysis of ambiguous repo flags ambiguity, does not guess, and leaves repo clean."""
    cfg = AgentConfig()
    result = run_repository_analysis(
        repo_path=str(ambiguous_repo),
        provider_mode="mock",
        config=cfg,
    )

    assert result["is_healthy"] is False
    assert result["status"] == "FAILED"
    # Root cause must mention contract ambiguity
    assert "contract ambiguity" in result["diagnosis"]["root_cause"].lower()
    assert result["diagnosis"]["confidence"] == "low"

    # Working tree MUST remain completely clean
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=str(ambiguous_repo), capture_output=True, text=True)
    assert proc.stdout.strip() == "", "Repository was modified!"


def test_unambiguous_repo_distinguished_from_ambiguous(unambiguous_defect_repo):
    """Verify an unambiguous failure (with docstring or clear spec) is distinguished from ambiguous failure."""
    cfg = AgentConfig()
    result = run_repository_analysis(
        repo_path=str(unambiguous_defect_repo),
        provider_mode="mock",
        config=cfg,
    )

    assert result["is_healthy"] is False
    assert result["status"] == "FAILED"
    # Should diagnose real test assertion failure from execution logs
    assert "assert 5 == 4" in result["logs_raw"] or "test_addition" in result["logs_raw"]
    # Not confused with the add(2, 2) == 5 ambiguity
    assert "add(2, 2) == 5" not in result["diagnosis"]["root_cause"]

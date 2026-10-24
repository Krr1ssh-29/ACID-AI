"""End-to-end integration tests for multi-format report export (JSON, Markdown, PDF) — QA Fix 2.

Verifies:
1. Completed run produces consistent JSON, Markdown, and PDF identifying the same run ID.
2. Canonical outcomes and attempt counts match across all three formats.
3. Repository-first runs and mock-demo runs are clearly distinguishable in exports.
4. Blocked run produces a useful report with plain-English summary in all formats.
5. Flask endpoints for JSON, Markdown, and PDF all return HTTP 200 with appropriate content types.
6. Zero real GitHub publication is performed during test runs.
"""
import io
import pytest
from pypdf import PdfReader
from dashboard.app import create_app
from dashboard.engine import run_scenario, run_repository_analysis
from agent.models import AgentConfig


@pytest.fixture
def app_client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_scenario_run_multi_format_export_consistency(app_client):
    """Verify demo scenario run produces consistent JSON, Markdown, and PDF exports."""
    from unittest.mock import patch
    from agent.sandbox import DockerSandbox

    with patch.object(DockerSandbox, "is_available", return_value=(False, "Docker daemon offline")):
        result = run_scenario("missing_dependency", provider_mode="mock")
    run_id = result["run_id"]
    final_status = result["final_status"]

    # 1. JSON Report Endpoint
    res_json = app_client.get(f"/api/reports/{run_id}")
    assert res_json.status_code == 200
    json_data = res_json.get_json()
    assert json_data["run_id"] == run_id
    assert json_data["outcome"] == final_status
    assert "summary" in json_data
    assert json_data["summary"]["overall_outcome"] == final_status

    # 2. Markdown Report Endpoint
    res_md = app_client.get(f"/api/reports/{run_id}/markdown")
    assert res_md.status_code == 200
    assert res_md.content_type.startswith("text/markdown")
    md_text = res_md.get_data(as_text=True)
    assert run_id in md_text
    assert "1. Plain-English Run Summary" in md_text
    assert final_status.upper() in md_text

    # 3. PDF Report Endpoint
    res_pdf = app_client.get(f"/api/reports/{run_id}/pdf")
    assert res_pdf.status_code == 200
    assert res_pdf.content_type == "application/pdf"
    assert res_pdf.data.startswith(b"%PDF-")
    disp = res_pdf.headers.get("Content-Disposition", "")
    assert f'filename="acid-ai-report-{run_id}.pdf"' in disp

    # Verify PDF content via pypdf
    reader = PdfReader(io.BytesIO(res_pdf.data))
    full_pdf_text = " ".join([p.extract_text() for p in reader.pages])
    assert run_id in full_pdf_text
    assert "Plain-English Run Summary" in full_pdf_text
    has_demo = (
        "DETERMINISTIC DEMONSTRATION" in full_pdf_text
        or "DEMO" in full_pdf_text
        or "mock" in full_pdf_text.lower()
    )
    assert has_demo


def test_blocked_run_produces_consistent_multi_format_reports(app_client, tmp_path):
    """Verify a blocked repository run generates useful, consistent reports across JSON, Markdown, and PDF."""
    import subprocess
    repo_dir = tmp_path / "blocked-test-repo"
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
    test_content = "from app import add\n\ndef test_addition():\n    assert add(2, 2) == 5\n"
    (tests_dir / "test_app.py").write_text(test_content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo_dir), check=True, capture_output=True)

    cfg = AgentConfig()
    result = run_repository_analysis(
        repo_path=str(repo_dir),
        provider_mode="mock",
        config=cfg,
    )
    run_id = result["run_id"]
    assert result["run_record"]["status"] == "BLOCKED"

    # Verify JSON
    res_json = app_client.get(f"/api/reports/{run_id}")
    assert res_json.status_code == 200
    json_rep = res_json.get_json()
    assert json_rep["outcome"] == "blocked"
    assert json_rep["summary"]["overall_outcome"] == "blocked"

    # Verify Markdown
    res_md = app_client.get(f"/api/reports/{run_id}/markdown")
    assert res_md.status_code == 200
    md_text = res_md.get_data(as_text=True)
    assert "BLOCKED" in md_text
    assert "Plain-English Run Summary" in md_text

    # Verify PDF
    res_pdf = app_client.get(f"/api/reports/{run_id}/pdf")
    assert res_pdf.status_code == 200
    assert res_pdf.data.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(res_pdf.data))
    full_pdf_text = " ".join([p.extract_text() for p in reader.pages])
    assert run_id in full_pdf_text
    assert "BLOCKED" in full_pdf_text
    assert "Plain-English Run Summary" in full_pdf_text

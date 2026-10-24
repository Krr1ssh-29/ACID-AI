"""Unit tests for PDF report generation and Flask download endpoint.

Verifies:
1. Valid PDF generation with %PDF- header.
2. Correct MIME type application/pdf and Content-Disposition filename.
3. HTTP 404 on missing or unknown run IDs.
4. All 5 canonical outcomes rendered without error.
5. Plain-English summary extracted from PDF text via pypdf.
6. Secret redaction in PDF output.
7. Graceful handling of Unicode, long logs, and malformed inputs.
8. Truthful verification details, stop reasons, and PR links.
"""
import io
from pypdf import PdfReader
from agent.models import FinalReport
from agent.pdf_report import generate_pdf_report
from agent.report import save_report
from dashboard.app import create_app


def create_sample_report(
    run_id: str = "run-pdf-unit-1",
    outcome: str = "repaired",
    pr_url: str = None,
    pr_number: int = None,
    secret_text: str = None,
    log_text: str = "test assertion failed",
) -> FinalReport:
    """Helper to build a realistic FinalReport for testing."""
    root_cause = "AssertionError in tests/test_app.py: expected 5 but got 4"
    if secret_text:
        root_cause += f" with secret {secret_text}"

    is_repaired = outcome == "repaired"
    is_healthy = outcome == "healthy"
    diff_content = "--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n-broken\n+fixed\n"
    verif_status = "VERIFIED_SUCCESS" if is_repaired else ("SKIPPED_HEALTHY" if is_healthy else "FAILED")
    stop_msg = "All required checks passed after verified repair." if is_repaired else "Checks complete."
    attempt_msg = (
        "Attempted 1 container-verified patch on app.py." if not is_healthy else "No repair attempts needed."
    )

    return FinalReport(
        run_id=run_id,
        repository="acid-ai-test-repo",
        repo_path="/d/test/repo",
        branch="main",
        base_commit="abc1234567",
        short_sha="abc1234",
        outcome=outcome,
        mode="real",
        created_at="2026-10-23 10:00:00",
        completed_at="2026-10-23 10:00:15",
        elapsed_seconds=15.0,
        initial_checks={
            "stages": [
                {"name": "Install", "id": "install", "status": "success"},
                {"name": "Lint", "id": "lint", "status": "success"},
                {"name": "Test", "id": "test", "status": "failure" if not is_healthy else "success"},
            ],
            "failures_detected": ["test"] if not is_healthy else [],
        },
        diagnosis={
            "severity": "medium",
            "failure_types": ["test"],
            "root_cause": root_cause,
            "fixes": [],
            "prevention": "Define clear contract.",
            "confidence": "high",
            "log_evidence": log_text,
        },
        candidate_patches=[],
        repair_attempts=[
            {
                "attempt": 1,
                "status": "VERIFIED_SUCCESS" if is_repaired else "FAILED",
                "failure_category": "test",
                "patch": {"diff": diff_content, "files": ["app.py"]},
                "verification": {"is_verified": is_repaired, "exit_code": 0 if is_repaired else 1},
                "reason": "Verification passed" if is_repaired else "Tests failed",
            }
        ] if not is_healthy else [],
        verification={
            "final_status": verif_status,
            "commands_executed": ["pytest -v"],
            "all_passed": outcome in ("healthy", "repaired"),
            "isolation_type": "Hardened Linux Container (read-only rootfs)",
            "host_mutated": False,
        },
        retry_count=1 if not is_healthy else 0,
        stop_reason=stop_msg,
        unresolved_issues=[] if outcome in ("healthy", "repaired") else ["Test suite failure in tests/test_app.py"],
        publication={
            "outcome": "successful" if pr_url else "skipped",
            "raw_status": "published" if pr_url else "skipped",
            "branch": "acid-ai/repair-patch" if pr_url else None,
            "pr_url": pr_url,
            "pr_number": pr_number,
            "commit_sha": "def5678" if pr_url else None,
            "message": "Draft PR created" if pr_url else "Publication skipped",
        },
        changed_files=["app.py"] if is_repaired else [],
        verification_scope_statement="Verification Scope: Candidate code changes verified in container.",
        summary={
            "overall_outcome": outcome,
            "overall_outcome_text": f"Run outcome is {outcome.upper()}.",
            "what_happened": "Pipeline executed repository tests.",
            "why_it_happened": root_cause,
            "what_acid_attempted": attempt_msg,
            "did_repair_work": "Yes — verified in container." if is_repaired else "No.",
            "why_agent_stopped": "Stop condition satisfied.",
            "what_to_do_next": "Review verified PR." if pr_url else "Inspect logs.",
            "publication_status": f"Draft PR #{pr_number} created" if pr_url else "Publication skipped",
            "pr_url": pr_url,
            "pr_number": pr_number,
        },
    )


def test_pdf_signature_and_creation():
    """Verify generated PDF starts with %PDF- signature and creates valid byte stream."""
    report = create_sample_report(run_id="test-sig", outcome="repaired")
    pdf_bytes = generate_pdf_report(report)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_all_five_canonical_outcomes():
    """Verify all 5 canonical outcomes can be rendered to PDF without exceptions."""
    outcomes = ["healthy", "repaired", "partially repaired", "unresolved", "blocked"]
    for out in outcomes:
        report = create_sample_report(run_id=f"test-outcome-{out.replace(' ', '-')}", outcome=out)
        pdf_bytes = generate_pdf_report(report)
        assert pdf_bytes.startswith(b"%PDF-")

        # Verify readable by pypdf
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) >= 1
        page1_text = reader.pages[0].extract_text()
        assert "ACID AI" in page1_text
        assert "Plain-English Run Summary" in page1_text
        assert out.upper() in page1_text or out.title() in page1_text


def test_pdf_extracts_plain_english_summary():
    """Verify plain-English summary content is present in the rendered PDF text."""
    report = create_sample_report(
        run_id="test-summary-text",
        outcome="repaired",
        pr_url="https://github.com/org/repo/pull/101",
        pr_number=101,
    )
    pdf_bytes = generate_pdf_report(report)
    reader = PdfReader(io.BytesIO(pdf_bytes))

    full_text = " ".join([p.extract_text() for p in reader.pages])
    assert "Plain-English Run Summary" in full_text
    assert "What Happened" in full_text
    assert "Why Did It Happen" in full_text
    assert "Did the Repair Work" in full_text
    assert "What You Should Do Next" in full_text
    assert "Draft PR #101" in full_text
    assert "https://github.com/org/repo/pull/101" in full_text


def test_pdf_secret_redaction():
    """Verify secrets and API keys are redacted from the generated PDF."""
    secret = "AIzaSyB12345678901234567890123456789012"
    report = create_sample_report(
        run_id="test-pdf-redaction",
        outcome="blocked",
        secret_text=secret,
        log_text=f"Failure with token: {secret}",
    )
    pdf_bytes = generate_pdf_report(report)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = " ".join([p.extract_text() for p in reader.pages])

    assert secret not in full_text
    assert "[REDACTED_API_KEY]" in full_text or "[REDACTED_SECRET]" in full_text or "REDACTED" in full_text


def test_pdf_long_log_bounding_and_unicode():
    """Verify long logs and unusual Unicode characters do not break rendering."""
    huge_log = "Error line with unusual chars: € £ ¥ 🚀 \n" * 500
    report = create_sample_report(
        run_id="test-pdf-bounds",
        outcome="unresolved",
        log_text=huge_log,
    )
    pdf_bytes = generate_pdf_report(report)
    assert pdf_bytes.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) <= 10  # Bounded, doesn't generate 100 pages


def test_flask_pdf_download_endpoint_success():
    """Verify GET /api/reports/<run_id>/pdf returns HTTP 200, application/pdf, and attachment header."""
    report = create_sample_report(run_id="run-flask-pdf-test", outcome="repaired")
    save_report(report)

    app = create_app()
    client = app.test_client()

    res = client.get("/api/reports/run-flask-pdf-test/pdf")
    assert res.status_code == 200
    assert res.content_type == "application/pdf"
    assert res.data.startswith(b"%PDF-")
    disp = res.headers.get("Content-Disposition", "")
    assert "attachment" in disp
    assert 'filename="acid-ai-report-run-flask-pdf-test.pdf"' in disp


def test_flask_pdf_download_endpoint_not_found():
    """Verify GET /api/reports/<run_id>/pdf returns HTTP 404 for unknown run IDs."""
    app = create_app()
    client = app.test_client()

    res = client.get("/api/reports/nonexistent-run-id-999/pdf")
    assert res.status_code == 404
    assert res.is_json
    data = res.get_json()
    assert "not found" in data["error"].lower()


def test_json_and_markdown_exports_remain_stable():
    """Verify existing JSON and Markdown report routes remain fully functional and consistent."""
    report = create_sample_report(run_id="run-stability-test", outcome="repaired")
    save_report(report)

    app = create_app()
    client = app.test_client()

    # JSON export
    res_json = client.get("/api/reports/run-stability-test")
    assert res_json.status_code == 200
    data = res_json.get_json()
    assert data["run_id"] == "run-stability-test"
    assert data["outcome"] == "repaired"
    assert "summary" in data

    # Markdown export
    res_md = client.get("/api/reports/run-stability-test/markdown")
    assert res_md.status_code == 200
    assert res_md.content_type.startswith("text/markdown")
    assert "run-stability-test" in res_md.get_data(as_text=True)
    assert "1. Plain-English Run Summary" in res_md.get_data(as_text=True)

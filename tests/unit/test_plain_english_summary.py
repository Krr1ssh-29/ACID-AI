"""Comprehensive unit tests for Plain-English Run Summary generation.

Verifies:
1. All 5 canonical outcomes: healthy, repaired, partially repaired, unresolved, blocked.
2. Accurate attempt counts and stop reasons.
3. Distinction between proposed, applied, and verified patches.
4. Correct publication status mappings.
5. No false success language.
6. Secret redaction and untrusted content handling.
7. Graceful fallbacks when evidence or diagnosis is missing.
"""
from agent.models import (
    RunRecord,
    FinalReport,
    PlainEnglishSummary,
)
from agent.report import generate_plain_english_summary, build_report_markdown


def make_dummy_run_record(
    run_id: str = "run-test-123",
    final_status: str = "unresolved",
    retry_count: int = 1,
    stop_reason: str = "Max attempts reached.",
    is_healthy: bool = False,
    pub_status: str = "none",
    pr_url: str = None,
    pr_number: int = None,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        repo_path="/test/repo",
        repo_name="test-repo",
        branch="main",
        base_commit="abc1234",
        short_sha="abc1234",
        mode="real",
        status="VERIFIED" if final_status in ("healthy", "repaired") else "FAILED",
        final_status=final_status,
        stop_reason=stop_reason,
        retry_count=retry_count,
        created_at="2026-10-23 10:00:00",
        completed_at="2026-10-23 10:00:05",
        elapsed_seconds=5.0,
        is_healthy=is_healthy,
        publication={
            "status": pub_status,
            "display": pub_status,
            "message": f"Publication status: {pub_status}",
            "pr_url": pr_url,
            "pr_number": pr_number,
        },
    )


def test_summary_healthy_outcome():
    """Verify healthy outcome summary contains zero-token bypass notice and no repair false claims."""
    rec = make_dummy_run_record(final_status="healthy", is_healthy=True, retry_count=0, stop_reason="Pipeline healthy.")
    rep_data = {"outcome": "healthy", "retry_count": 0, "stop_reason": "Pipeline healthy."}

    summary = generate_plain_english_summary(rec, rep_data)
    assert summary["overall_outcome"] == "healthy"
    assert "Healthy" in summary["overall_outcome_text"]
    assert "passed" in summary["what_happened"].lower()
    assert "zero tokens" in summary["why_it_happened"].lower() or "no failure" in summary["why_it_happened"].lower()
    assert "0" in summary["what_acid_attempted"] or "no repair" in summary["what_acid_attempted"].lower()
    assert "not needed" in summary["did_repair_work"].lower()
    assert "no action" in summary["what_to_do_next"].lower()
    assert "skipped" in summary["publication_status"].lower()
    # Pydantic validation
    validated = PlainEnglishSummary(**summary)
    assert validated.overall_outcome == "healthy"


def test_summary_repaired_outcome():
    """Verify repaired outcome summary accurately describes verified repairs and PR details."""
    rec = make_dummy_run_record(
        final_status="repaired",
        is_healthy=True,
        retry_count=1,
        stop_reason="All required checks passed after verified repair.",
        pub_status="published",
        pr_url="https://github.com/org/repo/pull/42",
        pr_number=42,
    )
    rep_data = {
        "outcome": "repaired",
        "retry_count": 1,
        "stop_reason": "All required checks passed after verified repair.",
        "changed_files": ["app.py"],
        "publication": {
            "status": "published",
            "pr_url": "https://github.com/org/repo/pull/42",
            "pr_number": 42,
        },
    }

    summary = generate_plain_english_summary(rec, rep_data)
    assert summary["overall_outcome"] == "repaired"
    assert "Repaired" in summary["overall_outcome_text"]
    assert "isolated container" in summary["did_repair_work"].lower()
    assert summary["pr_url"] == "https://github.com/org/repo/pull/42"
    assert summary["pr_number"] == 42
    assert "Draft PR #42" in summary["publication_status"]
    assert "app.py" in summary["what_acid_attempted"]
    # Pydantic validation
    validated = PlainEnglishSummary(**summary)
    assert validated.overall_outcome == "repaired"


def test_summary_partially_repaired_outcome():
    """Verify partially repaired outcome clarifies that some tests passed but others remain."""
    rec = make_dummy_run_record(
        final_status="partially repaired",
        retry_count=2,
        stop_reason="Retry budget exhausted: Verified 1 patch, but remaining failures unresolved.",
    )
    rep_data = {
        "outcome": "partially repaired",
        "retry_count": 2,
        "stop_reason": "Retry budget exhausted: Verified 1 patch, but remaining failures unresolved.",
    }

    summary = generate_plain_english_summary(rec, rep_data)
    assert summary["overall_outcome"] == "partially repaired"
    assert "Partially repaired" in summary["overall_outcome_text"]
    assert "partially" in summary["did_repair_work"].lower()
    assert "unresolved failures" in summary["what_to_do_next"].lower()
    assert "blocked" in summary["publication_status"].lower() or "skipped" in summary["publication_status"].lower()


def test_summary_unresolved_outcome():
    """Verify unresolved outcome never claims success and warns user to inspect failures."""
    rec = make_dummy_run_record(
        final_status="unresolved",
        retry_count=3,
        stop_reason="Retry budget exhausted: Candidate patches failed verification across 3 attempts.",
    )
    rep_data = {
        "outcome": "unresolved",
        "retry_count": 3,
        "stop_reason": "Retry budget exhausted: Candidate patches failed verification across 3 attempts.",
    }

    summary = generate_plain_english_summary(rec, rep_data)
    assert summary["overall_outcome"] == "unresolved"
    assert "Unresolved" in summary["overall_outcome_text"]
    assert "did not pass" in summary["did_repair_work"].lower() or "unverified" in summary["did_repair_work"].lower()
    assert "manual" in summary["what_to_do_next"].lower() or "inspect" in summary["what_to_do_next"].lower()
    assert "blocked" in summary["publication_status"].lower()


def test_summary_blocked_outcome():
    """Verify blocked outcome highlights missing credentials or infrastructure without false diff claims."""
    rec = make_dummy_run_record(
        final_status="blocked",
        retry_count=1,
        stop_reason="Live AI diagnosis unavailable: No GEMINI_API_KEY configured.",
    )
    rep_data = {
        "outcome": "blocked",
        "retry_count": 1,
        "stop_reason": "Live AI diagnosis unavailable: No GEMINI_API_KEY configured.",
    }

    summary = generate_plain_english_summary(rec, rep_data)
    assert summary["overall_outcome"] == "blocked"
    assert "Blocked" in summary["overall_outcome_text"]
    assert "not executed" in summary["did_repair_work"].lower() or "refused" in summary["did_repair_work"].lower()
    assert "configure" in summary["what_to_do_next"].lower() or "missing" in summary["what_to_do_next"].lower()


def test_summary_secret_redaction():
    """Verify secrets and API keys are redacted from summaries."""
    secret_key = "AIzaSyB12345678901234567890123456789012"
    rec = make_dummy_run_record(
        final_status="blocked",
        stop_reason=f"Error connecting with key {secret_key}",
    )
    rep_data = {
        "outcome": "blocked",
        "stop_reason": f"Error connecting with key {secret_key}",
        "root_cause": f"Found key {secret_key}",
    }

    summary = generate_plain_english_summary(rec, rep_data)
    for field in ("what_happened", "why_it_happened", "why_agent_stopped", "what_acid_attempted"):
        assert secret_key not in summary[field], f"Secret leaked in field {field}"


def test_summary_contract_ambiguity_representation():
    """Verify contract ambiguity is truthfully highlighted in plain-English summary."""
    ambiguous_stop = (
        "Contract ambiguity: Repository evidence does not establish whether "
        "implementation or test defines the intended contract."
    )
    ambiguous_root = (
        "Contract ambiguity detected between test and implementation: "
        "Test asserts add(2, 2) == 5 while add returns 4."
    )
    rec = make_dummy_run_record(
        final_status="unresolved",
        stop_reason=ambiguous_stop,
    )
    rep_data = {
        "outcome": "unresolved",
        "stop_reason": ambiguous_stop,
        "root_cause": ambiguous_root,
    }

    summary = generate_plain_english_summary(rec, rep_data)
    assert summary["overall_outcome"] == "unresolved"
    assert "contract ambiguity" in summary["why_it_happened"].lower()
    assert "contract" in summary["what_to_do_next"].lower() or "specification" in summary["what_to_do_next"].lower()


def test_markdown_renders_plain_english_summary():
    """Verify Section 1 of the Markdown report contains the plain-English summary block."""
    outcome_text = (
        "Repaired — a repair was applied in the disposable workspace and passed required verification."
    )
    final_rep = FinalReport(
        run_id="run-markdown-test",
        repository="test-repo",
        repo_path="/path/test",
        branch="main",
        base_commit="1234567",
        short_sha="1234567",
        outcome="repaired",
        mode="real",
        created_at="2026-10-23 10:00:00",
        completed_at="2026-10-23 10:00:10",
        elapsed_seconds=10.0,
        initial_checks={"stages": [], "failures_detected": []},
        diagnosis={
            "severity": "medium",
            "failure_types": ["test"],
            "root_cause": "Test index endpoint assertion failed.",
            "fixes": [],
            "prevention": "Check endpoint.",
            "confidence": "high",
            "log_evidence": "assert 4 == 5",
        },
        candidate_patches=[],
        repair_attempts=[],
        verification={
            "final_status": "VERIFIED_SUCCESS",
            "commands_executed": ["pytest"],
            "all_passed": True,
            "isolation_type": "Docker",
            "host_mutated": False,
        },
        retry_count=1,
        stop_reason="All required checks passed after verified repair.",
        unresolved_issues=[],
        publication={
            "outcome": "successful",
            "raw_status": "published",
            "branch": "acid-ai/repair",
            "pr_url": "https://github.com/org/repo/pull/99",
            "pr_number": 99,
            "message": "Published draft PR",
        },
        changed_files=["app.py"],
        verification_scope_statement="Verification Scope: Candidate code verified in container.",
        summary={
            "overall_outcome": "repaired",
            "overall_outcome_text": outcome_text,
            "what_happened": "Test check failed on index endpoint.",
            "why_it_happened": "Index endpoint returned unexpected string.",
            "what_acid_attempted": "Attempted 1 patch modifying app.py.",
            "did_repair_work": "Yes — verified in isolated container.",
            "why_agent_stopped": "All checks passed.",
            "what_to_do_next": "Review Draft PR #99.",
            "publication_status": "Draft PR #99 created (https://github.com/org/repo/pull/99)",
            "pr_url": "https://github.com/org/repo/pull/99",
            "pr_number": 99,
        },
    )

    md = build_report_markdown(final_rep)
    assert "ACID AI — Execution & Repair Report" in md
    assert "## 1. Plain-English Run Summary" in md
    assert "Overall Outcome" in md
    assert "Did the Repair Work" in md
    assert "What You Should Do Next" in md
    assert "Draft PR #99" in md

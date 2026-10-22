"""Tests for Pull Request comment formatting in agent.formatter."""
from agent.formatter import format_pr_comment


def test_format_pr_comment_basic_structure():
    """Verify core sections of formatted PR comment markdown."""
    analysis = {
        "severity": "high",
        "confidence": "high",
        "failure_types": ["test"],
        "root_cause": "test_index_endpoint assertion failed.",
        "fixes": [
            {
                "title": "Fix status check",
                "description": "Align return value in app.py",
                "code": "return jsonify({'status': 'healthy'}), 200",
            }
        ],
        "prevention": "Add regression test before deployment.",
    }
    comment = format_pr_comment(
        analysis=analysis,
        commit_sha="abcdef1234567890",
        run_id="987654321",
        repo="my-org/my-repo",
        ai_provider="claude",
    )

    assert "## 🤖 ACID AI — Pipeline Analysis" in comment
    assert "`abcdef12`" in comment
    assert "🟠 `HIGH`" in comment
    assert "✅ `high`" in comment
    assert "🟣 `Anthropic Claude Sonnet`" in comment
    assert "### 🔍 Failure Types Detected" in comment
    assert "`test`" in comment
    assert "### 🧠 Root Cause Analysis" in comment
    assert "test_index_endpoint assertion failed." in comment
    assert "### 🛠️ Suggested Fixes" in comment
    assert "#### Fix 1: Fix status check" in comment
    assert "```bash\nreturn jsonify({'status': 'healthy'}), 200\n```" in comment
    assert "### 🛡️ Prevention" in comment
    assert "Add regression test before deployment." in comment
    assert "<summary>📋 Pipeline Run Details</summary>" in comment
    assert "[987654321](https://github.com/my-org/my-repo/actions/runs/987654321)" in comment


def test_format_pr_comment_gemini_provider():
    """Verify Gemini provider badge and label formatting."""
    analysis = {
        "severity": "critical",
        "confidence": "low",
        "failure_types": ["docker", "install"],
        "root_cause": "Dockerfile missing requirements file.",
        "fixes": [],
    }
    comment = format_pr_comment(
        analysis=analysis,
        commit_sha="1122334455667788",
        run_id="55555",
        repo="test/repo",
        ai_provider="gemini",
    )
    assert "🔴 `CRITICAL`" in comment
    assert "❓ `low`" in comment
    assert "🔵 `Google Gemini 2.5 Flash`" in comment
    assert "`docker`" in comment
    assert "`install`" in comment


def test_format_pr_comment_string_failure_types():
    """Verify handling when failure_types is a comma-separated string."""
    analysis = {
        "severity": "medium",
        "failure_types": "lint, install",
        "root_cause": "Style error and missing package.",
    }
    comment = format_pr_comment(
        analysis=analysis,
        commit_sha="99887766",
        run_id="111",
        repo="test/repo",
    )
    assert "`lint`" in comment
    assert "`install`" in comment
    assert "🟡 `MEDIUM`" in comment

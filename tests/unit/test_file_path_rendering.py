"""Unit tests for candidate file path formatting and [object Object] prevention (QA Fix 2).

Verifies:
1. String-based candidate-file entries.
2. Structured candidate-file entries (FilePatch objects, dictionaries with 'path', 'name', 'target_path').
3. Multiple changed files formatted cleanly as comma-separated paths.
4. No candidate files gracefully returning 'None'.
5. Unexpected or malformed file metadata handled without leaking [object Object] or crashing.
"""
from agent.models import FilePatch, PatchProposal, PatchStatus
from agent.report import format_file_list


def test_format_file_list_strings():
    """Verify list of plain strings renders cleanly."""
    assert format_file_list(["app.py"]) == "app.py"
    assert format_file_list(["src/app.py", "tests/test_app.py"]) == "src/app.py, tests/test_app.py"
    assert format_file_list("app.py") == "app.py"


def test_format_file_list_structured_file_patch_objects():
    """Verify list of FilePatch pydantic objects extracts paths without [object Object]."""
    fp1 = FilePatch(path="app.py", status="modified", additions=2, deletions=1)
    fp2 = FilePatch(path="tests/test_main.py", status="modified", additions=5, deletions=0)
    assert format_file_list([fp1, fp2]) == "app.py, tests/test_main.py"
    assert format_file_list(fp1) == "app.py"


def test_format_file_list_dictionaries():
    """Verify serialized dictionary models from model_dump() format cleanly."""
    dict_list = [
        {"path": "app.py", "status": "modified", "additions": 1},
        {"path": "tests/test_app.py", "status": "modified", "additions": 1},
    ]
    assert format_file_list(dict_list) == "app.py, tests/test_app.py"

    # Single dictionary
    assert format_file_list({"path": "sample.py"}) == "sample.py"
    assert format_file_list({"name": "sample.py"}) == "sample.py"
    assert format_file_list({"target_path": "sample.py"}) == "sample.py"
    assert format_file_list({"file_path": "sample.py"}) == "sample.py"


def test_format_file_list_empty_and_none():
    """Verify empty or None inputs return 'None'."""
    assert format_file_list(None) == "None"
    assert format_file_list([]) == "None"
    assert format_file_list("") == "None"
    assert format_file_list("   ") == "None"
    assert format_file_list({}) == "None"


def test_format_file_list_malformed_and_mixed():
    """Verify mixed and unexpected types are handled without leaking [object Object]."""
    mixed = ["app.py", None, {"path": "main.py"}, "", {"unknown_key": "val"}]
    rendered = format_file_list(mixed)
    assert "[object Object]" not in rendered
    assert "app.py" in rendered
    assert "main.py" in rendered

    # Non-standard types
    assert format_file_list(12345) == "None"
    assert format_file_list([None, None]) == "None"


def test_patch_proposal_model_dump_compatibility():
    """Verify full PatchProposal with multiple files serializes and formats properly."""
    fp1 = FilePatch(path="frontend/app.js", status="modified")
    fp2 = FilePatch(path="frontend/style.css", status="modified")
    proposal = PatchProposal(
        status=PatchStatus.VALIDATED,
        explanation="Update UI",
        diff="--- a/frontend/app.js\n+++ b/frontend/app.js",
        files=[fp1, fp2],
    )
    dumped = proposal.model_dump()
    assert format_file_list(dumped["files"]) == "frontend/app.js, frontend/style.css"

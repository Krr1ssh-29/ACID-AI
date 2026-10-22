"""Unit tests for patch safety policy validator and diff parser in agent.validator."""
import pytest
from agent.validator import (
    parse_unified_diff,
    validate_patch,
    validate_file_path,
    MalformedDiffError,
    BinaryPatchError,
)
from agent.models import AnalysisResult, FixSuggestion


SAMPLE_VALID_DIFF = """--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -10,4 +10,4 @@
 def health():
-    return {"status": "broken"}
+    return {"status": "ok"}
"""

SAMPLE_MULTI_FILE_DIFF = """--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -10,3 +10,3 @@
-old_app_line
+new_app_line
--- a/sample-app/tests/test_app.py
+++ b/sample-app/tests/test_app.py
@@ -5,3 +5,3 @@
-old_test_line
+new_test_line
"""

SAMPLE_ADD_FILE_DIFF = """--- /dev/null
+++ b/sample-app/new_module.py
@@ -0,0 +1,3 @@
+def helper():
+    return True
"""


def test_parse_unified_diff_valid_single_file():
    """Verify parsing of standard single-file unified diff."""
    patches = parse_unified_diff(SAMPLE_VALID_DIFF)
    assert len(patches) == 1
    p = patches[0]
    assert p.path == "sample-app/app.py"
    assert p.original_path == "sample-app/app.py"
    assert p.target_path == "sample-app/app.py"
    assert p.additions == 1
    assert p.deletions == 1
    assert p.hunks_count == 1
    assert p.status == "modified"


def test_parse_unified_diff_multi_file():
    """Verify parsing of unified diff spanning multiple files."""
    patches = parse_unified_diff(SAMPLE_MULTI_FILE_DIFF)
    assert len(patches) == 2
    assert patches[0].path == "sample-app/app.py"
    assert patches[1].path == "sample-app/tests/test_app.py"


def test_parse_unified_diff_added_file():
    """Verify parsing of newly created file diff."""
    patches = parse_unified_diff(SAMPLE_ADD_FILE_DIFF)
    assert len(patches) == 1
    assert patches[0].path == "sample-app/new_module.py"
    assert patches[0].original_path == "/dev/null"
    assert patches[0].status == "added"
    assert patches[0].additions == 2
    assert patches[0].deletions == 0


def test_validate_patch_empty():
    """Verify empty or blank diff is rejected with EMPTY_PATCH."""
    res = validate_patch("")
    assert not res.is_valid
    assert any(e.code == "EMPTY_PATCH" for e in res.errors)

    res_ws = validate_patch("   \n\n  ")
    assert not res_ws.is_valid
    assert any(e.code == "EMPTY_PATCH" for e in res_ws.errors)


def test_validate_patch_malformed_headers():
    """Verify malformed diff headers are rejected with MALFORMED_DIFF."""
    bad_diff = "--- a/sample-app/app.py\n@@ -1,3 +1,3 @@\n-line\n+line"
    res = validate_patch(bad_diff)
    assert not res.is_valid
    assert any(e.code == "MALFORMED_DIFF" for e in res.errors)


def test_validate_patch_invalid_hunk_header():
    """Verify corrupted hunk header is rejected with MALFORMED_DIFF."""
    bad_diff = "--- a/sample-app/app.py\n+++ b/sample-app/app.py\n@@ invalid @@\n-line\n+line"
    res = validate_patch(bad_diff)
    assert not res.is_valid
    assert any(e.code == "MALFORMED_DIFF" for e in res.errors)


def test_validate_patch_binary_diff_forbidden():
    """Verify binary file modifications are strictly rejected."""
    binary_diff = "Binary files a/sample-app/logo.png and b/sample-app/logo.png differ"
    res = validate_patch(binary_diff)
    assert not res.is_valid
    assert any(e.code == "BINARY_PATCH_FORBIDDEN" for e in res.errors)


def test_validate_patch_file_deletion_forbidden():
    """Verify file deletion is rejected by policy."""
    del_diff = """--- a/sample-app/app.py
+++ /dev/null
@@ -1,5 +0,0 @@
-def app():
-    pass
"""
    res = validate_patch(del_diff)
    assert not res.is_valid
    assert any(e.code == "FILE_DELETION_FORBIDDEN" for e in res.errors)


def test_validate_patch_excessive_files_limit():
    """Verify patches modifying more than max_files are rejected."""
    diff_chunks = []
    for i in range(6):
        diff_chunks.append(f"""--- a/sample-app/module_{i}.py
+++ b/sample-app/module_{i}.py
@@ -1,2 +1,2 @@
-x_{i} = 1
+x_{i} = 2
""")
    res = validate_patch("\n".join(diff_chunks), max_files=5)
    assert not res.is_valid
    assert any(e.code == "EXCESSIVE_FILES_CHANGED" for e in res.errors)


def test_validate_patch_excessive_lines_limit():
    """Verify patches modifying more than max_lines are rejected."""
    adds = "\n".join([f"+line_{i}" for i in range(160)])
    oversized_diff = f"""--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -1,1 +1,161 @@
-original
{adds}
"""
    res = validate_patch(oversized_diff, max_lines=150)
    assert not res.is_valid
    assert any(e.code == "EXCESSIVE_LINES_MODIFIED" for e in res.errors)


def test_validate_patch_absolute_paths_forbidden():
    """Verify absolute paths are rejected."""
    abs_diff = """--- /etc/passwd
+++ /etc/passwd
@@ -1,1 +1,1 @@
-root:x:0:0
+root:x:0:1
"""
    res = validate_patch(abs_diff)
    assert not res.is_valid
    assert any(e.code == "ABSOLUTE_PATH_FORBIDDEN" for e in res.errors)


def test_validate_patch_path_traversal_forbidden():
    """Verify directory traversal sequences are rejected."""
    traversal_diff = """--- a/sample-app/../../outside.py
+++ b/sample-app/../../outside.py
@@ -1,1 +1,1 @@
-old
+new
"""
    res = validate_patch(traversal_diff)
    assert not res.is_valid
    assert any(e.code == "PATH_TRAVERSAL_DETECTED" for e in res.errors)


def test_validate_patch_prohibited_github_workflows():
    """Verify attempts to modify .github workflows are strictly rejected (Threat T-03)."""
    workflow_diff = """--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,3 +1,3 @@
-permissions: read-all
+permissions: write-all
"""
    res = validate_patch(workflow_diff)
    assert not res.is_valid
    assert any(e.code == "PROHIBITED_FILE_MODIFICATION" for e in res.errors)


def test_validate_patch_prohibited_git_internals():
    """Verify attempts to modify .git internals are strictly rejected."""
    git_diff = """--- a/.git/config
+++ b/.git/config
@@ -1,2 +1,2 @@
-bare = false
+bare = true
"""
    res = validate_patch(git_diff)
    assert not res.is_valid
    assert any(e.code == "PROHIBITED_FILE_MODIFICATION" for e in res.errors)


def test_validate_patch_prohibited_secrets_and_credentials():
    """Verify sensitive files (.env, id_rsa, keys) are strictly rejected."""
    for bad_path in (".env", ".env.production", "secrets.json", "id_rsa", "auth_token.txt"):
        diff = f"""--- a/{bad_path}
+++ b/{bad_path}
@@ -1,1 +1,1 @@
-old
+new
"""
        res = validate_patch(diff)
        assert not res.is_valid, f"Expected {bad_path} to be rejected"
        assert any(e.code == "PROHIBITED_FILE_MODIFICATION" for e in res.errors)


def test_validate_patch_path_not_allowlisted():
    """Verify unapproved paths outside allowlisted application/test folders are rejected."""
    unapproved_diff = """--- a/scripts/arbitrary_tool.sh
+++ b/scripts/arbitrary_tool.sh
@@ -1,2 +1,2 @@
-echo 1
+echo 2
"""
    res = validate_patch(unapproved_diff)
    assert not res.is_valid
    assert any(e.code == "PATH_NOT_ALLOWLISTED" for e in res.errors)


def test_validate_patch_dependency_manifest_allowed_with_warning():
    """Verify modifying requirements.txt is allowed within allowlist but produces Threat T-11 warning."""
    req_diff = """--- a/requirements.txt
+++ b/requirements.txt
@@ -1,2 +1,2 @@
-flask==3.0.0
+flask==3.1.0
"""
    res = validate_patch(req_diff)
    assert res.is_valid
    assert len(res.warnings) >= 1
    assert "Threat T-11" in res.warnings[0]


def test_validate_patch_contradictory_hunks():
    """Verify contradictory file entries on same file are rejected."""
    contra_diff = """--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -1,2 +1,2 @@
-a
+b
--- /dev/null
+++ b/sample-app/app.py
@@ -0,0 +1,2 @@
+new
"""
    res = validate_patch(contra_diff)
    assert not res.is_valid
    assert any(e.code == "CONTRADICTORY_PATCH" for e in res.errors)


def test_validate_patch_repository_state_match_success(tmp_path):
    """Verify patch matches existing file content on disk without modifying it."""
    app_dir = tmp_path / "sample-app"
    app_dir.mkdir(parents=True)
    target_file = app_dir / "app.py"
    target_file.write_text("line 1\ndef broken():\n    return False\nline 4\n", encoding="utf-8")

    diff = """--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -2,2 +2,2 @@
 def broken():
-    return False
+    return True
"""
    res = validate_patch(diff, repo_root=str(tmp_path))
    assert res.is_valid
    assert len(res.errors) == 0

    # Ensure working tree was NOT modified
    content_after = target_file.read_text(encoding="utf-8")
    assert "return False" in content_after
    assert "return True" not in content_after


def test_validate_patch_repository_state_target_not_found(tmp_path):
    """Verify patch referencing non-existent file on disk is rejected."""
    diff = """--- a/sample-app/missing.py
+++ b/sample-app/missing.py
@@ -1,2 +1,2 @@
-old
+new
"""
    res = validate_patch(diff, repo_root=str(tmp_path))
    assert not res.is_valid
    assert any(e.code == "TARGET_FILE_NOT_FOUND" for e in res.errors)


def test_validate_patch_repository_state_content_mismatch(tmp_path):
    """Verify patch referencing mismatched file content is rejected."""
    app_dir = tmp_path / "sample-app"
    app_dir.mkdir(parents=True)
    target_file = app_dir / "app.py"
    target_file.write_text("actual line 1\nactual line 2\n", encoding="utf-8")

    diff = """--- a/sample-app/app.py
+++ b/sample-app/app.py
@@ -1,2 +1,2 @@
-completely wrong line
+replacement
"""
    res = validate_patch(diff, repo_root=str(tmp_path))
    assert not res.is_valid
    assert any(e.code == "PATCH_STATE_MISMATCH" for e in res.errors)


def test_validate_patch_added_file_already_exists(tmp_path):
    """Verify creating a file that already exists on disk is rejected."""
    app_dir = tmp_path / "sample-app"
    app_dir.mkdir(parents=True)
    existing_file = app_dir / "new_module.py"
    existing_file.write_text("already here", encoding="utf-8")

    res = validate_patch(SAMPLE_ADD_FILE_DIFF, repo_root=str(tmp_path))
    assert not res.is_valid
    assert any(e.code == "FILE_ALREADY_EXISTS" for e in res.errors)


def test_parse_unified_diff_exceptions():
    """Verify parse_unified_diff raises MalformedDiffError and BinaryPatchError directly."""
    with pytest.raises(BinaryPatchError, match="Binary files diff"):
        parse_unified_diff("Binary files a/b and b/b differ")

    with pytest.raises(MalformedDiffError, match="No valid hunks"):
        parse_unified_diff("--- a/sample-app/app.py\n+++ b/sample-app/app.py\n")


def test_validate_file_path_direct():
    """Verify validate_file_path detects absolute paths and traversal directly."""
    errs = validate_file_path("/abs/path/file.py")
    assert any(e.code == "ABSOLUTE_PATH_FORBIDDEN" for e in errs)

    errs_trav = validate_file_path("sample-app/../../etc/passwd")
    assert any(e.code == "PATH_TRAVERSAL_DETECTED" for e in errs_trav)


def test_validate_patch_with_diagnosis_context():
    """Verify validate_patch accepts Phase 03 AnalysisResult diagnosis."""
    diagnosis = AnalysisResult(
        severity="medium",
        failure_types=["lint"],
        root_cause="Line length exceeded 120 chars in app.py",
        fixes=[
            FixSuggestion(
                type="lint",
                title="Wrap long line",
                description="Break long string into multi-line tuple",
                code="long_str = (\n    'line 1'\n    'line 2'\n)",
            )
        ],
        prevention="Run flake8 locally",
        confidence="high",
    )
    res = validate_patch(SAMPLE_VALID_DIFF, diagnosis=diagnosis)
    assert res.is_valid

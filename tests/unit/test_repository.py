"""Unit tests for repository inspection, Git metadata extraction, and disposable workspace isolation."""
import os
import shutil
import tempfile
from unittest.mock import patch

from agent.repository import (
    validate_repository,
    create_disposable_workspace,
    disposable_working_copy,
    _inspect_git_via_fs,
)
from agent.models import RepositoryMetadata, RunRecord


def test_validate_repository_current_workspace():
    """Verify validate_repository truthfully identifies the current Git repository."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    meta = validate_repository(repo_root)

    assert isinstance(meta, RepositoryMetadata)
    assert meta.is_git is True
    assert meta.name == os.path.basename(repo_root)
    assert meta.path.lower() == repo_root.lower()
    assert meta.branch != "unknown"
    assert len(meta.base_commit) == 40  # Full 40-char SHA
    assert meta.short_sha == meta.base_commit[:8]
    assert meta.error is None
    assert meta.has_tests is True
    assert meta.has_manifest is True
    assert any("requirements.txt" in df for df in meta.detected_files)


def test_validate_repository_empty_path():
    """Verify empty or whitespace-only paths return a clean validation error."""
    meta1 = validate_repository("")
    assert meta1.is_git is False
    assert "cannot be empty" in meta1.error

    meta2 = validate_repository("   ")
    assert meta2.is_git is False
    assert "cannot be empty" in meta2.error


def test_validate_repository_nonexistent_path():
    """Verify nonexistent paths return a clean error without throwing unhandled exceptions."""
    nonexistent = os.path.join(tempfile.gettempdir(), "nonexistent_repo_dir_abc123")
    meta = validate_repository(nonexistent)

    assert meta.is_git is False
    assert "does not exist" in meta.error


def test_validate_repository_file_not_directory():
    """Verify pointing to a plain file returns an invalid directory error."""
    this_file = os.path.abspath(__file__)
    meta = validate_repository(this_file)

    assert meta.is_git is False
    assert "is not a directory" in meta.error


def test_validate_repository_directory_without_git():
    """Verify plain directories without .git return a truthful non-git repository error."""
    temp_dir = tempfile.mkdtemp(prefix="non-git-dir-")
    try:
        meta = validate_repository(temp_dir)
        assert meta.is_git is False
        assert "not a valid Git repository" in meta.error
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_create_disposable_workspace_excludes_sensitive_files():
    """Verify disposable workspace copy excludes .git, .env, .venv, and caches."""
    source_dir = tempfile.mkdtemp(prefix="source-repo-")
    try:
        # Create normal project files
        os.makedirs(os.path.join(source_dir, "src"), exist_ok=True)
        with open(os.path.join(source_dir, "src", "app.py"), "w") as f:
            f.write("print('hello')")

        # Create sensitive and ignored items
        os.makedirs(os.path.join(source_dir, ".git"), exist_ok=True)
        os.makedirs(os.path.join(source_dir, ".venv"), exist_ok=True)
        os.makedirs(os.path.join(source_dir, "__pycache__"), exist_ok=True)
        with open(os.path.join(source_dir, ".env"), "w") as f:
            f.write("SECRET_KEY=123")

        workspace = create_disposable_workspace(source_dir)
        try:
            assert os.path.isfile(os.path.join(workspace, "src", "app.py"))
            assert not os.path.exists(os.path.join(workspace, ".git"))
            assert not os.path.exists(os.path.join(workspace, ".venv"))
            assert not os.path.exists(os.path.join(workspace, ".env"))
            assert not os.path.exists(os.path.join(workspace, "__pycache__"))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


def test_disposable_working_copy_zero_host_mutation():
    """Verify disposable_working_copy context manager guarantees zero mutation of source repository."""
    source_dir = tempfile.mkdtemp(prefix="source-immutability-")
    try:
        target_file = os.path.join(source_dir, "service.py")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("def run():\n    return 'original_content'\n")

        created_workspace = None
        with disposable_working_copy(source_dir) as workspace:
            created_workspace = workspace
            assert os.path.isdir(workspace)

            # Mutate the file inside the disposable copy
            disp_file = os.path.join(workspace, "service.py")
            with open(disp_file, "w", encoding="utf-8") as f:
                f.write("def run():\n    return 'heavily_modified_patch'\n")

            # Create new file in disposable copy
            with open(os.path.join(workspace, "extra.py"), "w", encoding="utf-8") as f:
                f.write("extra = True")

            # Verify mutation in disposable copy
            with open(disp_file, "r", encoding="utf-8") as f:
                assert "heavily_modified_patch" in f.read()

        # Context manager exited: workspace must be deleted
        assert not os.path.exists(created_workspace)

        # Source repository must be completely untouched!
        with open(target_file, "r", encoding="utf-8") as f:
            assert f.read() == "def run():\n    return 'original_content'\n"
        assert not os.path.exists(os.path.join(source_dir, "extra.py"))
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


def test_disposable_working_copy_cleanup_on_exception():
    """Verify disposable workspace is destroyed even if an exception occurs during execution."""
    source_dir = tempfile.mkdtemp(prefix="source-exc-")
    workspace_path = None
    try:
        with open(os.path.join(source_dir, "app.py"), "w") as f:
            f.write("print(1)")

        try:
            with disposable_working_copy(source_dir) as ws:
                workspace_path = ws
                assert os.path.isdir(workspace_path)
                raise RuntimeError("Simulated failure during analysis")
        except RuntimeError:
            pass

        # Workspace must be removed
        assert not os.path.exists(workspace_path)
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


def test_inspect_git_via_fs_fallback():
    """Verify direct .git directory parsing as fallback when git CLI is unavailable."""
    temp_repo = tempfile.mkdtemp(prefix="git-fs-fallback-")
    try:
        dot_git = os.path.join(temp_repo, ".git")
        os.makedirs(os.path.join(dot_git, "refs", "heads"), exist_ok=True)

        # Write HEAD pointing to ref
        with open(os.path.join(dot_git, "HEAD"), "w", encoding="utf-8") as f:
            f.write("ref: refs/heads/feature-repair\n")

        # Write commit SHA into ref file
        fake_sha = "a" * 40
        with open(os.path.join(dot_git, "refs", "heads", "feature-repair"), "w", encoding="utf-8") as f:
            f.write(fake_sha + "\n")

        info = _inspect_git_via_fs(temp_repo)
        assert info is not None
        assert info["branch"] == "feature-repair"
        assert info["base_commit"] == fake_sha

        # Test with git CLI returning None
        with patch("agent.repository._inspect_git_via_cli", return_value=None):
            meta = validate_repository(temp_repo)
            assert meta.is_git is True
            assert meta.branch == "feature-repair"
            assert meta.base_commit == fake_sha
            assert meta.short_sha == fake_sha[:8]
    finally:
        shutil.rmtree(temp_repo, ignore_errors=True)


def test_run_record_model_instantiation():
    """Verify RunRecord data model instantiation and attribute/dict access."""
    rec = RunRecord(
        run_id="run-12345678",
        repo_path="/test/repo",
        repo_name="my-service",
        branch="main",
        base_commit="abc1234567890",
        short_sha="abc12345",
        mode="real",
        status="RUNNING",
        created_at="2026-10-23 00:00:00",
    )

    assert rec.run_id == "run-12345678"
    assert rec["run_id"] == "run-12345678"
    assert rec.get("branch") == "main"
    assert rec.status == "RUNNING"
    assert rec.is_healthy is None

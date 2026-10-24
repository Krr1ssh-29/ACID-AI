"""Repository inspection, Git metadata extraction, and disposable workspace management.

Provides truthful local Git repository validation, branch and base-commit
identification, and ephemeral workspace copying to guarantee zero host mutation.
"""
import contextlib
import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional, List

from agent.models import RepositoryMetadata
from agent.runner import copy_disposable_repo


MANIFEST_FILES = (
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "setup.py",
    "setup.cfg",
    "Dockerfile",
)

TEST_DIRECTORIES = (
    "tests",
    "test",
    "sample-app/tests",
    "sample_app/tests",
)


def _detect_key_files(root_path: str) -> List[str]:
    """Inspect directory to detect manifests, test suites, and log fixtures."""
    detected = []
    for mf in MANIFEST_FILES:
        if os.path.isfile(os.path.join(root_path, mf)):
            detected.append(mf)

    for td in TEST_DIRECTORIES:
        full_td = os.path.join(root_path, *td.split("/"))
        if os.path.isdir(full_td):
            detected.append(td)

    for log_candidate in ("combined-logs.txt", "ci-output.log"):
        if os.path.isfile(os.path.join(root_path, log_candidate)):
            detected.append(log_candidate)

    return detected


def extract_github_repo_from_remote(remote_url: Optional[str]) -> Optional[str]:
    """Parse remote URL to extract GitHub owner/repo slug.

    Supports:
      - https://github.com/owner/repo.git
      - https://github.com/owner/repo
      - git@github.com:owner/repo.git
      - ssh://git@github.com/owner/repo.git
    """
    if not remote_url:
        return None
    url = remote_url.strip()
    match = re.search(r"github\.com[:/]([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?$", url)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return None


def _inspect_git_via_cli(repo_dir: str) -> Optional[dict]:
    """Inspect Git repository via git CLI commands if available.

    Returns dict with keys ('toplevel', 'branch', 'base_commit', 'is_clean', 'remote_url', 'github_repo') or None.
    """
    try:
        top_proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if top_proc.returncode != 0:
            return None

        toplevel = os.path.abspath(top_proc.stdout.strip())

        # Branch resolution
        branch_proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=toplevel,
            capture_output=True,
            text=True,
            timeout=5,
        )
        branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else "unknown"

        # Commit SHA resolution
        commit_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=toplevel,
            capture_output=True,
            text=True,
            timeout=5,
        )
        base_commit = commit_proc.stdout.strip() if commit_proc.returncode == 0 else "unknown"

        # Working tree status
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=toplevel,
            capture_output=True,
            text=True,
            timeout=5,
        )
        is_clean = (status_proc.returncode == 0 and len(status_proc.stdout.strip()) == 0)

        # Remote URL & GitHub owner/repo
        remote_url = None
        github_repo = None
        remote_proc = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=toplevel,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if remote_proc.returncode == 0 and remote_proc.stdout.strip():
            remote_url = remote_proc.stdout.strip()
            github_repo = extract_github_repo_from_remote(remote_url)

        return {
            "toplevel": toplevel,
            "branch": branch,
            "base_commit": base_commit,
            "is_clean": is_clean,
            "remote_url": remote_url,
            "github_repo": github_repo,
        }
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def _inspect_git_via_fs(repo_dir: str) -> Optional[dict]:
    """Inspect Git repository directly via .git filesystem structures as fallback."""
    dot_git = os.path.join(repo_dir, ".git")
    if not os.path.exists(dot_git):
        return None

    # Handle .git directory vs gitdir file (submodule / worktree)
    git_dir = dot_git
    if os.path.isfile(dot_git):
        try:
            with open(dot_git, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content.startswith("gitdir:"):
                    rel_gitdir = content.replace("gitdir:", "").strip()
                    git_dir = os.path.abspath(os.path.join(repo_dir, rel_gitdir))
        except OSError:
            pass

    branch = "unknown"
    commit_sha = "unknown"

    head_file = os.path.join(git_dir, "HEAD")
    if os.path.isfile(head_file):
        try:
            with open(head_file, "r", encoding="utf-8") as f:
                head_content = f.read().strip()
                if head_content.startswith("ref:"):
                    ref_path = head_content.replace("ref:", "").strip()
                    branch = ref_path.replace("refs/heads/", "")
                    full_ref_path = os.path.join(git_dir, ref_path.replace("/", os.sep))
                    if os.path.isfile(full_ref_path):
                        with open(full_ref_path, "r", encoding="utf-8") as rf:
                            commit_sha = rf.read().strip()
                else:
                    # Detached HEAD contains commit SHA directly
                    commit_sha = head_content
                    branch = "HEAD"
        except OSError:
            pass

    remote_url = None
    github_repo = None
    config_file = os.path.join(git_dir, "config")
    if os.path.isfile(config_file):
        try:
            with open(config_file, "r", encoding="utf-8", errors="replace") as cf:
                for line in cf:
                    line_str = line.strip()
                    if line_str.startswith("url ="):
                        remote_url = line_str.split("=", 1)[1].strip()
                        github_repo = extract_github_repo_from_remote(remote_url)
                        break
        except OSError:
            pass

    return {
        "toplevel": repo_dir,
        "branch": branch,
        "base_commit": commit_sha,
        "is_clean": True,  # Cannot determine dirty status safely without git binary
        "remote_url": remote_url,
        "github_repo": github_repo,
    }


def validate_repository(path: Optional[str] = None) -> RepositoryMetadata:
    """Validate a local repository path and extract branch and commit identity.

    Args:
        path: Path to the target local repository. Defaults to current working directory.

    Returns:
        Truthful RepositoryMetadata detailing the repository or validation failure.
    """
    if path is None:
        target = os.getcwd()
    else:
        target = str(path).strip()

    if not target:
        return RepositoryMetadata(
            path="",
            name="unknown",
            is_git=False,
            error="Repository path cannot be empty.",
        )

    abs_path = os.path.abspath(os.path.expanduser(target))

    if not os.path.exists(abs_path):
        return RepositoryMetadata(
            path=abs_path,
            name=os.path.basename(abs_path) or "unknown",
            is_git=False,
            error=f"Repository path does not exist: '{abs_path}'",
        )

    if not os.path.isdir(abs_path):
        return RepositoryMetadata(
            path=abs_path,
            name=os.path.basename(abs_path) or "unknown",
            is_git=False,
            error=f"Repository path is not a directory: '{abs_path}'",
        )

    # 1. Attempt Git CLI inspection
    git_info = _inspect_git_via_cli(abs_path)

    # 2. Fall back to direct .git filesystem inspection
    if not git_info:
        git_info = _inspect_git_via_fs(abs_path)

    if not git_info:
        return RepositoryMetadata(
            path=abs_path,
            name=os.path.basename(abs_path),
            is_git=False,
            error=f"Directory is not a valid Git repository: '{abs_path}' (missing .git)",
        )

    resolved_root = git_info["toplevel"]
    repo_name = os.path.basename(resolved_root)
    branch = git_info["branch"]
    base_commit = git_info["base_commit"]
    short_sha = base_commit[:8] if base_commit != "unknown" else "unknown"
    is_clean = git_info.get("is_clean", True)

    detected_files = _detect_key_files(resolved_root)
    has_tests = any("test" in df.lower() for df in detected_files)
    has_manifest = any(df in MANIFEST_FILES for df in detected_files)

    remote_url = git_info.get("remote_url")
    github_repo = git_info.get("github_repo")

    return RepositoryMetadata(
        path=resolved_root,
        name=repo_name,
        branch=branch,
        base_commit=base_commit,
        short_sha=short_sha,
        is_git=True,
        is_clean=is_clean,
        has_tests=has_tests,
        has_manifest=has_manifest,
        detected_files=detected_files,
        remote_url=remote_url,
        github_repo=github_repo,
        error=None,
    )


def create_disposable_workspace(source_repo: str) -> str:
    """Create an isolated temporary copy of a repository, excluding sensitive and cache files.

    Guarantees that analysis and verification occur in an ephemeral environment
    without modifying the user's source working tree.

    Args:
        source_repo: Clean source repository directory path.

    Returns:
        Absolute path to the created temporary workspace.
    """
    if not os.path.isdir(source_repo):
        raise ValueError(f"Cannot create disposable workspace: '{source_repo}' is not a directory.")

    temp_dir = tempfile.mkdtemp(prefix="acid-disposable-")
    try:
        copy_disposable_repo(source_root=source_repo, target_dir=temp_dir)
        return temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


@contextlib.contextmanager
def disposable_working_copy(source_repo: str):
    """Context manager providing an ephemeral working copy with guaranteed cleanup.

    Usage:
        with disposable_working_copy("/path/to/repo") as workspace:
            # perform candidate patch application and verification inside workspace
            pass
        # workspace is destroyed; source_repo is 100% untouched
    """
    workspace = create_disposable_workspace(source_repo)
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

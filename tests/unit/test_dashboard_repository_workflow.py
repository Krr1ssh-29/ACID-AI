"""Unit and integration tests for the repository-first dashboard workflow (Milestone 1)."""
import os
import shutil
import tempfile
import pytest

from dashboard.app import create_app


@pytest.fixture
def repo_root():
    """Return the absolute path of the current repository root."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def client(repo_root):
    """Create a configured Flask test client."""
    app = create_app({"TESTING": True, "REPO_ROOT": repo_root})
    with app.test_client() as test_client:
        test_client.post("/api/reset")
        yield test_client


def test_api_repo_current(client, repo_root):
    """Verify /api/repo/current returns metadata for the default workspace."""
    res = client.get("/api/repo/current")
    assert res.status_code == 200
    data = res.get_json()

    assert data["is_valid"] is True
    assert data["repo"]["name"] == os.path.basename(repo_root)
    assert data["repo"]["branch"] != "unknown"
    assert len(data["repo"]["base_commit"]) == 40
    assert data["error"] is None


def test_api_repo_validate_valid_path(client, repo_root):
    """Verify /api/repo/validate succeeds on a valid Git repository."""
    res = client.post("/api/repo/validate", json={"repo_path": repo_root})
    assert res.status_code == 200
    data = res.get_json()

    assert data["is_valid"] is True
    assert data["repo"]["is_git"] is True
    assert data["repo"]["short_sha"] == data["repo"]["base_commit"][:8]


def test_api_repo_validate_invalid_path(client):
    """Verify /api/repo/validate returns 400 for a nonexistent directory."""
    res = client.post("/api/repo/validate", json={"repo_path": "/fake/nonexistent/repo_path_123"})
    assert res.status_code == 400
    data = res.get_json()

    assert data["is_valid"] is False
    assert "does not exist" in data["error"]


def test_api_repo_validate_empty_path(client):
    """Verify /api/repo/validate returns 400 for an empty path."""
    res = client.post("/api/repo/validate", json={"repo_path": ""})
    assert res.status_code == 400
    data = res.get_json()

    assert data["is_valid"] is False
    assert "cannot be empty" in data["error"]


def test_api_repo_run_healthy_pipeline(client, repo_root):
    """Verify running analysis against sample-app with passing tests activates healthy silent bypass."""
    res = client.post(
        "/api/repo/run",
        json={"repo_path": repo_root, "provider_mode": "mock"},
    )
    assert res.status_code == 200
    data = res.get_json()

    assert "run_id" in data
    assert data["run_id"].startswith("repo-")
    assert data["is_healthy"] is True
    assert data["status"] == "HEALTHY"
    assert data["verification"]["status"] == "SKIPPED_HEALTHY"
    assert data["publication"]["status"] == "SKIPPED_HEALTHY"

    # Truthful RunRecord verification
    rec = data["run_record"]
    assert rec["run_id"] == data["run_id"]
    assert rec["status"] == "HEALTHY"
    assert rec["branch"] != "unknown"
    assert rec["base_commit"] != "unknown"
    assert rec["is_healthy"] is True
    assert "workspace_isolation" in data["truthfulness"]


def test_api_repo_run_failure_with_log_fixture(client):
    """Verify repository analysis correctly triages failure logs, proposes patch, and evaluates verification."""
    temp_repo = tempfile.mkdtemp(prefix="repo-failure-test-")
    try:
        # Create minimal git repository
        dot_git = os.path.join(temp_repo, ".git")
        os.makedirs(os.path.join(dot_git, "refs", "heads"), exist_ok=True)
        with open(os.path.join(dot_git, "HEAD"), "w") as f:
            f.write("ref: refs/heads/main\n")
        with open(os.path.join(dot_git, "refs", "heads", "main"), "w") as f:
            f.write("b" * 40 + "\n")

        # Copy fixture log as combined-logs.txt
        fixture_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "missing_dependency.txt")
        )
        shutil.copy2(fixture_path, os.path.join(temp_repo, "combined-logs.txt"))

        # Create target file matching patch expectation
        os.makedirs(os.path.join(temp_repo, "sample-app"), exist_ok=True)
        with open(os.path.join(temp_repo, "sample-app", "requirements.txt"), "w") as f:
            f.write("flask==3.0.3\nrequests==2.32.3\n")

        res = client.post(
            "/api/repo/run",
            json={"repo_path": temp_repo, "provider_mode": "mock"},
        )
        assert res.status_code == 200
        data = res.get_json()

        assert data["is_healthy"] is False
        assert data["status"] == "FAILED"
        assert "install" in data["diagnosis"]["failure_types"]
        assert data["publication"]["status"] in (
            "skipped_milestone_1",
            "skipped_milestone_2",
            "skipped_phase_3",
            "skipped_phase_4",
        )
        assert "DISABLED" in data["publication"]["display"]

        rec = data["run_record"]
        assert rec["status"] in ("FAILED", "BLOCKED")
        assert rec["base_commit"] == "b" * 40
        assert rec["is_healthy"] is False
    finally:
        shutil.rmtree(temp_repo, ignore_errors=True)


def test_api_repo_run_invalid_path_fails_gracefully(client):
    """Verify running on an invalid path returns 400 error cleanly."""
    res = client.post(
        "/api/repo/run",
        json={"repo_path": "/invalid/nonexistent/path_xyz"},
    )
    assert res.status_code == 400
    data = res.get_json()
    assert "error" in data


def test_api_run_accepts_repo_path_for_repository_workflow(client, repo_root):
    """Verify unified /api/run endpoint dispatches to repository analysis when repo_path is provided."""
    res = client.post(
        "/api/run",
        json={"repo_path": repo_root, "provider_mode": "mock"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["run_id"].startswith("repo-")
    assert "repo_meta" in data
    assert "run_record" in data


def test_history_tracks_repository_runs(client, repo_root):
    """Verify repository runs accumulate properly in session history with mode metadata."""
    client.post("/api/reset")

    res = client.post(
        "/api/repo/run",
        json={"repo_path": repo_root, "provider_mode": "mock"},
    )
    assert res.status_code == 200

    hist_res = client.get("/api/history")
    assert hist_res.status_code == 200
    history = hist_res.get_json()["history"]

    assert len(history) == 1
    entry = history[0]
    assert entry["failure_type"] == "repository"
    assert entry["run_id"].startswith("repo-")
    assert entry["scenario_id"] is None
    assert entry["mode"] == "mock"

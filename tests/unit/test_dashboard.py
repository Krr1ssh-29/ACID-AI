"""Unit and integration tests for the hackathon demo dashboard."""
import os
from unittest.mock import patch
import pytest
from dashboard.app import create_app
from dashboard.engine import get_system_status, DEMO_SCENARIOS


@pytest.fixture
def client():
    """Create test client configured with repository root."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    app = create_app({"TESTING": True, "REPO_ROOT": repo_root})
    with app.test_client() as test_client:
        # Reset demo history before each test
        test_client.post("/api/reset")
        yield test_client


def test_dashboard_index_route(client):
    """Test index route renders presentation HTML with required headings."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "ACID AI" in html
    assert "Select Reproducible Demonstration Scenario" in html
    assert "ci-console-output.log" in html


def test_dashboard_list_scenarios(client):
    """Test /api/scenarios returns all 6 predefined scenarios."""
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    data = response.get_json()
    assert "scenarios" in data
    assert len(data["scenarios"]) == len(DEMO_SCENARIOS)
    ids = [sc["id"] for sc in data["scenarios"]]
    assert "healthy_run" in ids
    assert "missing_dependency" in ids
    assert "lint_flake8" in ids
    assert "pytest_assertion" in ids
    assert "docker_build" in ids
    assert "live_sample_app" in ids


def test_dashboard_system_status(client):
    """Test /api/system-status probes environment truthfully."""
    response = client.get("/api/system-status")
    assert response.status_code == 200
    data = response.get_json()
    assert "docker_available" in data
    assert "has_gemini_key" in data
    assert "isolation_guard_status" in data
    assert data["isolation_guard_status"] == "FAIL_CLOSED_ACTIVE"


def test_dashboard_run_healthy_scenario(client):
    """Test healthy scenario execution results in silent bypass."""
    response = client.post("/api/run", json={"scenario_id": "healthy_run"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["is_healthy"] is True
    assert data["status"] == "HEALTHY"
    assert data["classification"]["bypass_active"] is True
    assert data["verification"]["status"] == "SKIPPED_HEALTHY"
    assert data["publication"]["status"] == "SKIPPED_HEALTHY"


def test_dashboard_run_missing_dependency(client):
    """Test dependency failure triage, patch generation, and fail-closed verification."""
    response = client.post(
        "/api/run",
        json={"scenario_id": "missing_dependency", "provider_mode": "mock"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["is_healthy"] is False
    assert data["status"] == "FAILED"
    assert "install" in data["diagnosis"]["failure_types"]
    assert data["patch"]["is_valid"] is True
    assert "infrastructure requirement not met" in data["verification"]["display"]
    assert "BLOCKED" in data["publication"]["display"]


def test_dashboard_run_lint_flake8(client):
    """Test lint failure triage and patch proposal."""
    response = client.post(
        "/api/run",
        json={"scenario_id": "lint_flake8", "provider_mode": "mock"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["is_healthy"] is False
    assert "lint" in data["diagnosis"]["failure_types"]
    assert "sample-app/app.py" in data["patch"]["diff"]


def test_dashboard_run_pytest_assertion(client):
    """Test pytest assertion failure triage."""
    response = client.post(
        "/api/run",
        json={"scenario_id": "pytest_assertion", "provider_mode": "mock"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["is_healthy"] is False
    assert "test" in data["diagnosis"]["failure_types"]


def test_dashboard_run_docker_build(client):
    """Test docker container build failure triage."""
    response = client.post(
        "/api/run",
        json={"scenario_id": "docker_build", "provider_mode": "mock"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["is_healthy"] is False
    assert "docker" in data["diagnosis"]["failure_types"]


def test_dashboard_run_live_sample_app(client):
    """Test live local pytest execution against sample-app."""
    response = client.post(
        "/api/run",
        json={"scenario_id": "live_sample_app"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "stages" in data
    assert any(s["name"] == "Test" for s in data["stages"])


def test_dashboard_run_invalid_scenario(client):
    """Test triggering an unconfigured scenario returns 400 error."""
    response = client.post(
        "/api/run",
        json={"scenario_id": "unregistered_scenario_xyz"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_dashboard_history_and_reset(client):
    """Test demo run history accumulation and reset functionality."""
    # Execute run
    client.post("/api/run", json={"scenario_id": "healthy_run"})

    # Check history contains entry
    res = client.get("/api/history")
    assert res.status_code == 200
    data = res.get_json()
    assert len(data["history"]) >= 1
    assert data["history"][0]["scenario_id"] == "healthy_run"

    # Reset history
    reset_res = client.post("/api/reset")
    assert reset_res.status_code == 200

    # Check history is empty
    empty_res = client.get("/api/history")
    assert empty_res.status_code == 200
    assert len(empty_res.get_json()["history"]) == 0


def test_direct_get_system_status():
    """Test engine get_system_status directly returns valid structure."""
    status = get_system_status()
    assert isinstance(status["docker_available"], bool)
    assert isinstance(status["has_gemini_key"], bool)
    assert "FAIL_CLOSED" in status["isolation_guard_status"]


def test_dashboard_app_launch_debug_disabled():
    """Verify python -m dashboard.app launch path passes debug=False and binds to 127.0.0.1."""
    import dashboard.app as dash_app

    with patch.object(dash_app.app, "run") as mock_run:
        exit_code = dash_app.main()
        assert exit_code == 0
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs.get("debug") is False
        assert kwargs.get("host") == "127.0.0.1"


def test_run_demo_launch_debug_disabled_and_localhost_enforced():
    """Verify python run_demo.py launch path passes debug=False and enforces 127.0.0.1."""
    import run_demo
    from flask import Flask

    with patch.object(Flask, "run") as mock_run:
        # 1. Default invocation
        with patch("sys.argv", ["run_demo.py"]):
            run_demo.main()
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs.get("debug") is False
            assert kwargs.get("host") == "127.0.0.1"

        mock_run.reset_mock()

        # 2. Invocations attempting to bind to non-localhost (e.g. 0.0.0.0) are safely overridden
        with patch("sys.argv", ["run_demo.py", "--host", "0.0.0.0"]):
            run_demo.main()
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs.get("debug") is False
            assert kwargs.get("host") == "127.0.0.1"

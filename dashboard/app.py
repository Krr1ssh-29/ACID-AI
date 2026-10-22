"""Flask web application for the hackathon presentation demo dashboard."""
import os
from typing import List, Dict, Any
from flask import Flask, jsonify, render_template, request

from dashboard.engine import (
    DEMO_SCENARIOS,
    get_system_status,
    run_scenario,
)

# In-memory history for local presentation session
DEMO_RUN_HISTORY: List[Dict[str, Any]] = []
MAX_HISTORY_ITEMS = 20


def create_app(test_config: Dict[str, Any] = None) -> Flask:
    """Application factory for the hackathon demo dashboard."""
    template_folder = os.path.join(os.path.dirname(__file__), "templates")
    static_folder = os.path.join(os.path.dirname(__file__), "static")

    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
    )

    if test_config:
        app.config.update(test_config)

    @app.route("/")
    def index():
        """Serve the presentation dashboard interface."""
        return render_template("index.html")

    @app.route("/api/scenarios", methods=["GET"])
    def list_scenarios():
        """Return available reproducible failure scenarios."""
        scenarios_list = list(DEMO_SCENARIOS.values())
        return jsonify({"scenarios": scenarios_list})

    @app.route("/api/system-status", methods=["GET"])
    def system_status():
        """Return host environment status and active security gates."""
        status = get_system_status()
        return jsonify(status)

    @app.route("/api/run", methods=["POST"])
    def trigger_run():
        """Trigger an end-to-end triage run for a selected scenario."""
        data = request.get_json() or {}
        scenario_id = data.get("scenario_id", "missing_dependency")
        provider_mode = data.get("provider_mode", "mock")

        if scenario_id not in DEMO_SCENARIOS:
            return jsonify({"error": f"Invalid scenario ID '{scenario_id}'"}), 400

        try:
            repo_root = app.config.get("REPO_ROOT")
            result = run_scenario(
                scenario_id=scenario_id,
                provider_mode=provider_mode,
                repo_root=repo_root,
            )

            # Record in local run history
            history_entry = {
                "run_id": result["run_id"],
                "scenario_id": scenario_id,
                "scenario_name": result["scenario"]["name"],
                "timestamp": result["timestamp"],
                "status": result["status"],
                "failure_type": result["scenario"]["failure_type"],
                "is_healthy": result["is_healthy"],
                "elapsed_seconds": result["elapsed_seconds"],
                "verification_display": (
                    result["verification"].get("display", "N/A")
                    if isinstance(result.get("verification"), dict)
                    else "N/A"
                ),
            }
            DEMO_RUN_HISTORY.insert(0, history_entry)
            if len(DEMO_RUN_HISTORY) > MAX_HISTORY_ITEMS:
                DEMO_RUN_HISTORY.pop()

            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/history", methods=["GET"])
    def get_history():
        """Return recent demo run history."""
        return jsonify({"history": DEMO_RUN_HISTORY})

    @app.route("/api/reset", methods=["POST"])
    def reset_demo():
        """Reset local demo run history."""
        DEMO_RUN_HISTORY.clear()
        return jsonify({"status": "reset_successful", "message": "Demo history cleared."})

    return app


# Default app instance for runners
app = create_app()


def main() -> int:
    """Run the presentation dashboard server with debug disabled on localhost."""
    port = int(os.environ.get("DEMO_PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=False)
    return 0


if __name__ == "__main__":
    main()

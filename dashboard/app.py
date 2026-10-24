"""Flask web application for the hackathon presentation demo dashboard."""
import os
from typing import List, Dict, Any
from flask import Flask, jsonify, render_template, request

from dashboard.engine import (
    DEMO_SCENARIOS,
    get_system_status,
    run_scenario,
    run_repository_analysis,
)
from agent.repository import validate_repository

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

    @app.route("/api/repo/current", methods=["GET"])
    def current_repository():
        """Inspect and return metadata for the current default workspace repository."""
        root = app.config.get("REPO_ROOT") or os.getcwd()
        meta = validate_repository(root)
        return jsonify({"is_valid": meta.is_git, "repo": meta.model_dump(), "error": meta.error})

    @app.route("/api/repo/validate", methods=["POST"])
    def validate_repo_path():
        """Validate a specified local repository path, branch, and base commit."""
        data = request.get_json() or {}
        repo_path = data.get("repo_path")
        if repo_path is None or not str(repo_path).strip():
            return jsonify({
                "is_valid": False,
                "repo": None,
                "error": "Repository path cannot be empty.",
            }), 400

        meta = validate_repository(repo_path)
        status_code = 200 if meta.is_git else 400
        return jsonify({
            "is_valid": meta.is_git,
            "repo": meta.model_dump(),
            "error": meta.error,
        }), status_code

    @app.route("/api/repo/run", methods=["POST"])
    def trigger_repo_run():
        """Trigger an end-to-end analysis and repair run on a local repository."""
        data = request.get_json() or {}
        repo_path = data.get("repo_path") or app.config.get("REPO_ROOT") or os.getcwd()
        provider_mode = data.get("provider_mode", "mock")
        log_file = data.get("log_file")
        enable_publishing = bool(data.get("enable_publishing", False))
        github_token = data.get("github_token")

        try:
            result = run_repository_analysis(
                repo_path=repo_path,
                provider_mode=provider_mode,
                log_file_override=log_file,
                enable_publishing=enable_publishing,
                github_token=github_token,
            )

            final_status = result.get("final_status") or ("healthy" if result.get("is_healthy") else "unresolved")
            # Record in local run history
            history_entry = {
                "run_id": result["run_id"],
                "scenario_id": None,
                "scenario_name": result.get("repo_meta", {}).get("name", "Unknown Repo"),
                "timestamp": result["timestamp"],
                "status": result["status"],
                "final_status": final_status,
                "failure_type": "repository",
                "mode": result.get("run_record", {}).get("mode", provider_mode),
                "is_healthy": result["is_healthy"],
                "elapsed_seconds": result["elapsed_seconds"],
                "verification_display": (
                    result["verification"].get("display", "N/A")
                    if isinstance(result.get("verification"), dict)
                    else "N/A"
                ),
                "publication_status": (
                    result["publication"].get("status", "none")
                    if isinstance(result.get("publication"), dict)
                    else "none"
                ),
                "pr_url": (
                    result["publication"].get("pr_url")
                    if isinstance(result.get("publication"), dict)
                    else None
                ),
            }
            DEMO_RUN_HISTORY.insert(0, history_entry)
            if len(DEMO_RUN_HISTORY) > MAX_HISTORY_ITEMS:
                DEMO_RUN_HISTORY.pop()

            return jsonify(result)
        except ValueError as e:
            return jsonify({
                "error": str(e),
                "error_type": "ValueError",
                "category": "validation_error",
            }), 400
        except Exception as e:
            return jsonify({
                "error": str(e),
                "error_type": type(e).__name__,
                "category": "execution_error",
            }), 500

    @app.route("/api/run", methods=["POST"])
    def trigger_run():
        """Trigger an end-to-end triage run for a repository or selected scenario."""
        data = request.get_json() or {}

        # If repo_path is explicitly provided, dispatch to repository analysis
        if "repo_path" in data and data.get("repo_path"):
            return trigger_repo_run()

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

            final_status = result.get("final_status") or ("healthy" if result.get("is_healthy") else "unresolved")
            # Record in local run history
            history_entry = {
                "run_id": result["run_id"],
                "scenario_id": scenario_id,
                "scenario_name": result["scenario"]["name"],
                "timestamp": result["timestamp"],
                "status": result["status"],
                "final_status": final_status,
                "failure_type": result["scenario"]["failure_type"],
                "mode": result["run_record"]["mode"],
                "is_healthy": result["is_healthy"],
                "elapsed_seconds": result["elapsed_seconds"],
                "verification_display": (
                    result["verification"].get("display", "N/A")
                    if isinstance(result.get("verification"), dict)
                    else "N/A"
                ),
                "publication_status": (
                    result["publication"].get("status", "none")
                    if isinstance(result.get("publication"), dict)
                    else "none"
                ),
                "pr_url": (
                    result["publication"].get("pr_url")
                    if isinstance(result.get("publication"), dict)
                    else None
                ),
            }
            DEMO_RUN_HISTORY.insert(0, history_entry)
            if len(DEMO_RUN_HISTORY) > MAX_HISTORY_ITEMS:
                DEMO_RUN_HISTORY.pop()

            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/reports/<run_id>", methods=["GET"])
    def get_run_report(run_id: str):
        """Retrieve structured FinalReport JSON for a specific run ID."""
        from agent.report import get_report
        report = get_report(run_id)
        if not report:
            return jsonify({"error": f"Report not found for run ID '{run_id}'"}), 404
        return jsonify(report.model_dump())

    @app.route("/api/reports/<run_id>/markdown", methods=["GET"])
    def get_run_report_markdown(run_id: str):
        """Retrieve rendered Markdown final report for a specific run ID."""
        from agent.report import get_report
        from flask import Response
        report = get_report(run_id)
        if not report:
            return jsonify({"error": f"Report not found for run ID '{run_id}'"}), 404
        return Response(report.markdown, mimetype="text/markdown")

    @app.route("/api/reports/<run_id>/pdf", methods=["GET"])
    def get_run_report_pdf(run_id: str):
        """Retrieve or generate downloadable PDF final report for a specific run ID."""
        from agent.report import get_or_generate_report_pdf
        from flask import Response
        try:
            pdf_bytes = get_or_generate_report_pdf(run_id)
            if not pdf_bytes:
                return jsonify({"error": f"Report not found for run ID '{run_id}'"}), 404

            headers = {
                "Content-Type": "application/pdf",
                "Content-Disposition": f'attachment; filename="acid-ai-report-{run_id}.pdf"',
            }
            return Response(pdf_bytes, mimetype="application/pdf", headers=headers)
        except Exception as e:
            from agent.security import redact_secrets
            clean_msg = redact_secrets(str(e))
            return jsonify({"error": f"Failed to generate PDF report: {clean_msg}"}), 500

    @app.route("/api/reports", methods=["GET"])
    def list_run_reports():
        """List all stored final reports."""
        from agent.report import list_reports
        reports = list_reports()
        return jsonify({"reports": reports})

    @app.route("/api/history", methods=["GET"])
    def get_history():
        """Return recent demo and repository run history."""
        return jsonify({"history": DEMO_RUN_HISTORY})

    @app.route("/api/reset", methods=["POST"])
    def reset_demo():
        """Reset local run history."""
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

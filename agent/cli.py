"""Command-line interface and orchestrator for ACID AI."""
import sys
import json
from typing import Optional, List
from agent.config import load_config, validate_credentials
from agent.collector import read_logs
from agent.classifier import classify_failures
from agent.providers import analyse_with_ai
from agent.formatter import format_pr_comment
from agent.github import post_pr_comment
from agent.models import AgentConfig, PipelineStatus


def main(argv: Optional[List[str]] = None, config: Optional[AgentConfig] = None) -> int:
    """Execute the failure triage pipeline.

    Args:
        argv: Optional command-line arguments.
        config: Optional pre-loaded AgentConfig instance.

    Returns:
        Process exit code: 0 for clean execution, 1 on unrecoverable error.
    """
    # Ensure stdout/stderr handle UTF-8 emojis cleanly across all platforms
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    cfg = config or load_config()

    print("🚀 ACID AI starting...")
    print(f"   Repo:     {cfg.repo_name}")
    print(f"   PR:       #{cfg.pr_number}")
    print(f"   SHA:      {cfg.commit_sha[:8] if cfg.commit_sha else 'unknown'}")
    print(f"   Provider: {cfg.ai_provider.upper()}")

    # Credential pre-check
    cred_error = validate_credentials(cfg)
    if cred_error:
        print(f"❌ {cred_error}")
        return 1

    logs = read_logs(cfg.log_file)
    print(f"📄 Logs loaded ({len(logs)} characters)")

    failure_context = classify_failures(logs)
    status = getattr(failure_context, "status", None) or failure_context.get("status")

    if status == PipelineStatus.ERROR:
        details = getattr(failure_context, "details", None) or failure_context.get("details", "Log error")
        print(f"❌ Input/collection error: {details}")
        return 1

    if status == PipelineStatus.INCONCLUSIVE:
        details = getattr(failure_context, "details", None) or failure_context.get("details", "Inconclusive")
        print(f"⚠️ Pipeline status is inconclusive: {details}. Skipping AI triage.")
        return 2

    if status == PipelineStatus.HEALTHY or (not failure_context["detected"] and status != PipelineStatus.FAILED):
        print("✅ No failures detected — pipeline healthy. Silent bypass active (0 tokens, 0 comments).")
        return 0

    print(f"🔍 Detected failures: {failure_context['detected']}")

    try:
        analysis = analyse_with_ai(logs, failure_context, cfg)
        print(f"🧠 Analysis complete. Severity: {analysis.get('severity', 'unknown')}")
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse AI response as JSON: {e}")
        return 1
    except Exception as e:
        from agent.security import redact_secrets
        clean_err = redact_secrets(str(e))
        print(f"❌ AI provider error: {clean_err}")
        return 1

    comment = format_pr_comment(
        analysis,
        cfg.commit_sha,
        cfg.run_id,
        cfg.repo_name or "unknown/repo",
        cfg.ai_provider,
    )
    post_pr_comment(comment, cfg.repo_name, cfg.pr_number, cfg.github_token)

    try:
        from agent.security import redact_data
        clean_analysis = redact_data(analysis)
        with open("agent-analysis.json", "w", encoding="utf-8") as f:
            json.dump(clean_analysis, f, indent=2)
        print("💾 Saved to agent-analysis.json")
    except OSError as e:
        print(f"⚠️ Warning: Could not write agent-analysis.json: {e}")

    if cfg.generate_patch:
        print("🛠️ Patch generation requested (GENERATE_PATCH=true)...")
        from agent.patcher import generate_patch
        from agent.runner import VerificationRunner
        from agent.publisher import publish_repair_pr
        from agent.models import PatchStatus, PublishStatus, VerificationStatus

        patch = generate_patch(analysis, config=cfg)
        print(f"📄 Patch proposal status: {patch.status.value}")

        if patch.status == PatchStatus.VALIDATED:
            print("🧪 Executing isolated verification in sandbox...")
            runner = VerificationRunner(config=cfg)
            verification = runner.verify(patch)
            print(f"🔬 Verification status: {verification.status.value} (is_verified={verification.is_verified})")

            # Bounded retry: if verification failed on attempt 1 with TEST_FAILED, retry once
            if (
                verification.status == VerificationStatus.TEST_FAILED
                and cfg.max_repair_attempts > 1
            ):
                print("🔄 Verification attempt 1 failed; triggering self-correction attempt 2...")
                feedback = (
                    f"Attempt 1 patch verification failed with output:\n{verification.output[-3000:]}\n"
                    f"Error: {verification.error_message}"
                )
                patch_2 = generate_patch(analysis, config=cfg, source_snippets=feedback)
                if patch_2.status == PatchStatus.VALIDATED:
                    verif_2 = runner.verify(patch_2, attempt=2)
                    print(f"🔬 Attempt 2 status: {verif_2.status.value} (is_verified={verif_2.is_verified})")
                    patch = patch_2
                    verification = verif_2

            if cfg.enable_repair_pr:
                print("🚀 Attempting to publish repair pull request...")
                pub_result = publish_repair_pr(patch, verification, analysis, cfg)
                if pub_result.status == PublishStatus.PUBLISHED:
                    print(f"🎉 Draft PR created: #{pub_result.pr_number} ({pub_result.pr_url})")
                else:
                    print(f"ℹ️ Repair PR status: {pub_result.status.value} — {pub_result.message}")
        else:
            print(
                f"⚠️ Patch proposal status is '{patch.status.value}' (not validated). "
                "Skipping isolated verification."
            )

    print("✅ Agent completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

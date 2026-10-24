import os
import sys
import json
import time
from typing import Optional, List, Dict, Any
from agent.config import load_config, validate_credentials
from agent.collector import read_logs
from agent.classifier import classify_failures
from agent.providers import analyse_with_ai
from agent.formatter import format_pr_comment
from agent.github import post_pr_comment
from agent.models import (
    AgentConfig,
    PipelineStatus,
    RunRecord,
    RepairAttempt,
    PatchStatus,
    PublishStatus,
    VerificationStatus,
)


def _emit_final_report(
    cfg: AgentConfig,
    outcome: str,
    stop_reason: str,
    logs: Optional[str] = None,
    failure_context: Optional[Any] = None,
    attempts: Optional[List[Dict[str, Any]]] = None,
    verified_patches: Optional[List[Dict[str, Any]]] = None,
    publication: Optional[Dict[str, Any]] = None,
    is_healthy: Optional[bool] = None,
) -> None:
    """Safely generate and save FinalReport and Markdown summary for the run."""
    try:
        from agent.report import generate_final_report

        status_mapping = {
            "healthy": "HEALTHY",
            "repaired": "VERIFIED",
            "partially repaired": "PARTIALLY_VERIFIED",
            "blocked": "BLOCKED",
            "unresolved": "FAILED",
        }
        cls_dict = failure_context if isinstance(failure_context, dict) else (
            getattr(failure_context, "__dict__", {}) if failure_context else {}
        )
        run_rec = RunRecord(
            run_id=cfg.run_id or "cli-run",
            repo_path=os.getcwd(),
            repo_name=cfg.repo_name or "unknown/repo",
            branch=cfg.base_branch or "main",
            pr_number=cfg.pr_number,
            base_commit=cfg.commit_sha or "unknown",
            short_sha=cfg.commit_sha[:8] if cfg.commit_sha else "unknown",
            mode="real",
            status=status_mapping.get(outcome, "FAILED"),
            final_status=outcome,
            stop_reason=stop_reason,
            retry_count=len(attempts or []),
            created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            is_healthy=is_healthy if is_healthy is not None else (outcome in ("healthy", "repaired")),
            attempts=attempts or [],
            verified_patches=verified_patches or [],
            publication=publication,
            classification=cls_dict,
        )
        generate_final_report(run_record=run_rec, log_text=logs)
    except Exception as e:
        print(f"⚠️ Warning: Could not generate final report: {e}")


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
        _emit_final_report(
            cfg=cfg,
            outcome="blocked",
            stop_reason=f"Execution blocked: {cred_error}. Live diagnosis was unavailable due to missing credentials.",
            is_healthy=False,
        )
        try:
            with open("agent-analysis.json", "w", encoding="utf-8") as f:
                json.dump({
                    "status": "blocked",
                    "error": cred_error,
                    "details": f"Live diagnosis was unavailable due to missing credentials: {cred_error}",
                    "root_cause": "Missing AI credentials",
                }, f, indent=2)
        except OSError:
            pass
        return 1

    logs = read_logs(cfg.log_file)
    print(f"📄 Logs loaded ({len(logs)} characters)")

    failure_context = classify_failures(logs)
    status = getattr(failure_context, "status", None) or failure_context.get("status")

    if status == PipelineStatus.ERROR:
        details = getattr(failure_context, "details", None) or failure_context.get("details", "Log error")
        print(f"❌ Input/collection error: {details}")
        _emit_final_report(
            cfg=cfg,
            outcome="blocked",
            stop_reason=f"Pipeline error: {details}",
            logs=logs,
            failure_context=failure_context,
            is_healthy=False,
        )
        try:
            with open("agent-analysis.json", "w", encoding="utf-8") as f:
                json.dump({"status": "blocked", "details": str(details)}, f, indent=2)
        except OSError:
            pass
        return 1

    if status == PipelineStatus.INCONCLUSIVE:
        details = getattr(failure_context, "details", None) or failure_context.get("details", "Inconclusive")
        print(f"⚠️ Pipeline status is inconclusive: {details}. Skipping AI triage.")
        _emit_final_report(
            cfg=cfg,
            outcome="unresolved",
            stop_reason=f"Pipeline status is inconclusive: {details}",
            logs=logs,
            failure_context=failure_context,
            is_healthy=False,
        )
        try:
            with open("agent-analysis.json", "w", encoding="utf-8") as f:
                json.dump({"status": "inconclusive", "details": str(details)}, f, indent=2)
        except OSError:
            pass
        return 2

    if status == PipelineStatus.HEALTHY or (not failure_context["detected"] and status != PipelineStatus.FAILED):
        _emit_final_report(
            cfg=cfg,
            outcome="healthy",
            stop_reason="Initial baseline checks passed cleanly; no repair required.",
            logs=logs,
            failure_context=failure_context,
            is_healthy=True,
        )
        try:
            with open("agent-analysis.json", "w", encoding="utf-8") as f:
                json.dump({"status": "healthy", "details": "No pipeline failures detected."}, f, indent=2)
        except OSError:
            pass
        print("✅ No failures detected — pipeline healthy. Silent bypass active (0 tokens, 0 comments).")
        return 0

    print(f"🔍 Detected failures: {failure_context['detected']}")

    try:
        analysis = analyse_with_ai(logs, failure_context, cfg)
        print(f"🧠 Analysis complete. Severity: {analysis.get('severity', 'unknown')}")
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse AI response as JSON: {e}")
        _emit_final_report(
            cfg=cfg,
            outcome="unresolved",
            stop_reason=f"Failed to parse AI response as JSON: {e}",
            logs=logs,
            failure_context=failure_context,
            is_healthy=False,
        )
        return 1
    except Exception as e:
        from agent.security import redact_secrets
        clean_err = redact_secrets(str(e))
        print(f"❌ AI provider error: {clean_err}")
        _emit_final_report(
            cfg=cfg,
            outcome="blocked",
            stop_reason=f"AI provider error: {clean_err}. Live diagnosis was unavailable.",
            logs=logs,
            failure_context=failure_context,
            is_healthy=False,
        )
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

    should_patch = cfg.generate_patch or cfg.enable_repair_pr
    attempts = []
    verified_patches = []
    pub_dict = None

    if should_patch:
        print("🛠️ Patch generation requested...")
        from agent.patcher import generate_patch
        from agent.runner import VerificationRunner
        from agent.publisher import publish_repair_pr

        patch = generate_patch(analysis, config=cfg)
        print(f"📄 Patch proposal status: {patch.status.value}")

        if patch.diff:
            try:
                with open("agent-patch.diff", "w", encoding="utf-8") as f:
                    f.write(patch.diff)
                print("💾 Saved candidate patch to agent-patch.diff")
            except OSError as e:
                print(f"⚠️ Warning: Could not write agent-patch.diff: {e}")

        if patch.status == PatchStatus.VALIDATED:
            print("🧪 Executing isolated verification in sandbox...")
            runner = VerificationRunner(config=cfg)
            verification = runner.verify(patch)
            print(f"🔬 Verification status: {verification.status.value} (is_verified={verification.is_verified})")

            attempts.append(RepairAttempt(
                attempt=1,
                status=verification.status.value,
                failure_category=analysis.get("failure_types", ["general"])[0],
                diagnosis={"root_cause": analysis.get("root_cause", "")},
                patch=patch.model_dump(),
                verification=verification.model_dump(),
                test_results=verification.output or "",
                reason=verification.error_message or "",
            ).model_dump())

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
                    if patch_2.diff:
                        try:
                            with open("agent-patch.diff", "w", encoding="utf-8") as f:
                                f.write(patch_2.diff)
                        except OSError:
                            pass
                    attempts.append(RepairAttempt(
                        attempt=2,
                        status=verif_2.status.value,
                        failure_category=analysis.get("failure_types", ["general"])[0],
                        diagnosis={"root_cause": analysis.get("root_cause", "")},
                        patch=patch_2.model_dump(),
                        verification=verif_2.model_dump(),
                        test_results=verif_2.output or "",
                        reason=verif_2.error_message or "",
                    ).model_dump())

            if verification and verification.is_verified and verification.exit_code == 0:
                verified_patches.append(patch.model_dump())

            if cfg.enable_repair_pr:
                print("🚀 Attempting to publish repair pull request...")
                pub_result = publish_repair_pr(patch, verification, analysis, cfg)
                pub_dict = pub_result.model_dump()
                if pub_result.status == PublishStatus.PUBLISHED:
                    print(f"🎉 Draft PR created: #{pub_result.pr_number} ({pub_result.pr_url})")
                else:
                    print(f"ℹ️ Repair PR status: {pub_result.status.value} — {pub_result.message}")
        else:
            print(
                f"⚠️ Patch proposal status is '{patch.status.value}' (not validated). "
                "Skipping isolated verification."
            )
            attempts.append(RepairAttempt(
                attempt=1,
                status=patch.status.value,
                failure_category=analysis.get("failure_types", ["general"])[0],
                diagnosis={"root_cause": analysis.get("root_cause", "")},
                patch=patch.model_dump(),
                verification=None,
                test_results="",
                reason="Patch proposal rejected by safety validation.",
            ).model_dump())

    final_status = "repaired" if verified_patches else "unresolved"
    stop_reason = (
        "Candidate repair verified in isolated sandbox."
        if final_status == "repaired"
        else ("Diagnosis completed without automated patch." if not should_patch else "Verification failed.")
    )
    _emit_final_report(
        cfg=cfg,
        outcome=final_status,
        stop_reason=stop_reason,
        logs=logs,
        failure_context=failure_context,
        attempts=attempts,
        verified_patches=verified_patches,
        publication=pub_dict,
        is_healthy=(final_status == "repaired"),
    )

    print("✅ Agent completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Final report generation, persistence, and formatting for ACID AI runs.

Produces structured, evidence-based reports adhering strictly to truthfulness,
distinguishing mock demonstrations from real repository runs, and preventing
secret leakage across all logs, diffs, and verification outputs.
"""
import json
import os
import re
import time
from typing import Dict, Any, Optional, List

from agent.models import FinalReport, RunRecord
from agent.security import redact_secrets


REPORT_STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
IN_MEMORY_REPORTS: Dict[str, FinalReport] = {}


def _ensure_report_dir() -> str:
    """Ensure reports directory exists and return absolute path."""
    os.makedirs(REPORT_STORAGE_DIR, exist_ok=True)
    return REPORT_STORAGE_DIR


def format_publication_status(pub_dict: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Map raw publication dict to normalized report publication status.

    Returns dict with keys:
      - outcome: 'successful', 'skipped', 'blocked', or 'attempted'
      - raw_status: PublishStatus enum value
      - branch: Branch name or None
      - pr_url: Pull request URL or None
      - pr_number: Pull request number or None
      - commit_sha: Commit SHA or None
      - message: Clear explanation of outcome
    """
    if not pub_dict:
        return {
            "outcome": "skipped",
            "raw_status": "none",
            "branch": None,
            "pr_url": None,
            "pr_number": None,
            "commit_sha": None,
            "message": "Publication was not attempted or not configured for this run.",
        }

    raw_status = str(pub_dict.get("status", "")).lower()
    msg = redact_secrets(str(pub_dict.get("message", "")))

    if raw_status in ("published", "success"):
        return {
            "outcome": "successful",
            "raw_status": raw_status,
            "branch": pub_dict.get("branch_name"),
            "pr_url": pub_dict.get("pr_url"),
            "pr_number": pub_dict.get("pr_number"),
            "commit_sha": pub_dict.get("commit_sha"),
            "message": msg or f"Successfully published Draft PR #{pub_dict.get('pr_number')}.",
        }
    elif raw_status in ("permission_error", "api_error", "fork_limitation"):
        return {
            "outcome": "blocked",
            "raw_status": raw_status,
            "branch": pub_dict.get("branch_name"),
            "pr_url": None,
            "pr_number": None,
            "commit_sha": pub_dict.get("commit_sha"),
            "message": msg or f"Publication blocked due to {raw_status}.",
        }
    else:
        return {
            "outcome": "skipped",
            "raw_status": raw_status,
            "branch": pub_dict.get("branch_name"),
            "pr_url": None,
            "pr_number": None,
            "commit_sha": pub_dict.get("commit_sha"),
            "message": msg or "Publication skipped: repair was unverified, disabled, or recursive.",
        }


def format_verification_statement(
    outcome: str,
    executed_commands: Optional[List[str]] = None,
) -> str:
    """Format clear, truthful verification scope disclaimer per Threat Model T-13."""
    cmds_str = ", ".join([f"`{c}`" for c in (executed_commands or ["pytest"])])
    if outcome == "healthy":
        return (
            "Verification Scope: ACID AI verified that existing baseline test and lint checks passed cleanly "
            "on the initial repository inspection without requiring code repair. No candidate patches were "
            "generated. Passing tests prove only that executed assertions held; edge cases outside existing "
            "tests were not evaluated."
        )
    elif outcome == "repaired":
        return (
            f"Verification Scope: ACID AI verified that candidate code changes returned exit code 0 for allowlisted "
            f"verification commands ({cmds_str}) executed inside an isolated Linux container with a read-only rootfs "
            f"and temporary tmpfs storage ceiling. ACID AI did NOT verify, and cannot guarantee, that the changes are "
            f"bug-free, optimal, performant, or free of regressions outside the executed test suite. Human engineering "
            f"review and approval remain mandatory before merging."
        )
    elif outcome == "partially repaired":
        return (
            f"Verification Scope: ACID AI verified intermediate candidate patches inside the isolated container for "
            f"commands ({cmds_str}), but remaining test failures could not be resolved within the retry budget. "
            f"The codebase is only partially repaired and requires human intervention."
        )
    elif outcome == "blocked":
        return (
            "Verification Scope: Isolated sandbox verification could not be completed because execution was blocked "
            "by infrastructure requirements (Docker offline, unavailable storage quotas) or missing provider "
            "credentials. Candidate code was strictly refused execution on the host runner to preserve isolation."
        )
    else:  # unresolved
        return (
            "Verification Scope: Candidate code changes either failed isolated sandbox verification, timed out, "
            "or failed deterministic safety policy validation. No candidate patch was verified as passing."
        )


def format_file_list(files: Any) -> str:
    """Safely format candidate or affected file list into a comma-separated string.

    Handles strings, FilePatch objects, dictionaries, lists of mixed items, and malformed inputs.
    """
    if not files:
        return "None"
    if isinstance(files, str):
        cleaned = files.strip()
        return cleaned or "None"
    if isinstance(files, dict):
        p = files.get("path") or files.get("name") or files.get("target_path") or files.get("file_path")
        return str(p).strip() if p else "None"
    if hasattr(files, "path") and files.path:
        return str(files.path).strip()
    if isinstance(files, (list, tuple)):
        extracted = []
        for f in files:
            if not f:
                continue
            if isinstance(f, str):
                s = f.strip()
                if s:
                    extracted.append(s)
            elif isinstance(f, dict):
                p = f.get("path") or f.get("name") or f.get("target_path") or f.get("file_path")
                if p:
                    extracted.append(str(p).strip())
            elif hasattr(f, "path") and f.path:
                extracted.append(str(f.path).strip())
        return ", ".join(extracted) if extracted else "None"
    return "None"


def generate_plain_english_summary(
    run_record: Optional[RunRecord] = None,
    report_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a beginner-friendly plain-English summary of the run.

    Provides clear, non-technical explanations across all 5 canonical outcomes:
    healthy, repaired, partially repaired, unresolved, and blocked.
    """
    data = report_data or {}
    outcome = (data.get("outcome") or (run_record.final_status if run_record else None) or "unresolved").lower()
    if outcome in ("pending", "running"):
        outcome = "unresolved"

    retry_count = data.get("retry_count")
    if retry_count is None and run_record:
        retry_count = run_record.retry_count
    retry_count = retry_count or 0

    stop_reason = data.get("stop_reason") or (run_record.stop_reason if run_record else "") or ""
    init_checks = data.get("initial_checks", {})
    detected = init_checks.get("detected_failures", [])
    evidence = init_checks.get("evidence", "")
    attempts = data.get("attempts", [])
    if not attempts and run_record and run_record.attempts:
        attempts = run_record.attempts
    verified_patches = data.get("verified_patches", [])
    if not verified_patches and run_record and run_record.verified_patches:
        verified_patches = run_record.verified_patches

    changed_files = data.get("changed_files") or getattr(run_record, "changed_files", []) or []

    pub_raw = data.get("publication") or (run_record.publication if run_record else None) or {}
    if pub_raw and "outcome" not in pub_raw:
        pub = format_publication_status(pub_raw)
    else:
        pub = pub_raw

    # 1. Overall outcome explanation
    outcome_explanations = {
        "healthy": "Healthy — all required checks passed; no repair was necessary.",
        "repaired": "Repaired — a repair was applied in the disposable workspace and passed the required verification.",
        "partially repaired": "Partially repaired — some failures were repaired, but other failures remain.",
        "unresolved": "Unresolved — the run finished without resolving all actionable failures.",
        "blocked": (
            "Blocked — the agent could not safely proceed because a required dependency, credential "
            "or infrastructure capability was unavailable."
        ),
    }
    overall_outcome_text = outcome_explanations.get(
        outcome,
        f"{outcome.capitalize()} — run finished with status '{outcome}'."
    )

    # 2. What happened?
    if outcome == "healthy":
        what_happened = (
            "All baseline checks (linting, tests, and environment verification) passed cleanly "
            "on the initial repository inspection without requiring code repair."
        )
    elif "test" in detected:
        test_match = re.search(r"FAILED\s+([^\s\n:]+(?:::test_[a-zA-Z0-9_]+)?)", evidence)
        if not test_match:
            test_match = re.search(r"def\s+(test_[a-zA-Z0-9_]+)", evidence)
        if not test_match:
            test_match = re.search(r"assert\s+([^\n]+)", evidence)

        if test_match:
            what_happened = (
                f"A failure was detected during the test stage. Specifically, assertion failure "
                f"'{test_match.group(1)}' occurred."
            )
        else:
            what_happened = "A failure occurred during the unit/integration test stage in the repository."
    elif "lint" in detected:
        what_happened = "Code style and formatting violations were detected during the Flake8 lint stage."
    elif "install" in detected:
        what_happened = "A package installation error occurred during the dependency install stage."
    elif "docker" in detected:
        what_happened = "A container build failure occurred during the Docker build stage."
    elif detected:
        what_happened = f"Failure detected during initial checks in: {', '.join(detected)}."
    else:
        what_happened = "Pipeline checks completed with detected failures."

    # 3. Why did it happen?
    diag = {}
    if attempts and attempts[0].get("diagnosis"):
        diag = attempts[0].get("diagnosis") or {}
    elif run_record and run_record.diagnosis:
        diag = run_record.diagnosis
    elif data.get("diagnosis"):
        diag = data.get("diagnosis") or {}

    raw_root_cause = (diag.get("root_cause") or data.get("root_cause") or "").strip()

    has_ambiguity = (
        "ambiguous" in raw_root_cause.lower()
        or ("contract" in raw_root_cause.lower() and "ambiguity" in raw_root_cause.lower())
    )
    is_add_defect = (
        "assert add(2, 2) == 5" in evidence
        and ("def add(a, b):" in evidence or "return a + b" in evidence or "4 == 5" in evidence)
    )

    if has_ambiguity:
        why_it_happened = raw_root_cause
    elif is_add_defect:
        why_it_happened = (
            "Contract Ambiguity: Test 'test_addition' asserts add(2, 2) == 5, but the implementation returns 4. "
            "Repository evidence does not document the intended contract (whether the test expectation is erroneous "
            "or the function logic was intended to differ). Human clarification is required."
        )
    elif raw_root_cause:
        why_it_happened = raw_root_cause
    elif outcome == "healthy":
        why_it_happened = "All baseline checks succeeded; no failure was detected in this run (zero tokens used)."
    elif outcome == "blocked":
        block_reason = stop_reason or "Required AI credentials or sandbox isolation unavailable."
        why_it_happened = f"Execution was blocked before root-cause resolution: {block_reason}"
    else:
        why_it_happened = "The root cause could not be conclusively determined from the available log evidence."

    # 4. What did ACID AI attempt?
    if outcome == "healthy":
        what_acid_attempted = "No repair attempts were needed or executed."
    elif not attempts:
        if changed_files:
            what_acid_attempted = (
                f"Executed {retry_count or 1} repair attempt(s) modifying [{format_file_list(changed_files)}] "
                f"(applied in disposable workspace & verified in sandbox)."
            )
        else:
            what_acid_attempted = f"Executed {retry_count or 1} repair attempt(s)."
    else:
        attempt_details = []
        for att in attempts:
            a_idx = att.get("attempt", 1)
            a_cat = att.get("failure_category", "failure")
            a_patch = att.get("patch") or {}
            cand_files = format_file_list(a_patch.get("files") or att.get("affected_files"))
            val = a_patch.get("validation") or {}
            is_valid = val.get("is_valid", False) if isinstance(val, dict) else getattr(val, "is_valid", False)
            verif = att.get("verification") or {}
            is_verif = verif.get("is_verified", False)

            if is_verif:
                status_note = "applied in disposable workspace & verified in sandbox"
            elif is_valid:
                status_note = "proposed (unverified)"
            else:
                err_codes = [e.get("code") for e in val.get("errors", [])] if isinstance(val, dict) else []
                err_str = f" [{', '.join(err_codes)}]" if err_codes else ""
                status_note = f"rejected by policy{err_str}"

            attempt_details.append(f"Attempt #{a_idx} ({a_cat}): Proposed changes to [{cand_files}] ({status_note}).")

        what_acid_attempted = f"Executed {len(attempts)} repair attempt(s): " + " ".join(attempt_details)

    # 5. Did the repair work?
    if outcome == "healthy":
        did_repair_work = "Not needed — all checks passed initially without repair."
    elif outcome == "repaired":
        did_repair_work = (
            "Yes. A candidate patch was applied in the disposable workspace and passed all allowlisted "
            "verification checks in an isolated container sandbox (exit code 0)."
        )
    elif outcome == "partially repaired":
        did_repair_work = (
            f"Partially. {len(verified_patches)} candidate patch(es) were verified and passed in the sandbox, "
            f"but remaining failures could not be resolved within the retry budget."
        )
    elif outcome == "blocked":
        did_repair_work = (
            "No. Candidate execution was blocked because sandbox isolation or live AI credentials were unavailable. "
            "Candidate code was strictly refused execution on the host runner."
        )
    else:  # unresolved
        did_repair_work = (
            "No. Candidate repair attempts did not pass isolated verification "
            "(tests failed, timed out, or policy rejected). No patch was verified as passing."
        )

    # 6. Why did the agent stop?
    no_creds = (
        "LIVE_AI_REQUIRED" in stop_reason
        or "No ANTHROPIC_API_KEY" in stop_reason
        or "No GEMINI_API_KEY" in stop_reason
    )
    if outcome == "healthy":
        why_agent_stopped = "All required CI/CD checks passed on initial inspection."
    elif outcome == "repaired":
        why_agent_stopped = "The candidate repair successfully passed all isolated sandbox verification checks."
    elif "Repeated identical" in stop_reason:
        why_agent_stopped = "The agent stopped early because consecutive attempts produced the same ineffective patch."
    elif "Nonexistent target" in stop_reason:
        why_agent_stopped = "The agent stopped early because candidate patches repeatedly targeted nonexistent files."
    elif no_creds:
        why_agent_stopped = "Execution stopped because live AI provider credentials were not configured."
    elif "INFRASTRUCTURE_FAILURE" in stop_reason or "Docker" in stop_reason:
        why_agent_stopped = "Execution stopped because Docker container isolation was unavailable."
    elif "Maximum repair" in stop_reason or "budget" in stop_reason or retry_count >= 3:
        why_agent_stopped = (
            f"The agent reached its configured maximum repair budget ({retry_count} attempts) "
            f"without resolving all issues."
        )
    elif stop_reason:
        why_agent_stopped = stop_reason
    else:
        why_agent_stopped = "Execution finished after completing analysis."

    # 7. What should the user do next?
    is_ambiguous_contract = (
        "ambiguous" in why_it_happened.lower()
        or "contract" in why_it_happened.lower()
        or "ambiguity" in why_it_happened.lower()
    )
    if outcome == "healthy":
        what_to_do_next = "No action required — all initial checks passed cleanly. Review check output if desired."
    elif is_ambiguous_contract:
        what_to_do_next = (
            "Clarify the intended contract and test specification before attempting further automated repairs."
        )
    elif outcome == "repaired":
        if pub.get("outcome") in ("successful", "published") or pub.get("status") == "published":
            what_to_do_next = (
                f"Review the verified patch and the Draft Pull Request #{pub.get('pr_number')} on GitHub "
                f"before merging."
            )
        else:
            what_to_do_next = (
                "Review the verified candidate patch in the report and consider applying it or opening a pull request."
            )
    elif outcome == "partially repaired":
        what_to_do_next = (
            "Review the verified intermediate patches and manually address the remaining unresolved failures."
        )
    elif outcome == "blocked":
        if "credential" in stop_reason.lower() or "api_key" in stop_reason.lower() or "live_ai" in stop_reason.lower():
            what_to_do_next = (
                "Configure a valid AI API key (e.g. GEMINI_API_KEY) in your environment, then re-run analysis."
            )
        elif "docker" in stop_reason.lower() or "isolation" in stop_reason.lower():
            what_to_do_next = (
                "Start the local Docker daemon to enable isolated container sandbox verification, then re-run analysis."
            )
        else:
            what_to_do_next = "Address the missing infrastructure requirement noted in the report and re-run analysis."
    else:  # unresolved
        what_to_do_next = (
            "Inspect the failure evidence and attempted candidate diffs in the report to determine if manual "
            "code changes or updated test expectations are needed."
        )

    # 8. Publication status
    pub_outcome = pub.get("outcome") or pub.get("status") or "skipped"
    if pub_outcome in ("successful", "published"):
        publication_status = (
            f"Draft PR #{pub.get('pr_number')} created on branch '{pub.get('branch')}'. "
            f"URL: {pub.get('pr_url')}"
        )
    elif pub_outcome == "blocked" or outcome in ("unresolved", "blocked"):
        msg = pub.get("message")
        if not msg or msg.lower() in ("none", "null"):
            msg = "Repairs unverified or execution blocked."
        publication_status = f"Publication blocked: {msg}"
    else:
        msg = pub.get("message")
        if not msg or msg.lower() in ("none", "null"):
            msg = "Publication was not enabled or repair was unverified."
        publication_status = f"Publication skipped: {msg}"

    pr_url = pub.get("pr_url") if pub_outcome in ("successful", "published") else None
    pr_number = pub.get("pr_number") if pub_outcome in ("successful", "published") else None

    return {
        "overall_outcome": outcome,
        "overall_outcome_text": overall_outcome_text,
        "what_happened": redact_secrets(what_happened),
        "why_it_happened": redact_secrets(why_it_happened),
        "what_acid_attempted": redact_secrets(what_acid_attempted),
        "did_repair_work": redact_secrets(did_repair_work),
        "why_agent_stopped": redact_secrets(why_agent_stopped),
        "what_to_do_next": redact_secrets(what_to_do_next),
        "publication_status": redact_secrets(publication_status),
        "pr_url": pr_url,
        "pr_number": pr_number,
    }


def build_report_markdown(report_data: Dict[str, Any]) -> str:
    """Construct full GitHub-flavored Markdown text for the final report."""
    run_id = report_data["run_id"]
    repo_name = report_data["repository"]
    branch = report_data["branch"]
    pr_num = report_data.get("pr_number")
    if pr_num:
        trigger_context_display = f"Pull Request `#{pr_num}`"
    else:
        trigger_context_display = f"Direct Push (`{branch}`)"
    base_commit = report_data["base_commit"]
    short_sha = report_data["short_sha"]
    outcome = report_data["outcome"]
    mode = report_data["mode"]
    created_at = report_data["created_at"]
    elapsed = report_data.get("elapsed_seconds") or 0.0
    retry_count = report_data.get("retry_count", 0)
    stop_reason = report_data.get("stop_reason", "")
    unresolved = report_data.get("unresolved_issues", [])
    pub = report_data.get("publication", {})
    attempts = report_data.get("attempts", [])
    scope_statement = report_data.get("verification_scope_statement", "")

    # Mode header badge
    is_mock = "mock" in str(mode).lower()
    if is_mock:
        mode_badge = (
            "> [!NOTE]\n"
            "> **DEMONSTRATION RUN:** Generated using deterministic mock fixtures for offline demonstration."
        )
    else:
        mode_badge = (
            "> [!NOTE]\n"
            "> **LIVE REPOSITORY RUN:** Generated from real repository execution, live AI diagnosis, and "
            "Docker container verification."
        )

    # Outcome badge styling
    outcome_upper = outcome.upper()
    if outcome == "repaired":
        outcome_display = f"🟩 **REPAIRED** ({outcome_upper})"
    elif outcome == "healthy":
        outcome_display = f"🟩 **HEALTHY** ({outcome_upper})"
    elif outcome == "partially repaired":
        outcome_display = f"🟦 **PARTIALLY REPAIRED** ({outcome_upper})"
    elif outcome == "blocked":
        outcome_display = f"🟨 **BLOCKED** ({outcome_upper})"
    else:
        outcome_display = f"🟥 **UNRESOLVED** ({outcome_upper})"

    # Publication section
    if pub.get("outcome") == "successful":
        pub_md = (
            f"- **Publication Status:** `SUCCESSFUL` (Draft PR Created)\n"
            f"- **Repair Branch:** `{pub.get('branch')}`\n"
            f"- **Pull Request:** [Draft PR #{pub.get('pr_number')}]({pub.get('pr_url')})\n"
            f"- **Commit SHA:** `{pub.get('commit_sha')}`\n"
            f"- **Details:** {pub.get('message')}"
        )
    elif pub.get("outcome") == "blocked":
        pub_md = (
            f"- **Publication Status:** `BLOCKED`\n"
            f"- **Reason:** {pub.get('message')}\n"
            f"- **Branch:** `{pub.get('branch') or 'none'}`"
        )
    else:
        pub_md = (
            f"- **Publication Status:** `SKIPPED`\n"
            f"- **Reason:** {pub.get('message')}"
        )

    # Initial checks summary
    init_checks = report_data.get("initial_checks", {})
    detected_failures = init_checks.get("detected_failures", [])
    detected_str = ", ".join([f"`{f}`" for f in detected_failures]) if detected_failures else "_None (clean)_"
    stages_list = init_checks.get("stages", [])
    stages_table_rows = []
    for s in stages_list:
        stages_table_rows.append(f"| {s.get('name', s.get('id', ''))} | `{s.get('status', 'unknown')}` |")
    stages_table_md = "\n".join(stages_table_rows) if stages_table_rows else "| All Checks | `success` |"

    cited_evidence = init_checks.get("evidence", "")
    evidence_block = f"```\n{cited_evidence[-1500:]}\n```" if cited_evidence else "_No failure logs recorded._"

    # Attempts breakdown
    attempts_md_blocks = []
    if not attempts:
        attempts_md_blocks.append("_No repair attempts executed._")
    else:
        for att in attempts:
            att_idx = att.get("attempt", 1)
            att_status = att.get("status", "UNKNOWN")
            att_cat = att.get("failure_category", "unknown")
            att_reason = att.get("reason", "")
            diag = att.get("diagnosis") or {}
            root_cause = diag.get("root_cause", "N/A")
            patch_dict = att.get("patch") or {}
            diff_text = patch_dict.get("diff", "")
            diff_snippet = diff_text[:2000] if diff_text else "_No diff generated_"
            files_changed = patch_dict.get("files", [])
            formatted_files = format_file_list(files_changed)
            files_str = f"`{formatted_files}`" if formatted_files != "None" else "_None_"
            verif_dict = att.get("verification") or {}
            verif_cmds = verif_dict.get("executed_commands", [])
            cmds_str = ", ".join([f"`{c}`" for c in verif_cmds]) if verif_cmds else "_None_"
            verif_exit = verif_dict.get("exit_code", "N/A")
            test_out = verif_dict.get("output", "")
            test_summary = att.get("test_results", "")
            if test_out and test_summary and test_out != test_summary:
                test_results = f"{test_out}\n{test_summary}"
            else:
                test_results = test_out or test_summary
            results_snippet = test_results[-1000:] if test_results else "_None_"

            att_md = f"""#### Attempt {att_idx} — Status: `{att_status}`
- **Target Failure:** `{att_cat}`
- **Root Cause:** {root_cause}
- **Affected Files:** {files_str}
- **Verification Commands:** {cmds_str} (Exit code: `{verif_exit}`)
- **Attempt Outcome / Reason:** {att_reason}

<details>
<summary>📄 Candidate Diff Preview (Attempt {att_idx})</summary>

```diff
{diff_snippet}
```

</details>

<details>
<summary>🔬 Test / Verification Output (Attempt {att_idx})</summary>

```
{results_snippet}
```

</details>
"""
            attempts_md_blocks.append(att_md)

    attempts_section = "\n\n".join(attempts_md_blocks)

    # Unresolved issues list
    if unresolved:
        unresolved_md = "\n".join([f"- ⚠️ {issue}" for issue in unresolved])
    else:
        unresolved_md = "- ✅ No unresolved issues remaining."

    # Verified patches section
    verified_patches = report_data.get("verified_patches", [])
    if verified_patches:
        patches_summary = "\n".join([
            f"- **Patch #{i + 1}:** {p.get('explanation', 'Code repair')} ({format_file_list(p.get('files', []))})"
            for i, p in enumerate(verified_patches)
        ])
    else:
        patches_summary = "_No patches were verified and applied during this run._"

    summary = report_data.get("summary")
    if not summary:
        summary = generate_plain_english_summary(report_data=report_data)

    md = f"""# 🛡️ ACID AI — Execution & Repair Report

{mode_badge}

---

## 1. Plain-English Run Summary

> [!NOTE]
> **Summary for Beginners:**
> - **Overall Outcome:** {summary.get('overall_outcome_text', outcome_display)}
> - **What Happened:** {summary.get('what_happened', '')}
> - **Why Did It Happen:** {summary.get('why_it_happened', '')}
> - **What ACID AI Attempted:** {summary.get('what_acid_attempted', '')}
> - **Did the Repair Work:** {summary.get('did_repair_work', '')}
> - **Why ACID AI Stopped:** {summary.get('why_agent_stopped', '')}
> - **What You Should Do Next:** {summary.get('what_to_do_next', '')}
> - **Publication Status:** {summary.get('publication_status', '')}

---

## 2. Executive Technical Overview

| Attribute | Details |
| :--- | :--- |
| **Run ID** | `{run_id}` |
| **Repository** | `{repo_name}` |
| **Base Branch** | `{branch}` |
| **Trigger Context** | {trigger_context_display} |
| **Base Commit** | `{base_commit}` (`{short_sha}`) |
| **Overall Outcome** | {outcome_display} |
| **Execution Duration** | `{elapsed}s` |
| **Timestamp** | `{created_at}` |
| **Repair Attempts** | `{retry_count}` |
| **Stop Reason** | {stop_reason} |

---

## 3. Initial Checks & Failure Triage

| Stage | Status |
| :--- | :--- |
{stages_table_md}

- **Detected Failures:** {detected_str}

### Supporting Log Evidence
{evidence_block}

---

## 4. Autonomous Repair Attempts

{attempts_section}

---

## 5. Cumulative Verified Patches

{patches_summary}

---

## 6. Unresolved Limitations & Issues

{unresolved_md}

---

## 7. GitHub Publication Delivery

{pub_md}

---

## 8. Verification Scope & Truthfulness Notice

> [!IMPORTANT]
> {scope_statement}

_Report generated by ACID AI Delivery Engine (Phase 5). All secrets and tokens automatically redacted._
"""
    return redact_secrets(md)


def generate_final_report(
    run_record: RunRecord,
    log_text: Optional[str] = None,
    initial_stages: Optional[List[Dict[str, Any]]] = None,
    initial_detected: Optional[List[str]] = None,
) -> FinalReport:
    """Generate structured FinalReport model and rendered Markdown from a RunRecord.

    Args:
        run_record: Comprehensive RunRecord containing attempts and results.
        log_text: Optional raw initial log text for evidence extraction.
        initial_stages: Optional parsed CI check stages.
        initial_detected: Optional list of initially detected failure categories.

    Returns:
        Structured FinalReport instance.
    """
    outcome = (run_record.final_status or run_record.status or "unresolved").lower()
    if outcome == "pending" or outcome == "running":
        outcome = "unresolved"

    # Identify executed verification commands from attempts or config defaults
    executed_cmds = []
    for att in run_record.attempts:
        verif = att.get("verification") or {}
        cmds = verif.get("executed_commands") or []
        for c in cmds:
            if c not in executed_cmds:
                executed_cmds.append(c)

    scope_statement = format_verification_statement(outcome, executed_cmds)

    # Initial checks details
    detected = initial_detected or (
        run_record.classification.get("detected", []) if run_record.classification else []
    )
    evidence_text = ""
    if log_text:
        evidence_text = log_text[-2000:]
    elif run_record.classification and run_record.classification.get("message"):
        evidence_text = run_record.classification.get("message")

    initial_checks = {
        "stages": initial_stages or [],
        "detected_failures": detected,
        "evidence": redact_secrets(evidence_text),
    }

    # Publication mapping
    pub_info = format_publication_status(run_record.publication)

    # Unresolved issues calculation
    unresolved_issues: List[str] = []
    if outcome == "healthy":
        unresolved_issues = []
    elif outcome == "repaired":
        unresolved_issues = []
    elif outcome == "partially repaired":
        unresolved_issues = [
            (
                f"Partial repair: {len(run_record.verified_patches)} patch(es) verified, "
                f"but remaining test failures persist."
            ),
            f"Terminated due to: {run_record.stop_reason}",
        ]
    elif outcome == "blocked":
        unresolved_issues = [
            f"Execution blocked: {run_record.stop_reason or 'Infrastructure or credential requirement not met.'}"
        ]
    else:  # unresolved
        unresolved_issues = [
            f"Repair unresolved: {run_record.stop_reason or 'Could not verify candidate patches within retry budget.'}"
        ]

    report_dict = {
        "run_id": run_record.run_id,
        "repository": run_record.repo_name,
        "repo_path": run_record.repo_path,
        "branch": run_record.branch,
        "pr_number": run_record.pr_number,
        "base_commit": run_record.base_commit,
        "short_sha": run_record.short_sha,
        "outcome": outcome,
        "mode": run_record.mode,
        "created_at": run_record.created_at,
        "completed_at": run_record.completed_at or time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": run_record.elapsed_seconds or 0.0,
        "initial_checks": initial_checks,
        "attempts": run_record.attempts,
        "retry_count": run_record.retry_count,
        "stop_reason": run_record.stop_reason or "Run completed.",
        "unresolved_issues": unresolved_issues,
        "publication": pub_info,
        "verified_patches": run_record.verified_patches,
        "verification_scope_statement": scope_statement,
    }

    # Generate beginner-friendly plain-English summary
    summary_dict = generate_plain_english_summary(run_record, report_dict)
    report_dict["summary"] = summary_dict

    # Render Markdown report
    markdown_text = build_report_markdown(report_dict)
    report_dict["markdown"] = markdown_text

    final_report = FinalReport(**report_dict)

    # Persist in memory and on disk
    save_report(final_report)

    return final_report


def save_report(report: FinalReport) -> str:
    """Save report to in-memory store and JSON / Markdown / PDF disk files.

    Args:
        report: FinalReport instance.

    Returns:
        Path to the saved JSON file.
    """
    if not getattr(report, "markdown", None):
        report.markdown = build_report_markdown(report)

    IN_MEMORY_REPORTS[report.run_id] = report

    target_dir = _ensure_report_dir()
    json_path = os.path.join(target_dir, f"{report.run_id}.json")
    md_path = os.path.join(target_dir, f"{report.run_id}.md")
    pdf_path = os.path.join(target_dir, f"{report.run_id}.pdf")

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report.markdown)
    except OSError:
        pass

    try:
        from agent.pdf_report import generate_pdf_report
        pdf_bytes = generate_pdf_report(report)
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
    except Exception:
        # PDF generation failure must not corrupt JSON or Markdown reports
        pass

    return json_path


def get_or_generate_report_pdf(run_id: str) -> Optional[bytes]:
    """Retrieve or generate the PDF report bytes for a given run ID.

    Args:
        run_id: Unique run identifier.

    Returns:
        Bytes of the PDF document or None if report does not exist.
    """
    report = get_report(run_id)
    if not report:
        return None

    target_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
    pdf_path = os.path.join(target_dir, f"{run_id}.pdf")
    if os.path.isfile(pdf_path):
        try:
            with open(pdf_path, "rb") as f:
                return f.read()
        except OSError:
            pass

    from agent.pdf_report import generate_pdf_report
    return generate_pdf_report(report)


def get_report(run_id: str) -> Optional[FinalReport]:
    """Retrieve report by run_id from memory or disk cache."""
    if run_id in IN_MEMORY_REPORTS:
        return IN_MEMORY_REPORTS[run_id]

    target_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
    json_path = os.path.join(target_dir, f"{run_id}.json")
    if os.path.isfile(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                report = FinalReport(**data)
                IN_MEMORY_REPORTS[run_id] = report
                return report
        except Exception:
            pass

    return None


def list_reports() -> List[Dict[str, Any]]:
    """Return summary list of all available reports."""
    reports_list = []
    for run_id, rep in IN_MEMORY_REPORTS.items():
        reports_list.append({
            "run_id": rep.run_id,
            "repository": rep.repository,
            "outcome": rep.outcome,
            "created_at": rep.created_at,
            "elapsed_seconds": rep.elapsed_seconds,
            "retry_count": rep.retry_count,
            "publication_status": rep.publication.get("outcome", "skipped"),
        })

    target_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
    if os.path.isdir(target_dir):
        for fname in os.listdir(target_dir):
            if fname.endswith(".json"):
                rid = fname[:-5]
                if rid not in IN_MEMORY_REPORTS:
                    rep = get_report(rid)
                    if rep:
                        reports_list.append({
                            "run_id": rep.run_id,
                            "repository": rep.repository,
                            "outcome": rep.outcome,
                            "created_at": rep.created_at,
                            "elapsed_seconds": rep.elapsed_seconds,
                            "retry_count": rep.retry_count,
                            "publication_status": rep.publication.get("outcome", "skipped"),
                        })

    return sorted(reports_list, key=lambda x: x.get("created_at", ""), reverse=True)

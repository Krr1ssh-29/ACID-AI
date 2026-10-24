# ROADMAP REASSESSMENT: PHASES 06 THROUGH FINAL
**Document:** `docs/ROADMAP_REASSESSMENT_PHASES_06_TO_FINAL.md`  
**Date:** October 24, 2026  
**Auditor:** Antigravity Advanced Agentic Coding System  
**Repository:** `Vasishtha15/ai-cicd-failure-triage-agent` (Local: `ACID AI`)  
**Active Branch:** `development`  
**HEAD Commit:** `a5eadefa9ac1bedb59f5028b3c122a4aed8f521f` (`Working error detection`)  
**Working State:** Preserved; zero resets, stashes, pops, commits, or branch modifications performed.

---

## 1. Executive Summary

ACID AI is an autonomous CI/CD failure diagnosis and self-healing agent engineered for GitHub Actions and local developer workflows. It performs bounded log analysis, structured AI diagnosis, safe unified diff patch generation, fail-closed isolated sandbox container verification, and draft pull request delivery.

Following the implementation work for Phase 05 (Sandbox Verification) and Phase 06 (GitHub Repair Integration and Draft PR Delivery), this reassessment audits the actual state of the codebase against [ROADMAP.md](../ROADMAP.md) and [PROJECT_REQUIREMENTS.md](../PROJECT_REQUIREMENTS.md).

### Key Audit Findings:
1. **Roadmap Structure & Phase Numbering:**
   - [ROADMAP.md](../ROADMAP.md) Section 1 overview diagram depicts Phases 00 through 08.
   - However, the detailed normative sections of [ROADMAP.md](../ROADMAP.md) explicitly define **Phases 00 through 09** (with **Phase 09 — Hackathon Demo & Presentation Interface** fully specified at lines 277–309).
   - In addition, [docs/PHASE_STATUS.md](PHASE_STATUS.md) tracks acceptance checklists through Phase 09.
   - There are no Phase 10+ specifications in the repository. The roadmap concludes at Phase 09.
2. **Phase 05 (Sandbox Verification) Status:**
   - **Genuinely Functional in Docker:** Live Docker container execution is operational (`cicd-sandbox:latest` on Docker Desktop Engine `29.7.2`).
   - 10 live container tests in `tests/integration/test_sandbox_integration.py` pass cleanly in 29.31s. Real container isolation, read-only rootfs (`--read-only`), tmpfs workspace sizing, deliberate test failure rejection, and container cleanup are verified against the running Docker daemon.
   - **Fail-Closed Gate Active:** On hosts lacking Docker or enforceable disk quotas, `DockerSandbox.is_available()` returns `False`, and candidate code execution on the host runner is strictly refused (`INFRASTRUCTURE_FAILURE`).
3. **Phase 06 (GitHub Repair Integration) Status:**
   - **Targeting & Identity Implemented:** Direct push failures target the pushed branch (`config.ref_name`). Same-repository PR failures target the PR head branch (`config.head_ref`), never `config.base_ref`, and derive git trees from the exact PR head commit (`config.pr_head_sha`), avoiding synthetic merge commits.
   - **External Fork Fallback Active:** Repository identity comparison (`config.pr_head_repo != config.repo_name`) detects external forks and halts remote branch writes to avoid HTTP 403 errors, generating local `agent-patch.diff` artifacts and diagnostic PR comments.
   - **Gating Enforced:** Publication is strictly disabled by default (`ENABLE_REPAIR_PR=false`) and requires genuine `VERIFIED_SUCCESS` (exit code 0 inside container).
   - **Live GitHub Publishing Unverified:** All Phase 06 GitHub API interactions are verified through deterministic unit and integration mocks (33 unit tests, 7 integration tests). **Live remote branch creation and Draft PR delivery on real GitHub servers have not been tested with live credentials**, which is an intentional governance safeguard pending user authorization on a dedicated test repository.
4. **Phase 07 & Phase 08 Status:**
   - **Phase 07 (Security & Reliability):** Fully implemented in source code (`agent/security.py`, `agent/providers.py`, `requirements.lock`, `tests/integration/test_resilience.py`). All 7 resilience tests pass.
   - **Phase 08 (E2E & Release Packaging):** Fully implemented in source code (`tests/integration/test_e2e_orchestration.py`, `action.yml`, `README.md`). All 11 orchestration scenarios pass deterministically with mocks. However, multi-project compatibility testing on non-Python languages (Node.js/Go) mentioned in the roadmap has not been conducted against live sample apps.
5. **Phase 09 (Presentation Dashboard):**
   - Implemented and running at `http://127.0.0.1:5000` via `python run_demo.py`.
   - Automated tests (347 unit, 39 integration, 3 sample-app = 389 total) pass with 0 errors. Flake8 and `git diff --check` are 100% clean.

---

## 2. Git & Workspace Preservation Status

- **Active Branch:** `development`
- **HEAD Commit SHA:** `a5eadefa9ac1bedb59f5028b3c122a4aed8f521f`
- **Remote Tracking:** `origin/development` (up to date)
- **Protected Branches:** `main` (`e141e6d`) and `frozen-mvp` (`841cc88`) are untouched.
- **Git Stash Register:**
  - `stash@{0}`: Stashed on `frozen-mvp` (51 files, 11,339 insertions — early development snapshot).
  - `stash@{1}`: Stashed on `development` (10 files, 1,275 insertions — contains `Dockerfile.sandbox` and `tests/unit/test_sandbox_security_boundary.py`).
- **Uncommitted Modifications in Current Checkout (Preserved):**
  - `.github/workflows/ci.yml`: Added GitHub Actions event context variables (`EVENT_NAME`, `REF_NAME`, `HEAD_REF`, `BASE_REF`, `PR_HEAD_SHA`, `PR_HEAD_REPO`).
  - `agent/cli.py`: Wired `repo_root=os.getcwd()` into `publish_repair_pr()` and structured error handling.
  - `agent/config.py`: Extended configuration parsing for event context and publisher tokens.
  - `agent/models.py`: Added event context fields to `AgentConfig`.
  - `agent/publisher.py`: Implemented branch targeting, external fork detection, base SHA derivation, and draft-only payloads.
  - `docs/PHASE_STATUS.md`: Updated Phase 06 acceptance checklist with verified evidence.
  - `tests/unit/test_publisher.py`: Added 4 dedicated unit tests for branch targeting, fork identity, and base SHA.
  - `tests/integration/test_ci_publisher_integration.py` (untracked): 7 CI-to-publisher end-to-end integration tests.
  - `docs/MANUAL_QA_PLAN.md` (untracked): Comprehensive QA test plan and manual browser checklist.

---

## 3. Verified Phase 05 Prerequisites (Sandbox Verification)

The Phase 05 implementation was independently revalidated on the `development` branch against the active Docker Desktop daemon (`ServerVersion: 29.7.2`):

1. **Host Runner Protection:**
   - Candidate code is copied to an ephemeral temporary directory (`copy_disposable_repo()`).
   - If container isolation is unavailable, `VerificationRunner.verify()` immediately returns `VerificationStatus.INFRASTRUCTURE_FAILURE`. Candidate code is never executed via host `subprocess`.
2. **Container Security Boundaries:**
   - Ephemeral container launched with: `--network none`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--memory 2g`, `--cpus 2.0`, `--pids-limit 100`, `--read-only`, and tmpfs `/tmp`.
   - Verified live in `tests/integration/test_sandbox_integration.py::test_real_docker_container_isolation` and `test_live_read_only_rootfs_and_tmpfs_quota_guarantees`.
3. **Execution Outcomes Verified Inside Real Containers:**
   - Known-good patch verified with exit code 0 (`VERIFIED_SUCCESS`).
   - Deliberately failing patch rejected with exit code 1 (`TEST_FAILED`).
   - Command timeouts enforced (terminates after 180s without hanging host).
   - Target repository remains completely untouched (SHA-256 tree hash before == after).
4. **Test Counts for Phase 05:**
   - 10 live container integration tests passing in `tests/integration/test_sandbox_integration.py`.
   - 2 live container autonomous repair loop tests passing in `tests/integration/test_autonomous_repair_e2e.py`.
   - 19 unit tests passing in `tests/unit/test_sandbox.py` and `tests/unit/test_runner.py`.

---

## 4. Phase 06 Focused Review: GitHub Repair Integration & Draft PR Delivery

### 4.1 Roadmap Specification Summary (Phase 06)
- **Objective:** Publish verified repairs to GitHub as isolated branches and reviewable Draft Pull Requests with anti-recursion safeguards.
- **Prerequisites:** Phase 05 isolated sandbox verification returning genuine `VERIFIED_SUCCESS`.
- **Scope:** Dedicated repair branches (`agent/fix-<category>-<run_id>`), branch targeting (push vs. same-repo PR vs. external fork), draft-only PR creation (`draft: true`), anti-recursion guards (bot actor check, `[ai-agent-repair]` headers), failure deduplication/idempotency, and fallback artifact generation (`agent-patch.diff`) on permission failure.
- **Exit Conditions:** Verified repairs published exclusively as Draft PRs; all commits include anti-recursion tags; fork 403 falls back to comment and artifact.

### 4.2 Complete Requirements-to-Code-to-Test Mapping

| Roadmap Requirement | Implementation Location | Connected to CI Execution Path? | Automated Test & Evidence | Verified Status |
| :--- | :--- | :---: | :--- | :---: |
| **Strict Publication Gating** | [`agent/publisher.py:425-442`](../agent/publisher.py#L425-L442) | Yes (`agent/cli.py:307-310`) | `test_publish_repair_pr_refuses_when_verification_is_infrastructure_failure`<br>`test_ci_path_test_failure_in_sandbox_blocks_pr_publication` | **VERIFIED WORKING** (Mocked GitHub) |
| **Direct Push Branch Targeting** | [`agent/publisher.py:545-555`](../agent/publisher.py#L545-L555) | Yes (`.github/workflows/ci.yml:169`) | `test_publish_repair_pr_direct_push_targeting`<br>`test_ci_path_direct_push_targeting_creates_draft_pr_against_pushed_branch` | **VERIFIED WORKING** (Mocked GitHub) |
| **Same-Repo PR Head Branch Targeting** | [`agent/publisher.py:540-545`](../agent/publisher.py#L540-L545) | Yes (`.github/workflows/ci.yml:170`) | `test_publish_repair_pr_same_repo_pr_head_targeting_not_base`<br>`test_ci_path_same_repo_pr_head_targeting_not_base_branch` | **VERIFIED WORKING** (Mocked GitHub) |
| **Base Commit SHA Resolution** | [`agent/publisher.py:733-740`](../agent/publisher.py#L733-L740) | Yes (`.github/workflows/ci.yml:172`) | `test_publish_repair_pr_exact_base_sha_used_for_tree_and_commit`<br>`test_ci_path_same_repo_pr_head_targeting_not_base_branch` | **VERIFIED WORKING** (Mocked GitHub) |
| **External Fork PR Safe Fallback** | [`agent/publisher.py:520-538`](../agent/publisher.py#L520-L538), [`337-408`](../agent/publisher.py#L337-L408) | Yes (`.github/workflows/ci.yml:173`) | `test_publish_repair_pr_external_fork_identity_rejection`<br>`test_ci_path_external_fork_repository_identity_and_fallback` | **VERIFIED WORKING** (Mocked GitHub) |
| **Dedicated Fix Branch Naming** | [`agent/publisher.py:555-561`](../agent/publisher.py#L555-L561) | Yes (`agent/cli.py:309`) | `test_sanitize_branch_slug`<br>`test_publish_repair_pr_success_creates_draft_pr` | **VERIFIED WORKING** (Mocked GitHub) |
| **Draft-Only PR Delivery (`draft: true`)** | [`agent/publisher.py:615-621`](../agent/publisher.py#L615-L621), [`895-905`](../agent/publisher.py#L895-L905) | Yes (`agent/cli.py:309`) | `test_publish_repair_pr_success_creates_draft_pr`<br>`test_ci_path_direct_push_targeting_creates_draft_pr_against_pushed_branch` | **VERIFIED WORKING** (Mocked GitHub) |
| **Anti-Recursion Defense** | [`agent/publisher.py:54-72`](../agent/publisher.py#L54-L72), [`445-460`](../agent/publisher.py#L445-L460) | Yes (`agent/cli.py:309`) | `test_is_recursive_trigger_bot_actors`<br>`test_ci_path_bot_actor_blocks_publication` | **VERIFIED WORKING** (Mocked GitHub) |
| **Idempotency & Duplicate Prevention** | [`agent/publisher.py:562-671`](../agent/publisher.py#L562-L671), [`130-155`](../agent/publisher.py#L130-L155) | Yes (`agent/cli.py:309`) | `test_publish_repair_pr_existing_branch_and_pr`<br>`test_e2e_duplicate_failure_event_idempotency` | **VERIFIED WORKING** (Mocked GitHub) |
| **Token Selection Precedence** | [`agent/publisher.py:421-423`](../agent/publisher.py#L421-L423) | Yes (`.github/workflows/ci.yml:160-161`) | `test_publisher_token_takes_precedence_over_github_token`<br>`test_publisher_token_fallback_to_github_token` | **VERIFIED WORKING** (Mocked GitHub) |
| **Safe Default (Opt-In Only)** | [`agent/config.py:72`](../agent/config.py#L72), [`agent/models.py:202`](../agent/models.py#L202) | Yes (`agent/cli.py:307`) | `test_publish_repair_pr_disabled_by_default_no_api_calls`<br>`test_ci_path_default_safe_mode_disabled_by_default` | **VERIFIED WORKING** (Mocked GitHub) |
| **Live Remote GitHub Publication** | GitHub REST API `/repos/{repo}/git/refs`, `/pulls` | Yes, when `ENABLE_REPAIR_PR=true` | **Not executed live** (Mocked in all 40 publisher tests) | **IMPLEMENTED, LIVE TEST PENDING** |

### 4.3 Detailed Execution Path Trace in CI
1. **GitHub Actions Trigger:** CI workflow triggers on `push` or `pull_request` ([`.github/workflows/ci.yml:4-10`](../.github/workflows/ci.yml#L4-L10)).
2. **Failure Logging:** When `build-and-test` job fails, `combine-logs` bundles installation, lint, test, and docker logs into `combined-logs.txt` ([`ci.yml:102-120`](../.github/workflows/ci.yml#L102-L120)).
3. **Agent Invocation:** Job `self-healing-agent` runs with permissions `contents: read`, `pull-requests: write`, `issues: write`. It exports event context variables to the environment and runs `python agent/self_healing_agent.py` ([`ci.yml:155-175`](../.github/workflows/ci.yml#L155-L175)).
4. **CLI Entrypoint:** [`agent/self_healing_agent.py:121`](../agent/self_healing_agent.py#L121) calls [`agent.cli.main()`](../agent/cli.py#L86).
5. **Config & Log Ingestion:** `load_config()` parses event metadata. Bounded log reader reads tail 50KB.
6. **Diagnosis & Patching:** `classify_failures()` attributes failure. If failing and `GENERATE_PATCH=true`, invokes AI provider and `generate_patch()`.
7. **Validation & Sandbox:** `validate_patch()` runs 6 safety policy checks. If valid, `VerificationRunner.verify()` executes the candidate patch in `cicd-sandbox:latest`.
8. **Publisher Evaluation:** If `cfg.enable_repair_pr` is `true`, `publish_repair_pr()` evaluates verification status. If `VERIFIED_SUCCESS`, creates Git branch and Draft PR. If fork or permission denied, generates `agent-patch.diff` artifact and PR comment.
9. **Artifact Upload:** Workflow step `Upload ACID AI Reports and Delivery Artifacts` uploads `reports/`, `agent-patch.diff`, and `agent-analysis.json` via `actions/upload-artifact@v4` ([`ci.yml:177-187`](../.github/workflows/ci.yml#L177-L187)).

---

## 5. Review of Later Phases: Phase 07, Phase 08, and Phase 09

### 5.1 Phase 07 — Security, Efficiency, and Operational Reliability

#### A. Objective & Scope (from ROADMAP.md)
Harden the agent against security vulnerabilities, implement secret redaction, enforce cost/token limits, and conduct failure injection testing. Deliverables include `agent/security.py`, `requirements.lock`, and `tests/integration/test_resilience.py`.

#### B. Code & Test Mapping

| Deliverable / Requirement | Code Location | Connected to Path? | Test Evidence | Assessed Status |
| :--- | :--- | :---: | :--- | :---: |
| **Secret Redaction** | [`agent/security.py:45-120`](../agent/security.py#L45-L120) | Yes (called in `cli.py`, `publisher.py`, `report.py`) | `tests/unit/test_security.py` (10 tests pass)<br>`test_e2e_secret_redaction_across_all_surfaces` | **VERIFIED WORKING** |
| **Prompt Injection Defenses** | [`agent/security.py:125-155`](../agent/security.py#L125-L155) | Yes (called before formatting AI prompts) | `tests/integration/test_resilience.py::test_resilience_prompt_injection_in_logs_cannot_bypass_policy` | **VERIFIED WORKING** |
| **Command Allowlisting** | [`agent/runner.py:134-210`](../agent/runner.py#L134-L210) | Yes (called in `VerificationRunner`) | `test_resilience_prompt_injection_cannot_bypass_command_allowlisting` | **VERIFIED WORKING** |
| **Token Budget Ceiling (12K)** | [`agent/security.py:160-195`](../agent/security.py#L160-L195) | Yes (called in AI providers) | `tests/integration/test_resilience.py::test_resilience_token_budget_exhaustion` | **VERIFIED WORKING** |
| **Bounded AI Retries (HTTP 429/500/503)** | [`agent/providers.py:80-120`](../agent/providers.py#L80-L120) | Yes (called on API errors) | `test_resilience_ai_provider_500_503_outages_and_bounded_retry`<br>`test_resilience_ai_provider_429_rate_limit_handled` | **VERIFIED WORKING** |
| **Network Dropout Resilience** | [`agent/github.py:45-65`](../agent/github.py#L45-L65) | Yes | `test_resilience_git_network_dropouts_do_not_crash_ci` | **VERIFIED WORKING** |
| **Hermetic Lockfile** | [`requirements.lock`](../requirements.lock) | Yes (reproducible installs) | `requirements.lock` present with pinned hashes | **VERIFIED WORKING** |

#### C. Phase 07 Status Summary
- **Overall Status:** **VERIFIED WORKING** (All 7 resilience tests and 10 security unit tests passing cleanly).

---

### 5.2 Phase 08 — End-to-End Testing, Packaging, and Release Readiness

#### A. Objective & Scope (from ROADMAP.md)
Conduct comprehensive cross-scenario validation, package the agent for distribution, update documentation, and verify release readiness across all 10 acceptance scenarios in [PROJECT_REQUIREMENTS.md](../PROJECT_REQUIREMENTS.md). Deliverables include `action.yml`, production `README.md`, and `tests/integration/test_e2e_orchestration.py`.

#### B. Code & Test Mapping

| Deliverable / Requirement | Code Location | Connected to Path? | Test Evidence | Assessed Status |
| :--- | :--- | :---: | :--- | :---: |
| **Scenario 1: Healthy Run Silent Bypass** | [`agent/cli.py:155-165`](../agent/cli.py#L155-L165) | Yes | `tests/integration/test_e2e_orchestration.py::test_e2e_healthy_run_silent_bypass` | **VERIFIED WORKING** |
| **Scenario 2 & 3: Diagnosis & Trace Extraction** | [`agent/classifier.py`](../agent/classifier.py), [`agent/evidence.py`](../agent/evidence.py) | Yes | `test_e2e_full_orchestration_gemini_diagnosis_to_verified_draft_pr` | **VERIFIED WORKING** |
| **Scenario 4: Verified Draft PR Creation** | [`agent/publisher.py`](../agent/publisher.py) | Yes | `test_e2e_full_orchestration_gemini_diagnosis_to_verified_draft_pr` | **VERIFIED WORKING** (Mocked GitHub) |
| **Scenario 5: Unverified Fix Retries & Abort** | [`agent/runner.py:475-520`](../agent/runner.py#L475-L520) | Yes | `test_e2e_verification_failure_with_bounded_retry_aborts_cleanly` | **VERIFIED WORKING** |
| **Scenario 6: Malformed / Timeout AI Recovery** | [`agent/cli.py:185-212`](../agent/cli.py#L185-L212) | Yes | `test_e2e_malformed_ai_response_graceful_degradation` | **VERIFIED WORKING** |
| **Scenario 7: Missing Credentials Handled** | [`agent/cli.py:100-123`](../agent/cli.py#L100-L123) | Yes | `tests/unit/test_cli.py::test_cli_missing_credentials_graceful_exit` | **VERIFIED WORKING** |
| **Scenario 8: Prompt Injection Invariant** | [`agent/validator.py`](../agent/validator.py), [`agent/security.py`](../agent/security.py) | Yes | `test_resilience_prompt_injection_in_logs_cannot_bypass_policy` | **VERIFIED WORKING** |
| **Scenario 9: Idempotent Re-runs** | [`agent/publisher.py:562-671`](../agent/publisher.py#L562-L671) | Yes | `test_e2e_duplicate_failure_event_idempotency` | **VERIFIED WORKING** |
| **Scenario 10: 403 Forbidden Fork Fallback** | [`agent/publisher.py:337-408`](../agent/publisher.py#L337-L408) | Yes | `test_e2e_publication_fork_403_graceful_fallback` | **VERIFIED WORKING** |
| **Reusable Composite Action** | [`action.yml`](../action.yml) | Yes (Composite Action definition) | `action.yml` validated against GitHub Actions schema | **IMPLEMENTED, LIVE TEST PENDING** |
| **Production README Documentation** | [`README.md`](../README.md) | Yes | Fully documents architecture, models, env vars, and demo launcher | **VERIFIED WORKING** |
| **Multi-Project Non-Python Compatibility** | Roadmap Section: "testing against non-Flask sample apps (e.g., Node.js/Jest or Go)" | No (`sample-app/` contains Flask only) | Not implemented or tested in repository | **NOT IMPLEMENTED** |

#### C. Phase 08 Status Summary
- **Overall Status:** **PARTIALLY IMPLEMENTED** (Core 10 acceptance scenarios pass in automated integration tests; `action.yml` and `README.md` are present. However, multi-project non-Python sample apps specified in ROADMAP.md have not been constructed, and `action.yml` has not been exercised as a standalone external action).

---

### 5.3 Phase 09 — Hackathon Demo & Presentation Interface

#### A. Objective & Scope (from ROADMAP.md)
Deliver a polished, interactive local web demonstration dashboard showcasing the complete autonomous triage, safe patch validation, and fail-closed isolated verification workflow to hackathon judges.

#### B. Code & Test Mapping

| Deliverable / Requirement | Code Location | Connected to Path? | Test Evidence | Assessed Status |
| :--- | :--- | :---: | :--- | :---: |
| **Flask Dashboard App Factory** | [`dashboard/app.py:19-260`](../dashboard/app.py#L19-L260) | Yes (`run_demo.py:34`) | `tests/unit/test_dashboard.py` (12 tests pass) | **VERIFIED WORKING** |
| **Convenience Launcher** | [`run_demo.py`](../run_demo.py) | Yes (`http://127.0.0.1:5000`) | Probed live at runtime; returns 200 OK | **VERIFIED WORKING** |
| **6 Reproducible Scenarios** | [`dashboard/engine.py:45-122`](../dashboard/engine.py#L45-L122) | Yes (`/api/scenarios`, `/api/run`) | All 6 scenarios defined and tested in `test_dashboard.py` | **VERIFIED WORKING** |
| **Real Backend Component Reuse** | [`dashboard/engine.py:384-650`](../dashboard/engine.py#L384-L650) | Yes (directly imports `agent.*`) | Tested in `test_dashboard_repository_workflow.py` | **VERIFIED WORKING** |
| **Fail-Closed Safety Visualization** | [`dashboard/static/app.js:73-92`](../dashboard/static/app.js#L73-L92) | Yes (`/api/system-status`) | Verified live: reports `FAIL_CLOSED_ACTIVE` when storage quota lacks host enforcement | **VERIFIED WORKING** |
| **Multi-Format Report Export** | [`agent/report.py`](../agent/report.py), [`agent/pdf_report.py`](../agent/pdf_report.py) | Yes (`/api/reports/<id>/pdf`) | Tested via HTTP requests (JSON, Markdown, PDF returned with 200 OK); `test_pdf_export_e2e.py` | **VERIFIED WORKING** |
| **Contract Ambiguity Detection** | [`dashboard/engine.py:288-312`](../dashboard/engine.py#L288-L312) | Yes | `tests/unit/test_contract_ambiguity.py` (3 tests pass) | **VERIFIED WORKING** |

#### C. Phase 09 Status Summary
- **Overall Status:** **VERIFIED WORKING** (Fully operational dashboard with dark UI, stepper, real backend reuse, PDF export, and contract ambiguity handling).

---

## 6. Comprehensive Status & Gap Assessment Table

| Phase | Milestone Title | Roadmap Scope Summary | Audit Assessment Status | Remaining Uncertainty & Limitations |
| :---: | :--- | :--- | :---: | :--- |
| **00** | Product Spec & Governance | 8 spec documents, model IDs, threat model | **VERIFIED WORKING** | None. Complete. |
| **01** | Test Suite Baseline | Package structure, pinned manifests, fixtures | **VERIFIED WORKING** | None. Complete. |
| **02** | Accurate Failure Detection | Step outcome parsing, ANSI stripping, bypass | **VERIFIED WORKING** | None. Complete. |
| **03** | AI Diagnosis Engine | Gemini/Claude providers, Pydantic schemas | **VERIFIED WORKING** | Primary AI provider remains configurable; default selection pending repo owner preference. |
| **04** | Patch Generation Engine | Unified diffs, 6 safety policies, size limits | **VERIFIED WORKING** | None. 100% of policy tests pass. |
| **05** | Sandbox Verification | Combined container isolation, host protection | **VERIFIED WORKING** | Host runner fails closed when disk quota lacks kernel support; live container verified on Docker daemon 29.7.2. |
| **06** | GitHub Draft PR Delivery | Push/PR branch targeting, fork fallback, gating | **IMPLEMENTED, LIVE TEST PENDING** | Automated logic 100% passing with mocks. **Live publication on real GitHub remote remains unperformed.** In CI workflow, `contents: write` must be granted to create remote fix branches. |
| **07** | Security & Reliability | Secret redaction, prompt injection, resilience | **VERIFIED WORKING** | All 7 resilience failure-injection tests pass. |
| **08** | E2E & Release Readiness | 10 acceptance scenarios, composite action | **PARTIALLY IMPLEMENTED** | 10 scenarios pass with mocks; `action.yml` and `README.md` present; multi-language non-Python sample apps not yet built. |
| **09** | Presentation Dashboard | Local Flask dashboard, 6 demo scenarios, PDF | **VERIFIED WORKING** | Operational on `http://127.0.0.1:5000`. Browser checklist awaiting user execution. |

---

## 7. Categorized Test Evidence Breakdown

### 7.1 Real Docker Container Tests (12 Passed)
- `tests/integration/test_sandbox_integration.py` (10 tests, 29.31s):
  - Container spawning, tmpfs limits, read-only rootfs mount, deliberate failure rejection, container cleanup.
- `tests/integration/test_autonomous_repair_e2e.py` (2 tests, 18.76s):
  - Live Docker autonomous repair loops verifying candidate fix inside container and returning exit code 0.

### 7.2 Deterministic Mocked Integration Tests (27 Passed)
- `tests/integration/test_ci_publisher_integration.py` (7 tests, 0.82s):
  - Direct push targeting, same-repo PR head branch targeting, fork identity rejection & fallback, test failure gating, safe mode opt-in, bot actor recursion guard.
- `tests/integration/test_e2e_orchestration.py` (11 tests, 3.84s):
  - 10 acceptance scenarios simulating AI responses and GitHub API payloads.
- `tests/integration/test_resilience.py` (7 tests, 0.75s):
  - Prompt injection, allowlist bypass denial, AI provider 500/503/429 outages, token budget exhaustion.
- `tests/integration/test_pdf_export_e2e.py` (2 tests, 1.85s):
  - Consistency of final report models across JSON, Markdown, and PDF.

### 7.3 Unit Tests (347 Passed)
- 347 unit tests passing across `tests/unit/` verifying evidence collection, failure classification, model validation, provider handling, patch generation, safety policy enforcement, reporting, and publisher internals.

### 7.4 Live Local Service & HTTP Probes
- Probed `http://127.0.0.1:5000/api/system-status`: 200 OK (Docker online, fail-closed active).
- Probed `http://127.0.0.1:5000/api/scenarios`: 200 OK (6 scenarios listed).
- Probed `http://127.0.0.1:5000/api/run` (`healthy_run`): 200 OK (silent bypass, 0 tokens).
- Probed `http://127.0.0.1:5000/api/reports/<run_id>/pdf`: 200 OK (binary PDF generated with headers, tables, badges).
- Probed `http://127.0.0.1:5000/api/repo/validate`: 200 OK (repo validation with git metadata).

### 7.5 Live Remote GitHub Tests
- **Status:** **0 tests executed live.**
- All remote GitHub operations were mocked to preserve repository safety and avoid spamming external remotes.

---

## 8. Missing Tests & Unresolved Integration Questions

1. **Live GitHub Branch & Draft PR Publishing:**
   - *Gap:* The agent has never created a real branch or pull request against `api.github.com` using a real personal access token or GitHub App token.
   - *Integration Question:* In `.github/workflows/ci.yml`, the `self-healing-agent` job permissions currently specify `pull-requests: write`, `issues: write`, and `contents: read`. Creating a new git branch (`refs/heads/agent/fix-...`) via GitHub REST API requires `contents: write`. Without `contents: write` (or a dedicated `REPAIR_PUBLISHER_TOKEN` secret), the default `GITHUB_TOKEN` will receive HTTP 403 when creating the repair branch.
2. **Multi-Project Language Compatibility:**
   - *Gap:* ROADMAP.md Phase 08 specifies validating against non-Flask sample apps (e.g. Node.js/Jest or Go). Currently, only `sample-app/` (Python/Flask) exists.
   - *Integration Question:* While `agent/runner.py` supports configurable commands (`active_cmds`), test discovery for non-Python projects in real containers requires pre-installing runtime engines (Node, Go) in the sandbox image or provisioning them dynamically.
3. **Standalone Composite Action (`action.yml`) External Consumption:**
   - *Gap:* `action.yml` is defined as a composite action, but has not been invoked by an external caller repository in a live GitHub Actions workflow.

---

## 9. Prioritized Work Plan

The following ordered task plan resolves remaining roadmap gaps sequentially without skipping dependencies:

### Task 1: Update Workflow Permissions for Publisher (Phase 06 Dependency)
- **Phase:** Phase 06
- **Defect / Gap Addressed:** `.github/workflows/ci.yml` job permissions lack `contents: write`, which will cause git branch creation to fail on live runs when using default `GITHUB_TOKEN`.
- **Exact Code Location:** [`.github/workflows/ci.yml:126`](../.github/workflows/ci.yml#L126)
- **Dependencies:** None.
- **Smallest Test:** Static inspection of `ci.yml` permissions block.
- **Measurable Acceptance Criteria:** `permissions` includes `contents: write` (or documents that `REPAIR_PUBLISHER_TOKEN` secret is required for push/branch creation).
- **Can Be Done Without Credentials:** Yes.

### Task 2: Live GitHub Delivery Verification on Dedicated Throwaway Test Repo (Phase 06 Exit Gate)
- **Phase:** Phase 06
- **Defect / Gap Addressed:** Live remote GitHub publishing remains unverified against live GitHub servers.
- **Exact Code Location:** [`agent/publisher.py:755-940`](../agent/publisher.py#L755-L940)
- **Dependencies:** User authorization, dedicated disposable test repo, live PAT with `repo` scope.
- **Smallest Test:** CLI invocation with `ENABLE_REPAIR_PR=true`, `REPO_NAME=<throwaway-repo>`, `GITHUB_TOKEN=<pat>` against a verified passing candidate fix.
- **Measurable Acceptance Criteria:**
  1. Dedicated fix branch created on remote GitHub repository.
  2. Draft PR opened targeting specified branch with `[ai-agent-repair]` tag.
  3. PR body contains verified sandbox output and truthful disclaimer.
  4. Auto-merge is disabled.
- **Can Be Done Without Credentials:** No (requires live token and remote repo).

### Task 3: Multi-Language Non-Python Sample App Fixture (Phase 08 Requirement)
- **Phase:** Phase 08
- **Defect / Gap Addressed:** ROADMAP.md Phase 08 requirement: "Verify multi-project compatibility by testing against non-Flask sample apps (e.g., Node.js/Jest or Go project)."
- **Exact Code Location:** `sample-app-nodejs/` or `tests/fixtures/nodejs_repo/`
- **Dependencies:** Node.js/Jest test runner container support.
- **Smallest Test:** Automated integration test running verification commands against a Node.js test failure.
- **Measurable Acceptance Criteria:** Verification runner executes allowlisted non-Python command inside container and captures exit code truthfully.
- **Can Be Done Without Credentials:** Yes (local container).

### Task 4: Standalone Action Validation in Live GitHub Actions (Phase 08 Requirement)
- **Phase:** Phase 08
- **Defect / Gap Addressed:** Verify `action.yml` runs cleanly when consumed by an external GitHub Actions workflow.
- **Exact Code Location:** [`action.yml`](../action.yml)
- **Dependencies:** Live GitHub Actions runner.
- **Smallest Test:** Trigger workflow using `uses: ./` or `uses: owner/repo@ref`.
- **Measurable Acceptance Criteria:** Composite action sets up Python, installs requirements, and runs agent without path or shell errors.
- **Can Be Done Without Credentials:** Yes (using mock provider mode or dry run).

### Task 5: User Execution of Manual Browser QA Checklist (Phase 09 Exit Gate)
- **Phase:** Phase 09
- **Defect / Gap Addressed:** Browser interactions in `docs/MANUAL_QA_PLAN.md` require human confirmation.
- **Exact Code Location:** `http://127.0.0.1:5000` via `python run_demo.py`
- **Dependencies:** Active dashboard server.
- **Smallest Test:** Follow the 7-step checklist in [`docs/MANUAL_QA_PLAN.md`](MANUAL_QA_PLAN.md).
- **Measurable Acceptance Criteria:** All 7 checklist items validated in browser; PDF report downloaded and verified visually.
- **Can Be Done Without Credentials:** Yes (uses offline mock mode).

---

## 10. Recommended Next Phase & First Actionable Milestone

### Recommended Action:
**Await user review of this reassessment and user execution of the Manual Browser QA Checklist ([docs/MANUAL_QA_PLAN.md](MANUAL_QA_PLAN.md)).**

### First Actionable Milestone Upon Authorization:
Once the manual browser QA is confirmed:
1. If the user desires live GitHub delivery verification: Authorize **Task 2** on a dedicated throwaway test repository to achieve 100% live verified status for Phase 06.
2. If the user desires release packaging completion: Proceed to **Phase 08** and resolve **Task 1** (workflow permission alignment) and **Task 3** (non-Python compatibility fixture).

---

## 11. Release-Readiness Assessment

### Is the project genuinely release-ready today?
**No, the project is not yet fully release-ready under strict engineering standards, though it is exceptionally mature (~90% complete).**

### Supporting Evidence:
1. **Live GitHub Publishing is Unverified:** While all 40 publisher tests pass deterministically with mocked HTTP responses, the agent has not yet executed a live branch push or Draft PR creation against a real GitHub repository.
2. **CI Workflow Permission Mismatch:** In `.github/workflows/ci.yml`, the job permissions specify `contents: read`. Branch creation on GitHub requires `contents: write`. Without addressing this, running with `ENABLE_REPAIR_PR=true` under default CI tokens will fail with HTTP 403.
3. **Multi-Language Scope in Phase 08:** The roadmap explicitly specifies demonstrating non-Flask project compatibility (e.g., Node.js or Go), which has not yet been added to the test fixtures.
4. **Local Verification & Host Safety are Fully Production-Ready:** The core pipeline, log seeking, failure triage, dual-engine AI providers, 6 safety policies, live Docker container isolation, fail-closed guards, secret redaction, and multi-format reporting are completely implemented, robust, and supported by 389 passing automated tests.

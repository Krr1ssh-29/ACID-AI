# ACID AI — Manual QA Plan & Verification Report
**Date:** October 24, 2026  
**Scope:** Phase 05 (Sandbox Verification) & Phase 06 (GitHub Repair Integration & Draft PR Delivery)  
**Branch:** `development`  
**Git Working Tree State:** Uncommitted modifications preserved; zero commits, pushes, or resets performed.

---

## 1. Working-State Protection & Pre-Flight Baseline

### 1.1 Git Status & Stash Register
- **Current Branch:** `development` (tracking `origin/development`)
- **Stashes Recorded:**
  - `stash@{0}: On frozen-mvp: !!GitHub_Desktop<frozen-mvp>`
  - `stash@{1}: On development: !!GitHub_Desktop<development>`
- **Working Tree Files (Preserved Uncommitted):**
  - Modified: `.github/workflows/ci.yml`
  - Modified: `agent/cli.py`
  - Modified: `agent/config.py`
  - Modified: `agent/models.py`
  - Modified: `agent/publisher.py`
  - Modified: `docs/PHASE_STATUS.md`
  - Modified: `tests/unit/test_publisher.py`
  - Untracked: `tests/integration/test_ci_publisher_integration.py`
- **Rule Adherence:** Zero source code files modified during this QA pass. No git clean, stash, pop, drop, discard, reset, or branch switch executed.

### 1.2 Local Execution Environment
- **Python Version:** Python 3.13.14 (Virtual Environment: `.\.venv\Scripts\python.exe`)
- **Docker Engine:** Docker Desktop 4.89.0 (Engine `29.7.2`, API `1.55`, context `desktop-linux`)
- **Sandbox Image:** `cicd-sandbox:latest` (ID `94996dce5c44`, verified with `pytest 9.1.1` and `flake8 7.4.1`)
- **Dashboard Application:** Flask presentation server running locally on `http://127.0.0.1:5000` via `python run_demo.py`

---

## 2. Automated Regression Evidence Matrix

All automated suites were executed using `.\.venv\Scripts\python.exe`.

| Suite Category | Exact Command | Exit Code | Results | Duration | Service Type |
| :--- | :--- | :---: | :--- | :---: | :--- |
| **Code Style & Lint** | `python -m flake8 --jobs 1 agent dashboard tests sample-app` | `0` | 0 errors | 3.12s | Host static analysis |
| **Whitespace & Line Formats** | `git diff --check` | `0` | 0 whitespace / CRLF errors | 0.08s | Host Git analysis |
| **Sample App Target Suite** | `python -m pytest sample-app/tests/ -v` | `0` | 3 passed | 1.17s | Host Python runner |
| **Integration Suite** | `python -m pytest tests/integration/ -v` | `0` | 39 passed | 48.07s | Hybrid (12 live container tests, 27 mocked network/API tests) |
| **Unit Test Suite** | `python -m pytest tests/unit/ -v` | `0` | 347 passed | 257.74s | Host isolated unit tests (all external I/O mocked) |
| **Total Automated Coverage** | Full combined automated suite | `0` | **389 passed, 0 failed, 0 errors** | ~5.1 min | Mixed |

### Breakdown of Live Container vs. Mocked Tests
1. **Live Container Execution (12 Tests):**
   - `tests/integration/test_sandbox_integration.py`: 10 tests verifying real Docker container creation, command execution, read-only rootfs mount, tmpfs workspace sizing, deliberate test failure rejection, and container cleanup.
   - `tests/integration/test_autonomous_repair_e2e.py`: 2 tests executing complete repair loops inside live Docker containers.
2. **Deterministic Mocked API Execution (377 Tests):**
   - `tests/unit/test_publisher.py` (33 tests) & `tests/integration/test_ci_publisher_integration.py` (7 tests): Mocked GitHub REST API endpoints (`/git/refs`, `/git/commits`, `/git/trees`, `/pulls`, `/issues/comments`). **Zero remote GitHub resources were created.**
   - All AI provider tests (`test_providers.py`, `test_patcher.py`, `test_classifier.py`): Mocked Anthropic and Gemini API responses.

---

## 3. Manual Dashboard Browser QA Checklist

The web dashboard is active at **`http://127.0.0.1:5000`**.  
Execute the following manual verification steps in your web browser:

### Step 1: Baseline Dashboard & Security Guard Status
- [ ] Open `http://127.0.0.1:5000` in the browser.
- [ ] Verify the header displays:
  - `⚡ ACID AI — AI-Powered CI/CD Failure Diagnosis & Self-Healing`
  - Two status pills in top-right:
    - **Docker:** `● Docker: Online`
    - **Gemini:** `● Gemini: No API Key (Offline Mock Active)` (or `Ready` if `GEMINI_API_KEY` is exported)
  - Security Guard indicator:
    - `Fail-Closed Protection Active (Host Runner Protected)` with status `FAIL_CLOSED_ACTIVE`.
- **Status:** `MANUAL TEST REQUIRED`

### Step 2: Demo Mode vs. Repository-First Mode Distinction
- [ ] Observe the two primary tabs: **"Local Repository Analysis"** and **"Presentation Scenarios"**.
- [ ] Click **"Presentation Scenarios"**:
  - Verify 6 cards appear: Healthy CI Pipeline Run, Dependency Installation Failure, Flake8 Code Style Violation, Pytest Assertion Regression, Docker Container Build Failure, Live Sample App Test Suite.
- [ ] Click **"Local Repository Analysis"**:
  - Verify path input field appears with default `D:\C0DE_B00K\Hackathons\innotech4\ACID AI`.
  - Verify metadata displays: Branch (`development`), Base Commit (`841cc88`), Clean Working Tree status, and detected manifest tags.
- **Status:** `MANUAL TEST REQUIRED`

### Step 3: Healthy Run Silent Bypass
- [ ] In **"Presentation Scenarios"**, click **"Healthy CI Pipeline Run"**.
- [ ] Verify:
  - Stepper lights up stages and marks all checks green.
  - Overall Outcome displays **HEALTHY** (green badge).
  - Autonomous Repair Loop displays **0 / 3 Attempts** and **0 Verified Patches**.
  - Log terminal shows clean output (0 tokens spent, 0 PR comments posted).
  - Stop Reason states: `Pipeline healthy: All test and lint checks passed.`
- **Status:** `MANUAL TEST REQUIRED`

### Step 4: Failing Scenario & Truthful Sandbox Verification
- [ ] In **"Presentation Scenarios"**, click **"Dependency Installation Failure"**.
- [ ] Verify:
  - Pipeline Stepper displays `Install` as failed.
  - AI Diagnosis accurately identifies `nonexistent-package==9.9.9`.
  - Code Diff Viewer displays clean syntax-highlighted diff for `sample-app/requirements.txt`.
  - Safety Policy Checklist displays green checkmarks for all 5 security gates.
  - Sandbox Verification displays truthful result (either `VERIFIED_SUCCESS` or `BLOCKED` with host protection notice).
- **Status:** `MANUAL TEST REQUIRED`

### Step 5: Ambiguous Contract Handling (No Blind Guessing)
- [ ] In **"Local Repository Analysis"**, point to a repository with an ambiguous test assertion (e.g. `assert add(2, 2) == 5` vs `def add(a, b): return a + b`).
- [ ] Click **"Run Autonomous Analysis"**.
- [ ] Verify:
  - Diagnosis Root Cause explicitly cites: `Contract ambiguity detected between test and implementation`.
  - Confidence is marked `low`.
  - Zero candidate patches are generated or applied (`fixes: []`).
  - ACID AI refuses to modify either test or application code without specification evidence.
- **Status:** `MANUAL TEST REQUIRED`

### Step 6: Multi-Format Report Export (JSON, Markdown, PDF)
- [ ] Following any completed run, scroll to the **"Plain-English Run Summary & Report Downloads"** section.
- [ ] Verify the 8 structured dimensions are populated:
  1. *Overall Outcome*
  2. *What Happened*
  3. *Why It Happened*
  4. *What ACID AI Attempted*
  5. *Did the Repair Work*
  6. *Why ACID AI Stopped*
  7. *What You Should Do Next*
  8. *Publication Status*
- [ ] Click **"Download JSON Report"** → verify valid JSON file downloads (`acid-ai-report-<run_id>.json`).
- [ ] Click **"Download Markdown"** → verify GitHub Flavored Markdown file downloads.
- [ ] Click **"Download PDF Report"** → verify binary PDF downloads (`acid-ai-report-<run_id>.pdf`) with table layout, headers, and secret redaction.
- **Status:** `MANUAL TEST REQUIRED`

### Step 7: Local Run History & Reset Action
- [ ] Scroll to the **"Session Run History"** table at the bottom of the page.
- [ ] Verify each executed run appears as a row with Timestamp, Scenario / Repository, Outcome Badge, Duration, and Action links.
- [ ] Click **"Reset History"** in the top navigation → verify the table clears cleanly.
- **Status:** `MANUAL TEST REQUIRED`

---

## 4. Phase-by-Phase Verification Findings

### Part D: Sandbox & Repair Isolation QA
| Criterion / Requirement | Status | Evidence |
| :--- | :---: | :--- |
| **Zero Execution on Host Runner** | **PASS** | `VerificationRunner` copies the workspace to a disposable temporary directory (`copy_disposable_repo()`). When Docker is offline or quotas unsupported, `sandbox.is_available()` returns `False` and runner halts with `INFRASTRUCTURE_FAILURE`. Candidate code is never executed via host `subprocess`. Verified in `tests/integration/test_sandbox_integration.py::test_docker_unavailable_refuses_host_execution`. |
| **Live Container Isolation** | **PASS** | Hardened container flags (`--network none`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--memory 2g`, `--cpus 2.0`, `--read-only`, tmpfs `/tmp`) verified live on Docker daemon 29.7.2. Verified in `test_real_docker_container_isolation` and `test_live_read_only_rootfs_and_tmpfs_quota_guarantees`. |
| **Candidate Rejection & Acceptance** | **PASS** | Deliberately failing test candidate is rejected inside container with exit code 1 (`TEST_FAILED`); valid candidate passes with exit code 0 (`VERIFIED_SUCCESS`). Verified in `test_verification_runner_verifies_known_good_candidate` and `test_verification_runner_rejects_deliberately_failing_candidate`. |
| **Bounded Retries & Terminations** | **PASS** | Autonomous repair loop strictly limits iterations to `max_attempts = 2` (or 3). Duplicate patches terminate immediately without looping. Verified in `test_run_repair_loop_terminates_after_2_attempts`. |
| **Target Repository Immutability** | **PASS** | SHA-256 tree hashes of target repository before and after repair verification are identical. Verified in `test_original_repository_immutability_guaranteed`. |

### Part E: Phase 06 Publisher Safety & Gating
| Criterion / Requirement | Status | Evidence |
| :--- | :---: | :--- |
| **Disabled by Default** | **PASS** | `ENABLE_REPAIR_PR` defaults to `false`. Zero GitHub API write calls are made unless explicitly set to `true`. Verified in `test_publish_repair_pr_disabled_by_default_no_api_calls` and `test_ci_path_default_safe_mode_disabled_by_default`. |
| **Strict Publication Gating** | **PASS** | `publish_repair_pr()` strictly requires `verification.status in (VERIFIED, VERIFIED_SUCCESS) and verification.exit_code == 0`. Unverified, failed, or blocked runs return `SKIPPED_UNVERIFIED` with zero git writes. Verified in `test_ci_path_test_failure_in_sandbox_blocks_pr_publication` and `test_ci_path_docker_offline_blocks_pr_publication`. |
| **Direct Push Branch Targeting** | **PASS** | Direct push failures resolve target branch to `config.ref_name` (e.g. `develop`), basing the commit on the pushed tip SHA. Verified in `test_publish_repair_pr_direct_push_targeting` and `test_ci_path_direct_push_targeting_creates_draft_pr_against_pushed_branch`. |
| **Same-Repo PR Head vs Base Targeting** | **PASS** | Pull request failures set draft PR target to `config.head_ref` (the PR author's branch), **NEVER** `config.base_ref`. Base commit parent is derived from `config.pr_head_sha`, avoiding GitHub's synthetic merge commit (`refs/pull/:id/merge`). Verified in `test_publish_repair_pr_same_repo_pr_head_targeting_not_base` and `test_ci_path_same_repo_pr_head_targeting_not_base_branch`. |
| **External Fork PR Safe Fallback** | **PASS** | Identifies external forks via repository identity check (`config.pr_head_repo != config.repo_name`). Aborts remote branch push to prevent HTTP 403 errors, writes `agent-patch.diff` artifact, and posts diagnostic comment. Verified in `test_publish_repair_pr_external_fork_identity_rejection` and `test_ci_path_external_fork_repository_identity_and_fallback`. |
| **Anti-Recursion Defense** | **PASS** | Bot actors (`github-actions[bot]`, `[ai-agent-repair]`) abort publication before network calls. Verified in `test_ci_path_bot_actor_blocks_publication`. |
| **Draft-Only PR Creation** | **PASS** | REST payload explicitly specifies `{"draft": true}` for initial PR creation and partial recovery. |
| **Live Remote GitHub Publication** | **NOT TESTED (MOCKED ONLY)** | All GitHub API interactions were tested via unit and integration mocks. **Live publication against a real GitHub remote remains intentionally unverified** until authorized against a dedicated throwaway test repository. |

### Part F: Reporting & Security
| Criterion / Requirement | Status | Evidence |
| :--- | :---: | :--- |
| **Secret Redaction** | **PASS** | `redact_secrets()` sanitizes GitHub PATs, Anthropic keys, Gemini keys, AWS keys, and custom secrets across JSON, Markdown, and PDF outputs. Verified in `test_security.py` and `test_e2e_secret_redaction_across_all_surfaces`. |
| **Single Source of Truth** | **PASS** | JSON, Markdown, and PDF share identical final report data models (`FinalReport`). Verified in `test_scenario_run_multi_format_export_consistency`. |
| **Report Download Endpoints** | **PASS** | `GET /api/reports/<id>` (200 JSON), `/markdown` (200 text/markdown), `/pdf` (200 application/pdf). Unknown IDs return structured 404 JSON. Verified via automated and HTTP tests. |

---

## 5. Identified Limitations & Observations

1. **Live Remote GitHub Publication Unexecuted:**
   - *Observation:* No real GitHub pull requests or branches were created on GitHub servers. Testing strictly relied on deterministic API mocks to protect the repository and avoid spamming remote branches.
   - *Severity:* Informational / Planned Safeguard.
   - *Action:* Requires repository owner authorization against a dedicated test repo before live publication can be demonstrated.
2. **Docker Storage Quota Probe Latency:**
   - *Observation:* On Docker Desktop for Windows (WSL 2 backend), running live container verification takes ~30–50 seconds per scenario due to cold container launch and disk write quota validation probes.
   - *Severity:* Low / UX Latency.
   - *Action:* Dashboard UI includes visual steppers and loading indicators to communicate progress truthfully without timing out.

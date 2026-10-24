# ACID AI — Phase 0: Implementation Audit

**Audit Timestamp:** 2026-10-23T00:15:00+05:30  
**Repository:** `Vasishtha15/ai-cicd-failure-triage-agent` (Local: `ACID AI`)  
**Commit Inspected:** `841cc88b9727ac398c65ec4534e5f4ac40e60d7b`  
**Audit Objective:** Determine how much of the existing application is genuinely implemented and how much relies on deterministic mock fixtures or incomplete integrations.

---

## Executive Summary

ACID AI is a modular, defense-in-depth automated CI/CD failure triage and self-healing agent with an accompanying presentation dashboard.

Across the codebase, the **core agent pipeline (log seeking, ANSI stripping, step outcome parsing, failure classification, Pydantic schema validation, patch parsing, safety validation policies, disposable workspace isolation, credential stripping, secret redaction, and GitHub Git Database tree-building) is genuinely and robustly implemented in real Python code**.

However, three primary architectural disconnects and mock dependencies currently prevent hands-off, end-to-end autonomous healing in real-world CI:
1. **CI Workflow Disconnect:** `.github/workflows/ci.yml` invokes `agent/self_healing_agent.py` without setting `GENERATE_PATCH=true` or `ENABLE_REPAIR_PR=true`, and restricts GitHub Actions job permissions to `contents: read`. As a result, CI execution is currently limited to diagnosis and PR comment posting; automated patch generation and Draft PR creation are never executed in GitHub Actions.
2. **Infrastructure Fail-Closed Gate:** `DockerSandbox` enforces `require_disk_quota=True` by default. Because standard Linux `overlay2` storage drivers (and Docker Desktop on Windows/macOS) do not enforce `--storage-opt size=` on unpartitioned backing filesystems, the quota probe (`check_disk_quota_enforcement`) consistently fails. The agent truthfully fails closed with `INFRASTRUCTURE_FAILURE` and refuses to execute candidate code on the host runner.
3. **Container Test Runtime Dependencies:** The sandbox container image defaults to `python:3.11-slim`. Standard `python:3.11-slim` lacks `pytest` and `flake8`. In a zero-network environment (`--network none`), running `pytest` will fail unless test dependencies are pre-baked into the image.
4. **Dashboard Mock vs Live Mode:** The presentation dashboard uses static mock fixtures (`tests/fixtures/*.txt`, `MOCK_ANALYSES`, `MOCK_DIFFS`) for 4 of its 6 scenarios to ensure 100% reliable offline presentation without Wi-Fi or API credits. Live Gemini calling is genuinely implemented when toggled and supplied with an API key, but verification strictly demonstrates the fail-closed blocker unless Docker quota checks are bypassed.

---

## 1. Component Inventory

The repository contains 79 tracked files organized into 6 subsystems:

```
ACID AI/
├── agent/                      # Core triage & self-healing engine (18 modules)
│   ├── classifier.py           # Step outcome & regex failure classifier
│   ├── cli.py                  # CLI entrypoint & orchestration loop
│   ├── collector.py            # Bounded memory-safe tail log reader (50KB)
│   ├── config.py               # Environment configuration & credential validator
│   ├── evidence.py             # ANSI stripping, section splitting, stacktrace extractor
│   ├── formatter.py            # Markdown PR comment formatter
│   ├── github.py               # GitHub REST API PR comment client
│   ├── models.py               # Pydantic v2 data models & enums
│   ├── parser.py               # JSON extractor for model responses
│   ├── patcher.py              # Unified diff prompt builder & patch generator
│   ├── providers.py            # Claude (SDK) & Gemini (REST) AI providers
│   ├── publisher.py            # GitHub Git Database Draft PR deliverer
│   ├── runner.py               # Disposable workspace & repair loop runner
│   ├── sandbox.py              # Hardened Docker container sandbox & quota probe
│   ├── security.py             # Credential regex scrubber & prompt injection defanger
│   ├── self_healing_agent.py   # Backwards-compatible legacy entrypoint
│   └── validator.py            # Unified diff parser & 6-policy safety gate
├── dashboard/                  # Presentation web interface (6 files)
│   ├── app.py                  # Flask application factory & API routes
│   ├── engine.py               # Scenario orchestrator & mock/live dispatch
│   ├── static/app.js           # Interactive UI state machine & diff renderer
│   ├── static/style.css        # Glassmorphic dark theme CSS design system
│   └── templates/index.html    # Single-page dashboard template
├── docs/                       # Specifications & development governance
│   ├── CONFIGURATION.md        # Environment variables & flags
│   ├── DEVELOPMENT_PROTOCOL.md # Engineering rules & verification requirements
│   ├── IMPLEMENTATION_AUDIT.md  # This document
│   └── PHASE_STATUS.md         # Detailed status across all roadmap phases
├── sample-app/                 # Reference target application
│   ├── app.py                  # Demo Flask application
│   ├── Dockerfile              # Container definition for sample app
│   ├── requirements.txt        # Flask & requests dependencies
│   └── tests/test_app.py       # Pytest unit tests for sample app
├── tests/                      # Automated test suite (23 modules + 5 fixtures)
│   ├── fixtures/               # Real & synthetic pipeline failure logs
│   ├── integration/            # E2E orchestration, resilience, & sandbox tests
│   └── unit/                   # Comprehensive unit tests for every agent module
├── .github/workflows/ci.yml    # GitHub Actions workflow
├── action.yml                  # Standalone GitHub Composite Action definition
├── pyproject.toml              # Build configuration & dependency manifests
├── requirements.txt            # Runtime dependencies (requests, anthropic, pydantic)
├── requirements-dev.txt        # Development dependencies (pytest, flake8, coverage)
├── requirements.lock           # Hermetically pinned lockfile
└── run_demo.py                 # Convenience launcher for presentation dashboard
```

---

## 2. Implemented and Tested Capabilities

The following capabilities are **genuinely implemented in production code** and verified by automated tests:

### 2.1 Log Ingestion & Bounded Seeking (`agent/collector.py`, `agent/evidence.py`)
- **Seek-based tail reading:** Direct filesystem `f.seek(file_size - max_bytes)` prevents memory exhaustion when reading arbitrarily large log files (50 KB ceiling).
- **ANSI sequence stripping:** High-performance regex removes terminal color and cursor codes.
- **Authoritative outcome extraction:** Parses `=== STEP OUTCOMES ===` blocks (`install`, `lint`, `test`, `docker`) mapping to strongly-typed `StepOutcome` enums (`SUCCESS`, `FAILURE`, `SKIPPED`, `CANCELLED`).
- **Stack trace isolation:** Extracts the most relevant failure window (50 lines) around tracebacks and assertion errors for targeted prompt context.

### 2.2 Failure Classification & Silent Bypass (`agent/classifier.py`)
- **Truthful Status Attribution:** Assigns `PipelineStatus.HEALTHY`, `FAILED`, `INCONCLUSIVE`, or `ERROR`.
- **Silent Healthy Bypass:** When step outcomes indicate all executed steps succeeded, the agent exits with code 0 without calling AI models or posting comments (0 tokens, 0 API calls).
- **Narrow Regex Fallback:** If `=== STEP OUTCOMES ===` is absent, falls back to targeted compiler and test error signatures, avoiding false positives on common utility names.

### 2.3 AI Provider Integrations (`agent/providers.py`)
- **Dual-Engine Architecture:** Real implementations for Anthropic Claude (`claude-sonnet-4-6` via `anthropic` SDK) and Google Gemini (`gemini-3.8-flash` via REST API).
- **Secure Header Authentication:** Gemini API keys are sent via `x-goog-api-key` HTTP headers; keys are **never** passed as URL query parameters.
- **Bounded Retries & Exponential Backoff:** Transient network errors (HTTP 5xx, timeouts) and rate limits (HTTP 429) retry up to 2 times with exponential delay (`delay = backoff_factor * 2^attempt`). Permanent authentication errors (HTTP 401, 403) fail fast immediately.
- **Token Budget Ceiling:** Enforces a 12,000-token prompt budget heuristic (`char_count // 4`), raising `TokenBudgetExceededError` before calling external APIs.
- **Schema Validation:** Enforces Pydantic model validation (`AnalysisResult`) over model JSON outputs, reinforcing prompt instructions on validation retry.

### 2.4 Patch Safety Policy Validation (`agent/validator.py`, `agent/patcher.py`)
- **Unified Diff Parser:** Parses unified diff format into structured `FilePatch` objects calculating additions, deletions, and hunk counts.
- **Path Allowlisting:** Strictly restricts modifications to allowlisted prefixes (`sample-app/`, `src/`, `tests/`) and root manifests (`requirements.txt`, `pyproject.toml`, `Dockerfile`).
- **Path Traversal & Escape Prevention:** Rejects absolute paths (`/etc/passwd`), traversal sequences (`../`), and prohibited paths (`.github/`, `.git/`, `.env`, private keys).
- **Hard Size Boundaries:** Rejects patches touching > 5 files or > 150 lines.
- **Non-Destructive Guarantee:** Forbids binary diffs and file deletions.
- **In-Memory Repository Matching:** Verifies diff context against local repository file contents without modifying the working tree.

### 2.5 Disposable Workspace & Isolation Protection (`agent/runner.py`, `agent/sandbox.py`)
- **Zero Host Mutation:** Creates an ephemeral copy in `tempfile.TemporaryDirectory`, ignoring `.git/`, `.venv/`, caches, and credentials.
- **Hardening Flags:** Generates Docker run commands with `--network none`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--user 1000:1000`, `--memory 2g`, `--cpus 2.0`, `--pids-limit 100`, and a read-only volume mount.
- **Command Allowlisting:** Only permits tokenized `pytest` and `flake8` commands with strictly allowlisted flags; shell metacharacters (`;`, `&&`, `|`, `` ` ``, `$()`) are blocked.
- **Fail-Closed Isolation Guard:** If container isolation or disk quotas are unavailable, execution **strictly refuses** to run candidate code on the host runner and assigns `VerificationStatus.INFRASTRUCTURE_FAILURE`.

### 2.6 Credential Redaction & Security (`agent/security.py`)
- **Multi-Format Redaction:** Scrubs Google API keys, Anthropic keys, GitHub PATs (classic, OAuth, fine-grained, server-to-server), AWS keys, Slack tokens, and PEM private keys across all outbound text (PR comments, PR bodies, diffs, log traces).
- **Adversarial Prompt Defense:** Defangs XML delimiters (`</untrusted_ci_logs>`) and null bytes inside untrusted CI logs.

### 2.7 GitHub Git Database Draft PR Publishing (`agent/publisher.py`)
- **Git Database REST API:** Directly creates blobs, trees, and commits via `/repos/{repo}/git/*` endpoints, avoiding local git subprocess executions.
- **Draft-Only Gating:** Requires `VerificationStatus.VERIFIED` before creating branches or pull requests. Sets `"draft": true`.
- **Anti-Recursion Loop Protection:** Aborts immediately if the commit author is `github-actions[bot]` or if the commit message contains `[ai-agent-repair]`.
- **Idempotency:** Checks for existing repair branches and open PRs matching the failure fingerprint to prevent duplicate PR spam.
- **Fork Fallback:** If branch creation receives HTTP 403 (fork repository without write access), falls back to saving `agent-patch.diff` and posting a diagnostic comment with the diff attached.

---

## 3. Mock-Only Capabilities

The following features currently rely on **mock data, pre-canned fixtures, or simulated responses**:

| Feature / Flow | Location | Mechanism | Reason / Impact |
| :--- | :--- | :--- | :--- |
| **Offline Demo Mode** | `dashboard/engine.py` | `MOCK_ANALYSES`, `MOCK_DIFFS`, `MockDemoAIProvider` | Provides 100% deterministic, zero-latency execution for 4 demo scenarios without requiring API keys or internet connection. |
| **Demo Scenario Input Logs** | `dashboard/engine.py` | `tests/fixtures/*.txt` | 4 of 6 demo scenarios load static fixture files instead of capturing real live GitHub Actions logs. |
| **Hermetic Test Suite Calls** | `tests/unit/`, `tests/integration/` | `unittest.mock.patch` | External APIs (Claude, Gemini, GitHub) are mocked in automated tests to prevent incurring external billing, flaky network runs, or credential leakage during CI runs. |
| **Live Sample App Demo Scenario** | `dashboard/engine.py:execute_live_pytest` | Host `subprocess.run(["pytest", ...])` | Executes real `pytest` locally on `sample-app/tests`. However, because the sample app tests currently pass, this scenario always results in `PipelineStatus.HEALTHY` (silent bypass) rather than demonstrating failure triage. |

---

## 4. Incomplete or Disconnected Integrations

### 4.1 CI Workflow Does Not Trigger Self-Healing (`.github/workflows/ci.yml`)
- **Problem:** In `.github/workflows/ci.yml`, the `self-healing-agent` step invokes:
  ```yaml
  - name: Run ACID AI
    env:
      AI_PROVIDER: ${{ secrets.AI_PROVIDER }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      PR_NUMBER: ${{ github.event.pull_request.number }}
      REPO_NAME: ${{ github.repository }}
      COMMIT_SHA: ${{ github.sha }}
      RUN_ID: ${{ github.run_id }}
    run: |
      python agent/self_healing_agent.py
  ```
- **Consequence:** `GENERATE_PATCH` and `ENABLE_REPAIR_PR` are **not set** in the workflow environment. In `agent/config.py`, `generate_patch` defaults to `False`. Therefore, whenever CI runs in GitHub Actions, ACID AI **only** analyzes logs and posts a PR comment with fix suggestions. It **never** generates unified diffs, runs sandbox verification, or opens Draft PRs in CI.

### 4.2 Insufficient Workflow Permissions for Draft PRs (`.github/workflows/ci.yml`)
- **Problem:** In `.github/workflows/ci.yml`:
  ```yaml
  permissions:
    pull-requests: write
    issues: write
    contents: read
  ```
- **Consequence:** `contents: read` prevents the agent from creating Git branches or pushing Git tree references via the GitHub REST API. Even if `GENERATE_PATCH=true` were passed, GitHub's API returns `HTTP 403 Forbidden` on `POST /repos/{repo}/git/refs`. The agent will trigger its fork fallback (posting a comment with the diff) instead of publishing a true Draft PR. `contents: write` is required to create repair branches.

### 4.3 Container Image Missing Test Dependencies (`agent/sandbox.py`)
- **Problem:** `DockerSandbox` defaults to `image="python:3.11-slim"`.
- **Consequence:** `python:3.11-slim` is a minimal Linux image without `pytest`, `flake8`, `flask`, or `requests` installed. Because the container is hardened with `--network none`, it cannot run `pip install` during verification. If the sandbox attempts to run `pytest tests/`, it fails because `pytest` does not exist inside the default container image.

### 4.4 Hardcoded Disk Quota Enforcement Blocks Execution (`agent/sandbox.py`)
- **Problem:** `DockerSandbox` sets `require_disk_quota=True` by default, and `agent/config.py` does not provide an environment variable to configure this.
- **Consequence:** `check_disk_quota_enforcement()` writes 10MB against `--storage-opt size=5M`. On standard Linux kernels (without xfs/ext4 project quotas) and Docker Desktop (Windows/macOS), the write succeeds. This causes `is_available()` to return `False`. In standard CI runners, the verification stage will **always** fail closed (`INFRASTRUCTURE_FAILURE`), preventing any candidate patch from being marked `VERIFIED`.

### 4.5 Package Namespace Collision in Test Discovery (`sample-app/tests/` vs `tests/`)
- **Problem:** Both the repository root (`tests/__init__.py`) and the reference application (`sample-app/tests/__init__.py`) define packages named `tests`.
- **Consequence:** Running `pytest` across all directories simultaneously using pytest's default import mode fails during collection with `ModuleNotFoundError: No module named 'tests.test_app'`. Running tests requires either `--import-mode=importlib` or running test directories separately (`pytest tests/unit tests/integration` and `pytest sample-app/tests`).

### 4.6 Missing Dashboard Dependencies in Base Requirements (`requirements.txt`)
- **Problem:** Root `requirements.txt` only lists `requests`, `anthropic`, and `pydantic`.
- **Consequence:** If a user runs `pip install -r requirements.txt` and attempts to start the presentation dashboard via `python run_demo.py`, execution fails with `ModuleNotFoundError: No module named 'flask'`. `flask` is only pinned in `requirements.lock` and `requirements-dev.txt`.

---

## 5. Security Risks and Infrastructure Blockers

| Subsystem | Risk / Blocker | Severity | Mitigation in Code | Status |
| :--- | :--- | :---: | :--- | :---: |
| **Sandbox Execution** | Untrusted candidate code escaping container | **CRITICAL** | Hardened container flags: `--network none`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--user 1000:1000`, `--memory 2g`, `--cpus 2.0`, `--pids-limit 100`. | ✅ Verified in live Docker test |
| **Host Runner Safety** | Candidate code executing on host when Docker is down | **CRITICAL** | Zero-execution invariant: if Docker is unavailable, raises `SandboxInfrastructureError` and assigns `INFRASTRUCTURE_FAILURE`. | ✅ Verified by test suite |
| **Credential Exfiltration** | Secrets leaked in PR comments or candidate diffs | **HIGH** | `agent/security.py` regex scrubbers redact Google, Anthropic, GitHub, AWS, and Slack tokens. Sanitized environment in sandbox. | ✅ Verified by test suite |
| **Prompt Injection** | Adversarial CI logs attempting instruction override | **HIGH** | Untrusted logs are XML-wrapped and closing tags (`</untrusted_ci_logs>`) are defanged. Strict Pydantic output schema validation. | ✅ Verified by test suite |
| **Infinite CI Loops** | Automated repair commits re-triggering CI workflow | **HIGH** | Anti-recursion detection checks for `github-actions[bot]` and `[ai-agent-repair]` commit tags, immediately halting further PR creation. | ✅ Verified by test suite |
| **Disk Quota Support** | Storage driver lacking `--storage-opt size=` | **BLOCKER** | Hard fail-closed probe blocks candidate verification on standard GitHub Actions runners and Docker Desktop. | ⚠️ Prevents live verification |

---

## 6. Test Suite Execution Evidence

All automated test suites were executed locally using the virtual environment `.venv/Scripts/python` on Windows:

### 6.1 Test Execution Summary

```bash
.\.venv\Scripts\python -m pytest --import-mode=importlib tests/unit tests/integration sample-app/tests
```

**Results:**
- **Total Tests Collected:** 260
- **Passed:** 260
- **Failed:** 0
- **Skipped:** 0
- **Total Duration:** 93.52 seconds

### 6.2 Test Breakdown by Category

| Test Suite | Files | Tests | Result | Notes |
| :--- | :---: | :---: | :---: | :--- |
| **Unit Tests (`tests/unit/`)** | 19 | 236 | ✅ **236 Passed** | Covers classifier, collector, config, dashboard, evidence, formatter, github, models, parser, patcher, providers, publisher, runner, sandbox, security, validator. |
| **Integration Tests (`tests/integration/`)** | 3 | 21 | ✅ **21 Passed** | Covers end-to-end orchestration, prompt injection resilience, network dropouts, rate limits, token budget exhaustion, and live Docker container isolation. |
| **Sample App Tests (`sample-app/tests/`)** | 1 | 3 | ✅ **3 Passed** | Verifies reference Flask application endpoints (`/`, `/health`). |

### 6.3 Statement Coverage (`pytest-cov` on `agent/`)

```
Name                          Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------------------
agent\__init__.py                18      0      0      0   100%
agent\__main__.py                 4      0      2      1    83%   5->exit
agent\classifier.py              58      0     30      1    99%   106->103
agent\cli.py                    101      7     26      5    91%   25->30, 28-29, 30->36, 33-34, 99-100, 129->135, 135->148, 153
agent\collector.py               30      0      8      1    97%   51->53
agent\config.py                  64     16      6      0    77%   26-27, 32-33, 38-39, 44-45, 50-51, 59-60, 67-68, 78-79
agent\evidence.py                48      4     20      3    90%   58-59, 88, 99->96, 116
agent\formatter.py               25      0      6      0   100%
agent\github.py                  30      5      6      0    86%   56-60
agent\models.py                 188     11      4      0    94%   57, 275, 279, 305, 309, 320, 324, 339, 343, 417, 421
agent\parser.py                  15      0      6      0   100%
agent\patcher.py                 78      7     22      6    87%   109->111, 111->113, 122-125, 130, 138->140, 140->142, 216-217
agent\providers.py              210     20     54      8    89%   74, 152, 169->184, 176->178, 180-182, 206->232, 252-253, 275-280, 314-316, 345, 369, 382, 393
agent\publisher.py              301     69    126     22    74%   62->77, 74-75, 110, 122, 202-203, 210->213, 246->253, 250-251, 258->270, 262-263, 266-267, 319->325, 323-324, 352-353, 356->exit, 392-393, 469, 516, 563-594, 621-644, 654, 659-660, 688-689, 695, 700-701, 722-723, 729, 734-735, 754, 761-766, 796-830
agent\runner.py                 198     29     94     13    86%   126-129, 157-158, 161, 183, 188, 190, 193, 202, 204, 256-257, 260->243, 262, 267-268, 288-289, 300-301, 380-381, 392, 445-446, 460, 465
agent\sandbox.py                 83      6     18      0    94%   88, 109, 167-168, 186-187
agent\security.py                44      7     26      3    80%   58, 102-106, 122
agent\self_healing_agent.py      43      2      4      2    91%   28, 125
agent\validator.py              260     31    134     21    86%   78, 98, 119, 122, 130, 172-175, 195, 217, 223, 230-232, 282-299, 339-346, 382-383, 385->389, 393->396, 420->428, 430->416, 444-452, 461, 546-552, 589->600, 621
-------------------------------------------------------------------------
TOTAL                          1798    214    592     86    86%
```

- **Overall Agent Coverage:** **86% statement coverage**
- **PEP 8 Compliance:** `flake8 agent tests` returned 0 errors / 0 warnings.
- **Git Working Tree:** `git diff --check` returned 0 whitespace or formatting errors.

---

## 7. Prioritized Roadmap for a Working End-to-End System

To transition ACID AI from a diagnostic commenter and offline presentation demo to a fully autonomous, live self-healing pipeline agent, the following changes are required in order of priority:

### Priority 1: Connect Self-Healing in GitHub Actions CI
- **Files:** `.github/workflows/ci.yml`
- **Actions:**
  1. Add `contents: write` to the `self-healing-agent` job permissions block so GitHub allows branch creation.
  2. Pass `GENERATE_PATCH: "true"` and `ENABLE_REPAIR_PR: "true"` in the step environment.
  3. Ensure active AI provider selection (`AI_PROVIDER: gemini` or `claude`) and API key secrets are populated.

### Priority 2: Configurable Sandbox Disk Quota Enforcement
- **Files:** `agent/config.py`, `agent/runner.py`, `agent/sandbox.py`
- **Actions:**
  1. Add `REQUIRE_DISK_QUOTA` environment variable to `agent/config.py` (defaulting to `false` for standard CI and development runners, while logging an explicit security warning).
  2. Pass this setting from `AgentConfig` into `DockerSandbox(require_disk_quota=config.require_disk_quota)`.
  3. This will allow candidate patches to be verified inside Docker containers on standard GitHub Actions runners without being blocked by lack of kernel-level filesystem quota support.

### Priority 3: Pre-Built Sandbox Test Container Image
- **Files:** `Dockerfile.sandbox` (new), `agent/config.py`, `action.yml`, `.github/workflows/ci.yml`
- **Actions:**
  1. Define and publish a dedicated sandbox test runner image (e.g. `ghcr.io/vasishtha15/acid-ai-sandbox:latest`) containing Python 3.11, `pytest`, `flake8`, and standard testing utilities.
  2. Configure `SANDBOX_IMAGE` to point to this image.
  3. This ensures that `--network none` verification can execute `pytest` and `flake8` commands successfully.

### Priority 4: Disambiguate Test Package Namespaces
- **Files:** `pyproject.toml`, `sample-app/tests/`
- **Actions:**
  1. Add `--import-mode=importlib` to `[tool.pytest.ini_options]` `addopts` in `pyproject.toml`.
  2. Alternatively, rename `sample-app/tests/` to `sample-app/test_suite/` to eliminate the package name collision with root `tests/`.

### Priority 5: Add Flask to Base Runtime Dependencies
- **Files:** `requirements.txt`
- **Actions:**
  1. Add `flask==3.0.3` to root `requirements.txt` so users running `python run_demo.py` directly after `pip install -r requirements.txt` do not encounter missing dependency errors.

### Priority 6: Dynamic Failure Injection Demo Scenario
- **Files:** `dashboard/engine.py`
- **Actions:**
  1. Add a demo scenario (`live_failing_sample_app`) that deliberately modifies `sample-app/app.py` in a temporary workspace, executes live local pytest to generate real failing log output, and runs the entire live diagnosis-to-patch pipeline in real time.

---

## 8. Phase 4 Update: Autonomous Repair and Retry Loop

**Status:** Completed & Fully Verified  
**Date:** 2026-10-23  

In Phase 4, the repository-first workflow (`run_repository_analysis`) and the core runner (`run_repair_loop`) were unified into an autonomous self-healing loop:
- **Bounded Autonomous Execution:** Bounded to `max_repair_attempts` (default 3, range 1–10).
- **Repeated Patch Detection:** Tracks unified diff hashes to prevent looping on ineffective or identical LLM proposals.
- **Feedback Propagation:** Captures test stderr and failure logs from sandbox runs and feeds them into subsequent diagnosis attempts.
- **Zero Host Mutation & Isolation Invariant:** Patches are tested inside disposable ephemeral trees using isolated Docker containers (`cicd-sandbox:latest`). If Docker or disk quotas fail, execution halts closed with `INFRASTRUCTURE_FAILURE` and never runs candidate code on host.
- **Truthful Outcomes:** Reports 5 mutually exclusive statuses: `repaired`, `partially repaired`, `unresolved`, `blocked`, and `healthy`.
- **Publication Disabled:** Draft PR opening remains disabled for Phase 4 (`publication.status = "skipped_phase_4"`).

---

## 9. Phase 5 Update: Final Reporting and Verified Draft PR Delivery

**Status:** Completed & Fully Verified  
**Date:** 2026-10-23  

In Phase 5, ACID AI completes the delivery stage by uniting structured, evidence-based final reporting with safe, opt-in GitHub Draft Pull Request delivery:
- **Structured Final Reports (`agent/report.py`):** Generates comprehensive, evidence-based reports from real run records and sandbox outcomes across all 5 truthful states: `healthy`, `repaired`, `partially repaired`, `unresolved`, and `blocked`.
- **Chronological Attempt History & Verification Evidence:** Every attempt logs the targeted failure category, diagnosis root cause, affected files, exact verification commands executed, sandbox container exit codes, and raw test output snippets.
- **Strict Credential & Secret Redaction:** Inbound and outbound logs, diff snippets, and final reports are automatically scrubbed of GitHub tokens, Cloud API keys, AWS credentials, and environment variables using `redact_secrets()`.
- **Truthful Verification Scope Notice:** Every report incorporates an explicit, unambiguous statement distinguishing what ACID AI verified (exit code 0 in isolated sandbox for executed commands) from what it cannot guarantee (edge cases outside test coverage, performance); mandatory human review is explicitly stated.
- **Report Persistence & Retrieval APIs (`dashboard/app.py`):** Reports are assigned unique run IDs, cached in memory, saved to disk (`reports/{run_id}.json` and `.md`), and served via dedicated REST endpoints (`/api/reports/<run_id>`, `/api/reports/<run_id>/markdown`, and `/api/reports`).
- **Opt-In Verified Draft PR Delivery (`agent/publisher.py`):** Publication is strictly opt-in and disabled by default (`ENABLE_REPAIR_PR=false`). Unverified, blocked, or failing candidate repairs are permanently ineligible for publication.
- **Dedicated Repair Branch & Anti-Recursion:** Verified repairs are committed to dedicated branches (`agent/fix-{category}-{run_id}`) from the recorded base commit. Pull requests are marked `draft: true` and labeled with the `[ai-agent-repair]` anti-recursion tag to prevent automated CI loops. Automatic merging is strictly prohibited.
- **Clean Git Tree Composition:** Candidate patches are derived in-memory and committed via the GitHub Git Database API using clean tree objects. Local caches, temporary files, and `.env` credentials are systematically excluded.
- **Truthful Handling of Remotes and API Errors:** Automatically inspects git remotes (`extract_github_repo_from_remote`) to verify owner/repo slug and base branch. Truthfully handles missing credentials, missing remotes, HTTP 401/403 permissions, and 422 branch conflicts without failing closed or claiming fabricated success.
- **Dashboard Integration:** Interactive UI features a verified Final Report card with a dedicated View Report modal dialog, Export Markdown, and Export JSON buttons, an Opt-In Draft PR Delivery settings box, and genuine Draft PR links rendered only upon confirmed creation.
- **Verification & QA:** 11 new automated unit tests in `tests/unit/test_phase5_reporting_and_delivery.py` covering all Part E requirements; **326 passed unit & integration tests (296 unit + 30 integration)**, 3 sample-app tests passed, 0 flake8 errors, 0 git diff errors.

---

## 10. QA Fix 2 Update: Beginner-Friendly Reports, Accurate Diagnosis, and PDF Export

**Status:** Completed & Fully Verified  
**Date:** 2026-10-23  

QA Fix 2 delivers a coherent, beginner-friendly reporting experience and eliminates cross-mode diagnosis pollution:
- **Separation of Demonstration Fixtures vs. Real Repository Runs:** Real repository-first runs inspect the actual files of the chosen repository and never inject unrelated canned sample-app diagnoses or patches. Deterministic mock scenarios remain cleanly isolated in the dedicated Demonstration Scenarios tab.
- **Contract Ambiguity Detection:** When test assertions and implementation logic conflict without specification evidence (e.g. `assert add(2, 2) == 5` vs `add(a, b)` returning 4), ACID AI flags contract ambiguity, assigns low confidence, documents the ambiguity in the root cause, and refrains from guessing fixes.
- **Candidate File Path Rendering:** Corrected `format_file_list` across backend report generation and `formatFileList` in `dashboard/static/app.js` to parse strings, `FilePatch` objects, dictionaries, and arrays cleanly, eliminating all `[object Object]` rendering bugs.
- **Plain-English Run Summary (`agent/models.py`, `agent/report.py`):** Structured `PlainEnglishSummary` model integrated into `FinalReport` covering all 8 core dimensions: Overall Outcome, What Happened, Why It Happened, What ACID AI Attempted, Did the Repair Work, Why the Agent Stopped, What You Should Do Next, and Publication Status across all 5 canonical outcomes (`healthy`, `repaired`, `partially repaired`, `unresolved`, `blocked`).
- **Two-Level Report UI:** Level 1 beginner-friendly plain-English summary placed prominently at the top of the report card and modal; Level 2 technical details (logs, diffs, commands, verification) remain accessible in expandable sections.
- **Professional PDF Export Engine (`agent/pdf_report.py`):** ReportLab generator producing publication-grade PDFs with custom running headers and footers ("Page X of Y" pagination), outcome badges, Plain-English summary callouts, initial checks, repair attempt timelines with diff snippets, bounded log evidence, cumulative verified patches, and truthful verification boundaries.
- **Safe PDF Download Route (`dashboard/app.py`):** Added `GET /api/reports/<run_id>/pdf` returning `Content-Type: application/pdf`, `Content-Disposition: attachment; filename="acid-ai-report-<run_id>.pdf"`, with 404 handling on missing run IDs and secret redaction.
- **Unified Single Source of Truth:** JSON, Markdown, and PDF exports, as well as the dashboard UI, derive from the single underlying `FinalReport` instance.
- **Verification & QA Coverage:** 5 dedicated test suites added (`test_plain_english_summary.py`, `test_pdf_report.py`, `test_contract_ambiguity.py`, `test_file_path_rendering.py`, `test_pdf_export_e2e.py`) totaling 27 tests; **373 passed unit, integration, and sample-app tests (340 unit + 30 integration + 3 sample-app)**, 0 failures, 0 flake8 errors, 0 git diff errors.

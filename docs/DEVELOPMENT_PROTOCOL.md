# DEVELOPMENT_PROTOCOL.md — Engineering Protocol & Operating Standard

This document defines the strict, reusable engineering protocol governing all development phases of the **ACID AI** project. Every developer and AI agent must adhere to these standards.

---

## 1. Repository Inspection & Change Planning

Before authoring code or editing files:
1. **Identify the Git Environment**: Run `git status --short --untracked-files=all`, `git branch`, and inspect the working tree to ensure no uncommitted or dirty files are overwritten.
   - *Note on Git Status*: `git diff` only displays tracked file modifications and omits untracked files. Always check untracked files explicitly before declaring a working tree clean.
2. **Review Relevant Existing Code**: Inspect target files, their dependencies, and any existing unit tests. Do not make assumptions about interfaces based solely on function names.
3. **Formulate an Explicit Change Plan**:
   - Define exact files to create, modify, or delete.
   - Verify that all intended changes fall within the boundaries of the currently authorized phase as tracked in [docs/PHASE_STATUS.md](PHASE_STATUS.md).
   - If an unexpected refactoring or dependency addition is discovered to be necessary, halt and seek authorization.

---

## 2. Scope Control & Behavioral Preservation

1. **Strict Phase Boundaries**: Work exclusively on the current phase. Never implement features from future roadmap phases prematurely.
2. **Preserve Working Logic**: When modifying an existing component, preserve unrelated functionality, comments, docstrings, and established APIs unless the phase explicitly mandates their redesign.
3. **Minimize Blast Radius**: Keep edits tightly focused on the specific acceptance criteria of the authorized phase. Refactor only where directly required to maintain architectural integrity.

---

## 3. Code Quality & Maintainability Standards

1. **Language & Formatting**:
   - Python code must adhere to PEP 8 standards, targeting Python 3.11+.
   - Enforce static typing with standard `typing` annotations for all function signatures, inputs, and return types.
2. **Modularity & Architecture**:
   - Adhere to the Single Responsibility Principle (SRP). Separate CLI entry points, log parsers, AI provider clients, patch executors, and GitHub API publishers into distinct modules.
   - Use dependency injection and interface abstractions (e.g., `AIProvider` base class) so implementations can be tested with mocks and substituted without touching core business logic.
3. **Data Modeling & Validation**:
   - Use structured data models (Pydantic v2 or Python `@dataclass`) for all domain objects (FailureContext, LogBundle, DiagnosticReport, PatchProposal, VerificationResult).
   - Avoid passing raw, unstructured dictionaries across component boundaries.

---

## 4. Testing Requirements & Execution Evidence

1. **Automated Test Coverage**:
   - Every new feature, parser, orchestrator step, or error-handling path must be accompanied by automated unit and integration tests.
   - Tests must reside in dedicated test directories (`tests/unit/`, `tests/integration/`) and be executable via `pytest`.
2. **Hermetic & Isolated Testing**:
   - Unit tests must never make real outbound network calls or invoke live external APIs (Anthropic, Gemini, GitHub).
   - Use `unittest.mock`, `pytest-mock`, or custom fake providers to simulate provider responses, network timeouts, 4xx/5xx HTTP errors, and malformed JSON payloads.
   - Use static fixture files for pipeline logs representing real-world failure modes (dependency failure, lint syntax error, test failure, Docker build error, healthy run).
3. **Verification Evidence & Scope of Claims**:
   - Code cannot be declared complete based on speculative inspection.
   - The test suite must be actively executed in the developer environment (`pytest tests/ -v`).
   - The exact command line and full terminal execution results must be documented in the completion report.
   - **Crucial Distinction**: A passing test suite (exit code 0) proves **ONLY** that the specific assertions executed in that test run passed. It does not prove that a patch is bug-free, complete, or free of subtle regressions. Human review remains mandatory.

---

## 5. Security & Safe Execution Protocol

1. **Untrusted Input Philosophy**:
   - All external data—including git commit messages, branch names, PR bodies, pipeline logs, test outputs, and AI-generated outputs—is untrusted.
   - Enforce strict sanitization and validation before using external strings in formatting, API requests, or file operations.
2. **Avoiding Shell Interpretation Does Not Equal Safe Execution**:
   - Never pass untrusted strings into shell interpreters (`shell=True`, `os.system`).
   - Invoking commands with `shell=False` prevents shell token expansion (e.g., `; rm -rf /`), but invoking `pytest` or `python` on untrusted repository code still executes arbitrary Python code (`test_*.py`, `conftest.py`, setup scripts).
   - Therefore, command allowlisting must be paired with genuine execution isolation.
3. **Isolated Patch Execution vs Temporary Directories**:
   - **A temporary working directory is NOT a security boundary**. Running code in a temporary directory on the host runner leaves host files, host processes, host network, and runner credentials fully accessible to the executed process.
   - **Required Security Properties of the Validation Environment**:
     - *Credential Separation*: The execution environment must have strictly **ZERO** access to privileged credentials (`GITHUB_TOKEN` with write scope, AI API keys).
     - *Filesystem Boundaries*: Must operate within an ephemeral container or chroot mount where the host runner filesystem is inaccessible.
     - *Network Access Controls*: Restrict or disable outbound network traffic during test execution unless specifically required by the test harness.
     - *Process & Permission Limits*: Execute as an unprivileged, non-root user with dropped Linux capabilities (`--cap-drop=ALL`).
     - *Resource & Wall-Clock Limits*: Strictly enforce CPU quotas, memory limits (e.g., 2GB ceiling), and wall-clock execution timeouts (SIGKILL after 180s).
     - *Ephemeral Lifecycle*: The sandbox must be completely destroyed after execution.
4. **Credential Isolation & Redaction**:
   - Credentials must never be transmitted via URL query parameters. Always use secure HTTP headers (`Authorization: Bearer <token>` or `x-goog-api-key: <token>`).
   - All logs generated by the agent must pass through an automated secret-redaction filter before persistence or transmission. Note that regex-based secret redaction is a defense-in-depth risk reduction control, not an absolute guarantee against novel token formats.

---

## 6. Dependency & Configuration Management

1. **Pinned Dependencies**:
   - Production and development dependencies must be explicitly defined with exact or securely constrained versions in `requirements.txt` or `pyproject.toml`.
   - Never install ad-hoc packages without updating dependency manifests.
2. **Schema-Driven Configuration**:
   - Application configuration must follow the schema defined in [docs/CONFIGURATION.md](CONFIGURATION.md).
   - Treat missing, empty, or malformed environment variables gracefully with explicit validation errors instead of uncaught exceptions.
   - Support configurable AI model identifiers (e.g., `ANTHROPIC_MODEL`, `GEMINI_MODEL`) rather than hardcoding model strings in source code.
   - Secrets must be injected exclusively via environment variables or secret vaults—never committed to the repository.

---

## 7. Error Handling, Timeouts & Retry Limits

1. **Bounded Operations**:
   - Network requests to AI providers and GitHub APIs must specify explicit HTTP timeouts (default: 30 seconds for standard APIs, 60 seconds for LLM generation).
   - AI self-healing iterations must be strictly capped (maximum 2 repair attempts per failure).
2. **Graceful Degradation**:
   - When an AI provider fails, times out, or returns invalid JSON, the agent must record a structured failure, log the error cleanly, and exit safely without crashing the overall CI pipeline or corrupting repository state.
3. **Structured Observability**:
   - Log at appropriate severity levels (`DEBUG`, `INFO`, `WARNING`, `ERROR`).
   - Output structured machine-readable logs (JSON) alongside human-readable console progress.

---

## 8. Git Management, PR Delivery & Recursion Safeguards

1. **Non-Destructive Git Workflows**:
   - Automated self-healing must never commit directly to `main` or existing shared branches.
   - All candidate repairs must be placed on an isolated, dedicated branch named with an explicit convention: `agent/fix-<issue_type>-<run_id>`.
2. **Draft Pull Requests Only & Base-Branch Selection**:
   - Automated repairs must be opened exclusively as **Draft Pull Requests** with detailed markdown explanations, failure logs, diff explanations, and local verification test results.
   - Direct automated merging is strictly prohibited.
   - **Branch Targeting Strategy & Trade-offs**:
     - *Branch-Push Failures*: Target the branch that was pushed (e.g., `feature/xyz`), or `main` if the failure occurred on `main`.
     - *Pull-Request Failures*: Opening a parallel PR against `main` can clutter the repository and confuse the contributor. Where permissions permit (internal branches), the agent may push a candidate commit or target the PR's head branch. On external forks where the agent lacks write access to the contributor's repository, the agent must **NOT** fail or attempt unauthorized writes; it must fall back to posting the verified patch as a PR comment with a downloadable diff artifact.
3. **Anti-Recursion Safeguards & GitHub Token Behavior**:
   - *Default GITHUB_TOKEN*: Under standard GitHub Actions behavior, actions performed by the built-in `GITHUB_TOKEN` do **not** trigger new workflow runs (`on: push` or `on: pull_request` events are suppressed).
   - *PAT & GitHub App Tokens*: If a Personal Access Token (PAT) or GitHub App installation token is used to publish branches or PRs, GitHub Actions **DOES** trigger new workflow runs.
   - *Mandatory Defense-in-Depth*: To prevent recursive loops regardless of token type, all repair commits must include metadata headers (`[ai-agent-repair]` in commit message and body) and the agent must explicitly verify that `github.actor != 'github-actions[bot]'`. If triggered by an agent-generated branch or commit, execution must abort immediately.

---

## 9. Documentation Synchronization

1. **Continuous Documentation Updates**:
   - Any architectural adjustment, configuration addition, or interface change must be immediately reflected across [ARCHITECTURE.md](../ARCHITECTURE.md), [docs/CONFIGURATION.md](CONFIGURATION.md), and [PROJECT_REQUIREMENTS.md](../PROJECT_REQUIREMENTS.md).
2. **Truthful Status Tracking**:
   - Keep [docs/PHASE_STATUS.md](PHASE_STATUS.md) up to date. Mark deliverables as completed only after automated verification has been demonstrated.

---

## 10. Mandatory Phase Completion Report Format

At the conclusion of any authorized development phase, the agent or developer MUST produce a formal Phase Completion Report structured with the following 10 sections:

1. **Summary of Changes**: High-level narrative of what was designed or implemented.
2. **Complete List of Created, Modified, and Deleted Files**: Clickable markdown links to every affected file.
3. **Design Decisions & Trade-offs**: Justification for key technical decisions and rejected alternatives.
4. **Tests Added & Exact Commands Executed**: Specific test files created and exact CLI commands run.
5. **Actual Test Results**: Full stdout/stderr evidence demonstrating test suite execution and passing status.
6. **Acceptance Criteria Verification**: Table mapping each phase acceptance criterion to its status (`PASSED`, `FAILED`, `BLOCKED`, `NOT VERIFIED`) with supporting evidence.
7. **Security, Reliability & Performance Implications**: Impact analysis on trust boundaries, resource limits, and error handling.
8. **Known Limitations & Unresolved Issues**: Explicit accounting of edge cases, temporary stubs, or open technical debt.
9. **Remaining Tasks**: Items scheduled for future phases.
10. **Recommended Next Action**: Clear proposal for the next sequential phase, with an explicit instruction to wait for human user approval.

---

## 11. Authorization Stop Condition

**Automated transitions between phases are strictly forbidden.**
Upon completing the authorized phase and publishing the 10-section report, the agent must immediately pause execution and await explicit user confirmation before initiating the next phase.

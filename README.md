# 🤖 ACID AI

### AI-Powered CI/CD Failure Diagnosis & Self-Healing
> **Diagnose failures. Propose fixes. Verify safely.**

An enterprise-grade, autonomous CI/CD failure diagnosis and self-healing agent operating natively within GitHub Actions and local developer workflows. It detects pipeline failures across unit tests, linters, dependency manifests, and container builds, performs evidence-grounded AI root cause analysis, generates targeted unified diff patches, enforces strict deterministic safety policies, verifies repairs inside an isolated sandbox container, and publishes reviewable **Draft Pull Requests**.

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google_Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Anthropic Claude](https://img.shields.io/badge/Anthropic_Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white)
![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Docker Isolation](https://img.shields.io/badge/Docker_Sandbox-Isolated-2496ED?style=for-the-badge&logo=docker&logoColor=white)

---

## 🎯 System Capabilities

- **Authoritative Stage Failure Detection**: Eliminates keyword false positives by parsing authoritative GitHub Actions step outcomes (`=== STEP OUTCOMES ===`) backed by narrow regex signatures.
- **Silent Healthy-Pipeline Bypass**: Exits immediately with code 0 on healthy runs, consuming **0 AI tokens** and posting **0 PR comments**.
- **Multi-Provider AI Diagnosis**: Vendor-neutral `BaseAIProvider` abstraction supporting:
  - **Google Gemini**: Flagship reasoning model `gemini-4-argon` and agent/coding model `gemini-3.8-flash` via secure `x-goog-api-key` header authentication.
  - **Anthropic Claude**: Frontier coding model `claude-sonnet-4-6` via bearer token header authentication.
- **Strict Patch Safety Policy Validator**: Bounded unified diff parsing enforcing:
  - Allowed path boundaries (`sample-app/`, `src/`, `tests/`, manifests).
  - Strict prohibition of CI workflows (`.github/`), Git internals (`.git/`), secrets, and environment files.
  - Size thresholds (maximum 5 files, maximum 150 modified lines).
  - In-memory repository state matching without modifying the local working tree.
- **Combined Sandbox Container Isolation**:
  - Ephemeral Linux container (`python:3.11-slim`) with `--network none`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, non-root execution (`--user 1000:1000`), and strict cgroups (2GB memory, 2.0 CPUs, 100 PIDs).
  - **Fail-Closed Safety Gate**: Never executes candidate code on the host runner. If container isolation or disk quotas are unavailable, returns `INFRASTRUCTURE_FAILURE` and refuses host execution.
- **Bounded 2-Attempt Self-Correction**: If Attempt 1 verification tests fail, feeds execution logs back to the AI for exactly one bounded correction attempt before clean termination.
- **Reviewable Draft Pull Requests**:
  - Fixes are published **exclusively as Draft Pull Requests** requiring human review. Automated merging is permanently prohibited.
  - Gated by mandatory `VERIFIED_SUCCESS`: unverified patches are never published as repair PRs.
  - Anti-recursion protection: checks bot actor and embeds `[ai-agent-repair]` headers to prevent runaway feedback loops.
  - Fork resilience: falls back to posting patch diffs in PR comments with downloadable `agent-patch.diff` artifacts on permission-restricted forks.
- **Automated Secret Redaction & Token Budgeting**: All outbound logs, PR comments, and artifacts are scrubbed of credentials (`sk-ant-...`, `AIzaSy...`, `ghp_...`, passwords). Prompts are capped at 12,000 tokens with defanged XML tags.

---

## 🏗️ End-to-End Architecture

```mermaid
flowchart TD
    subgraph CI["1. GitHub Actions CI Stage"]
        A[Workflow Trigger: push / pull_request] --> B[Execute: Install, Lint, Test, Docker]
        B --> C{Step Outcomes Check}
        C -- "All Steps Succeeded" --> D[Bypass Agent & Exit 0<br/>0 Tokens, No Comments]
        C -- "Stage Failure Detected" --> E[Extract Stage Logs & Outcomes]
    end

    subgraph AI["2. Diagnosis & Patch Generation"]
        E --> F[Normalize Logs & Scrub Secrets]
        F --> G[AI Diagnosis: Gemini 3.8 Flash / Claude]
        G --> H{Valid Schema & Evidence?}
        H -- "Schema Valid" --> I[Generate Unified Diff Patch]
        H -- "Malformed / Outage" --> J[Log Warning & Degrade Gracefully]
    end

    subgraph SEC["3. Safety Policy & Sandbox Isolation"]
        I --> K{Safety Policy Validation<br/>Paths, Size, Prohibited Files}
        K -- "Policy Violation" --> L[Reject Patch & Report Diagnosis Only]
        K -- "Policy Approved" --> M[Spawn Ephemeral Disposable Workspace]
        M --> N[Apply Patch to Disposable Copy]
        N --> O[Execute Verification Suite in Container<br/>--network none, --cap-drop=ALL, 2GB, non-root]
    end

    subgraph PUB["4. Verification & Draft PR Delivery"]
        O --> P{Verification Result<br/>Exit Code == 0?}
        P -- "Yes: VERIFIED_SUCCESS" --> Q[Publish Dedicated Repair Branch]
        Q --> R[Open Reviewable Draft Pull Request<br/>Tagged with [ai-agent-repair]]
        P -- "No: TEST_FAILED" --> S{Attempt Count < 2?}
        S -- "Attempt 1 Failed" --> T[Feed Verification Error to AI]
        T --> I
        S -- "Attempt 2 Failed" --> U[Clean Up Sandbox & Abort PR Creation]
    end
```

---

## 📁 Repository Structure

```
ACID-AI/
├── .github/
│   └── workflows/
│       └── ci.yml                # CI pipeline with truthful failure enforcement
├── agent/
│   ├── __init__.py               # Package metadata and public exports
│   ├── __main__.py               # Python module execution entry point (python -m agent)
│   ├── cli.py                    # Orchestrator and command-line interface
│   ├── classifier.py             # Authoritative step outcome and regex failure classifier
│   ├── collector.py              # Memory-bounded tail-seeking log reader
│   ├── config.py                 # Pydantic configuration loader and validator
│   ├── evidence.py               # Log normalizer, ANSI stripper, and stacktrace extractor
│   ├── formatter.py              # PR comment and diagnostic markdown formatter
│   ├── github.py                 # GitHub API client for PR comments
│   ├── models.py                 # Domain models (Diagnosis, Patch, Verification, Publish)
│   ├── parser.py                 # AI response schema parser
│   ├── patcher.py                # Unified diff patch generator
│   ├── providers.py              # BaseAIProvider, GeminiProvider, AnthropicProvider
│   ├── publisher.py              # Branch creator, Draft PR publisher, fork fallback
│   ├── runner.py                 # VerificationRunner and bounded 2-attempt repair loop
│   ├── sandbox.py                # DockerSandbox container isolation backend
│   ├── security.py               # Secret redactor, prompt sanitizer, token budgeter
│   ├── self_healing_agent.py     # Backward-compatible legacy script entry point
│   └── validator.py              # Patch safety policy validator and diff parser
├── docs/
│   ├── CONFIGURATION.md          # Unified configuration reference
│   ├── DEVELOPMENT_PROTOCOL.md   # Engineering protocol and standards
│   └── PHASE_STATUS.md           # Phase tracker and acceptance criteria
├── sample-app/                   # Reference Flask application for testing
│   ├── app.py                    # Flask web application
│   ├── Dockerfile                # Container build specification
│   ├── requirements.txt          # Application dependencies
│   └── tests/
│       └── test_app.py           # Pytest test suite
├── tests/
│   ├── fixtures/                 # Synthetic CI failure logs (healthy, test, lint, dep, docker)
│   ├── integration/              # End-to-end orchestration and resilience test suite
│   │   ├── test_e2e_orchestration.py
│   │   ├── test_resilience.py
│   │   └── test_sandbox_integration.py
│   └── unit/                     # Hermetic unit tests across all agent modules (18 test files)
├── action.yml                    # Reusable composite GitHub Action definition
├── AGENTS.md                     # Permanent agent governance and inviolable rules
├── ARCHITECTURE.md               # System architecture specification
├── PROJECT_REQUIREMENTS.md       # Product requirements and 10 acceptance scenarios
├── pyproject.toml                # Build packaging and pytest configuration
├── requirements.txt              # Pinned direct runtime dependencies
├── requirements-dev.txt          # Development and testing dependencies
├── requirements.lock             # Reproducible transitive lockfile
├── ROADMAP.md                    # Sequential development roadmap (Phases 00–08)
└── THREAT_MODEL.md               # Application security threat model
```

---

## ⚙️ Configuration Reference

Configuration is managed via environment variables or repository secrets:

| Variable | Required? | Default | Description |
| :--- | :---: | :--- | :--- |
| `AI_PROVIDER` | No | `gemini` | Active provider: `gemini` or `claude`. |
| `GEMINI_API_KEY` | If Gemini | *None* | Google AI Studio API key (sent via `x-goog-api-key` header). |
| `GEMINI_MODEL` | No | `gemini-3.8-flash` | Gemini model (`gemini-3.8-flash`, `gemini-4-argon`, `gemini-3.6-flash`). |
| `ANTHROPIC_API_KEY` | If Claude | *None* | Anthropic API key (`sk-ant-...`). |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-4-6` | Anthropic model identifier. |
| `GITHUB_TOKEN` | In CI | *None* | GitHub Actions token (`pull-requests: write`, `contents: write`). |
| `GENERATE_PATCH` | No | `false` | Enable patch generation engine after diagnosis. |
| `ENABLE_REPAIR_PR` | No | `true` | Publish verified repairs as reviewable Draft PRs. |
| `MAX_REPAIR_ATTEMPTS` | No | `2` | Bounded repair attempts ceiling (1 or 2). |
| `MAX_PROMPT_TOKENS` | No | `12000` | Maximum token budget ceiling per diagnosis session. |
| `LOG_FILE` | No | `combined-logs.txt` | Path to pipeline log file. |

---

## 🧪 Installation & Testing

### 1. Fresh Environment Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/ACID-AI.git
cd ACID-AI

# Create and activate virtual environment (Python 3.11+)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies using reproducible lockfile
pip install -r requirements.lock
```

### 2. Running Test Suites

```bash
# Run full hermetic unit test suite with statement coverage
pytest --cov=agent tests/unit

# Run full integration test suite (resilience, sandbox safety, end-to-end flows)
pytest tests/integration

# Run reference sample application tests
pytest sample-app/tests

# Run PEP 8 static code analysis
flake8 agent tests

# Verify Git working tree cleanliness
git diff --check
```

---

## 🚀 Repeatable Local Demo Procedure

You can test and demonstrate ACID AI locally without live GitHub Actions runners or live LLM charges.

### 🖥️ Interactive Web Dashboard (Hackathon Presentation)

Launch the lightweight presentation dashboard in one command:

```bash
python run_demo.py
# Server binds to http://127.0.0.1:5000
```

Open `http://127.0.0.1:5000` in any browser to interact with:
- **Pipeline Stage Stepper:** Visual 5-stage progress (Log Detection → AI Diagnosis → Patch Validation → Isolated Sandbox → Draft PR Gate).
- **One-Click Scenarios:** Healthy Run (Silent Bypass), Missing Dependency, Flake8 Lint Error, Pytest Assertion Failure, Docker Build Error, and Live Local Pytest Execution.
- **AI Engine Toggle:** Switch seamlessly between **Offline Deterministic Mock** (100% reliable for live stage demos) and **Live Google Gemini API** (`gemini-3.8-flash`).
- **Fail-Closed Safety Visualization:** Truthfully displays `BLOCKED — infrastructure requirement not met` whenever Docker is offline or disk quotas are unsupported, showing judges that candidate code is strictly protected from host execution.
- **Run History & Reset:** Review previous scenario outcomes or reset the session log.

### Demo Status Matrix: Real vs Mocked vs Blocked

| Component / Stage | Local Demo Status | Implementation Mechanism |
| :--- | :---: | :--- |
| **Log Collection & Seeking** | **REAL** | `agent/collector.py` reads local file tail up to 50KB without memory exhaustion. |
| **Outcome & Regex Classification** | **REAL** | `agent/classifier.py` parses step outcomes and matches failure signatures. |
| **AI Diagnosis & Prompt Generation** | **REAL / MOCKED** | Prompts formatted with real sanitization; AI responses can use live API keys or deterministic mocks. |
| **Unified Diff Patch Generation** | **REAL** | `agent/patcher.py` parses model output into structured `FilePatch` objects. |
| **Patch Safety Policy Validation** | **REAL** | `agent/validator.py` evaluates paths, sizes, and verifies in-memory state against local repo. |
| **Ephemeral Copy Creation** | **REAL** | `agent/runner.py` creates temporary workspace excluding `.git` and applies diff in-memory. |
| **Container Sandbox Isolation** | **REAL or BLOCKED** | If Docker is running with enforced quotas, executes in isolated container. If Docker is offline, **fails closed** (`INFRASTRUCTURE_FAILURE`), safely refusing host execution. |
| **Secret Redaction** | **REAL** | `agent/security.py` scrubs credentials from all logs, comments, and diffs. |
| **GitHub Draft PR Publishing** | **MOCKED / REAL** | Uses real Git logic; publishes to remote GitHub when `GITHUB_TOKEN` is supplied, or outputs local artifact. |

### Step-by-Step Demo Scenarios

#### Scenario A: Healthy Pipeline Bypass (Silent Exit)

```bash
# Run agent against healthy log fixture
python -m agent.cli --log-file tests/fixtures/healthy_run.txt
# Output:
# 🚀 ACID AI starting...
# 📄 Logs loaded (303 characters)
# ✅ No failures detected — pipeline healthy. Silent bypass active (0 tokens, 0 comments).
# Exit Code: 0
```

#### Scenario B: Test Assertion Failure Diagnosis & Local Patch Proposal

```bash
# Set dummy credentials for offline mock run, or supply real GEMINI_API_KEY
export AI_PROVIDER="gemini"
export GEMINI_API_KEY="your-gemini-api-key-here"
export GENERATE_PATCH="true"
export ENABLE_REPAIR_PR="false"  # Save patch locally without calling GitHub API

python -m agent.cli --log-file tests/fixtures/pytest_assertion_failure.txt
```

Expected behavior:
1. Agent parses `=== STEP OUTCOMES ===` and detects `test: failure`.
2. Diagnoses root cause: `AssertionError: assert 'Service Unavailable' == 'Welcome to the Sample App!'`.
3. Proposes unified diff targeting `sample-app/app.py`.
4. Saves redacted diagnostic report to `agent-analysis.json`.
5. Fails closed if Docker is offline, protecting the host runner from untrusted code execution.

---

## 🛡️ Security Model & Inviolable Safety Principles

1. **Zero Execution on Host Runner**: Untrusted candidate patches and tests are **NEVER** executed directly on the host runner. If container isolation is unavailable, the agent fails closed (`INFRASTRUCTURE_FAILURE`).
2. **Draft Pull Requests Exclusively**: Auto-merging is permanently prohibited. All automated repairs require human engineering review and approval before merging.
3. **Bounded Self-Healing Ceiling**: Maximum 2 repair attempts per failure event to prevent runaway billing or infinite loops.
4. **Passing Tests != Bug-Free Code**: A passing test suite proves **only** that executed assertions passed. It does not guarantee that the code is free of edge-case bugs.
5. **No Secrets in Sandbox**: The execution container has strictly zero access to runner credentials, tokens, or network interfaces.

---

## 📄 License

MIT — Copyright (c) Ayushi Vasishtha

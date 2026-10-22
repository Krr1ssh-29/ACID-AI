# CONFIGURATION.md — Configuration Schema & Management Guide

## Project: ACID AI — AI-Powered CI/CD Failure Diagnosis & Self-Healing

---

## 1. Overview & Configuration Architecture

The configuration architecture is designed to support both environment variable injection (for native GitHub Actions execution) and an optional repository configuration file (`.ai-agent.yaml`) for project-specific customization.

> [!IMPORTANT]
> **Secret Management Rule**: API keys, access tokens, and private credentials must **NEVER** be committed to source control. They must be supplied via GitHub Actions Repository Secrets, cloud secret managers (e.g., HashiCorp Vault, AWS Secrets Manager), or local environment variables.

---

## 2. Configuration Parameters Reference

The following table comprehensively details all current and proposed configuration parameters across all architectural categories.

| Parameter Name | Category | Current Status | Required? | Default Value | Allowed Values | Secret? | Purpose & Validation Rules |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `AI_PROVIDER` | AI Provider | Existing | Optional | Pending Owner Selection | `"claude"`, `"gemini"` | No | Selects the active AI provider. Case-insensitive string; must not be empty string. Primary provider selection is currently pending repository owner approval. |
| `ANTHROPIC_API_KEY` | AI Provider | Existing | Required if `AI_PROVIDER == "claude"` | *None* | Valid Anthropic API key string | **Yes** | Authentication credential for Anthropic Claude. Must start with `sk-ant-`. Transmitted via HTTP headers. |
| `ANTHROPIC_MODEL` | AI Provider | Proposed (Phase 03) | Optional | Pending Owner Selection | Valid Anthropic model identifiers | No | Model identifier for Anthropic Claude API calls. Default model selection remains pending owner approval. Supports verified model identifiers such as `claude-sonnet-4-6` (official Sonnet release, Feb 2026; verified Oct 2026) and `claude-3-5-sonnet-20241022`. |
| `GEMINI_API_KEY` | AI Provider | Existing | Required if `AI_PROVIDER == "gemini"` | *None* | Valid Google AI Studio API key | **Yes** | Authentication credential for Gemini. Transmitted via `x-goog-api-key` header (never in URL query string). |
| `GEMINI_MODEL` | AI Provider | Proposed (Phase 03) | Optional | Pending Owner Selection | `"gemini-4-argon"`, `"gemini-3.8-flash"`, `"gemini-3.6-flash"`, `"gemini-3.5-flash-lite"`, `"gemini-3.5-flash"`, `"gemini-2.5-flash"` | No | Model identifier for Gemini API calls. Default model selection remains pending owner approval. Accurately distinguishes current, legacy, and deprecated models per official Google documentation (Oct 2026): `gemini-4-argon` is Google's flagship reasoning model built for complex software engineering and deep reasoning (1M unified context); `gemini-3.8-flash` is Google's flagship Flash model engineered for long-horizon software engineering and agent workloads; `gemini-3.6-flash` is the previous-generation balanced Flash model; `gemini-3.5-flash` is deprecated and automatically routed by Google's API to `gemini-3.6-flash`; `gemini-3.5-flash-lite` is a separate active model for cost-efficient/lightweight tasks; `gemini-2.5-flash` is supported for legacy accounts but restricted for new projects. |
| `AI_TIMEOUT_SECONDS` | AI Provider | Proposed (Phase 03) | Optional | `60` | Integer: `10` to `180` | No | Strict HTTP request timeout for LLM generation. |
| `AI_MAX_TOKENS` | AI Provider | Proposed (Phase 03) | Optional | `4096` | Integer: `512` to `8192` | No | Maximum token ceiling for model generation responses. |
| `GITHUB_TOKEN` | GitHub Integration | Existing | Required | *None* | Valid GitHub Actions token | **Yes** | GitHub authentication token. Requires `contents: write`, `pull-requests: write`. |
| `REPO_NAME` | GitHub Integration | Existing | Required | *None* | String in `owner/repo` format | No | Target GitHub repository identifier. Derived from `github.repository`. |
| `PR_NUMBER` | GitHub Integration | Existing | Optional | *None* | Positive integer or empty | No | Pull request number. If empty or `"None"`, direct push triage mode is activated. |
| `COMMIT_SHA` | GitHub Integration | Existing | Optional | `"unknown"` | 40-character hex string | No | Git commit hash triggering the CI workflow. |
| `RUN_ID` | GitHub Integration | Existing | Optional | `"unknown"` | String / Integer | No | GitHub Actions workflow run identifier (`github.run_id`). |
| `DRAFT_PR_ENABLED` | GitHub Integration | Proposed (Phase 06) | Optional | `true` | `true`, `false` | No | If `true`, verified repairs are published as Draft PRs. If `false`, outputs patch to artifacts. |
| `BRANCH_PREFIX` | GitHub Integration | Proposed (Phase 06) | Optional | `"agent/fix-"` | Valid Git ref name prefix | No | Prefix for auto-generated fix branches. |
| `LOG_TRUNCATION_LIMIT` | Diagnosis | Proposed (Phase 02) | Optional | `8000` | Integer: `1000` to `24000` | No | Maximum character limit per stage log sent to the AI context. Uses smart error-windowing. |
| `SOURCE_SNIPPET_RADIUS`| Diagnosis | Proposed (Phase 02) | Optional | `50` | Integer: `10` to `100` | No | Number of source code lines around the implicated failure line to include in prompt context. |
| `SECRET_REDACTION_ENABLED` | Diagnosis | Proposed (Phase 07) | Optional | `true` | `true`, `false` | No | If `true`, runs regex pattern filters to scrub credentials before LLM transmission or PR posting. |
| `MAX_REPAIR_ATTEMPTS` | Repair | Proposed (Phase 05) | Optional | `2` | Integer: `1` to `3` | No | Hard ceiling on autonomous repair/verification iterations per failure. |
| `PATCH_MAX_FILES` | Repair | Proposed (Phase 04) | Optional | `5` | Integer: `1` to `10` | No | Maximum number of files permitted to be altered in a single candidate patch. |
| `PATCH_MAX_LINES` | Repair | Proposed (Phase 04) | Optional | `150` | Integer: `10` to `500` | No | Maximum total lines (added + deleted) permitted in a single candidate patch. |
| `ALLOWED_PATCH_PATHS` | Repair | Proposed (Phase 04) | Optional | `["sample-app/**", "src/**", "tests/**"]` | Array of glob paths | No | Glob list of paths permitted for autonomous modification. Rejects `.github/`, `.git/`, `.env`. |
| `SANDBOX_ISOLATION_STRATEGY`| Execution | Proposed (Phase 05) | Required for Phase 05 | Pending Owner Approval | `"container_docker"`, `"uncredentialed_job"` | No | Concrete execution isolation strategy. Phase 05 remains blocked until the owner selects and approves a concrete strategy. Host temp dirs, `shell=False`, or individual flags alone are rejected. |
| `VERIFICATION_COMMANDS`| Execution | Proposed (Phase 05) | Optional | Auto-detected | Array of command strings | No | Strict list of commands executed in the sandbox to verify repairs (e.g., `["pytest", "flake8"]`). |
| `VERIFICATION_TIMEOUT` | Execution | Proposed (Phase 05) | Optional | `180` | Integer: `30` to `600` | No | Maximum execution time in seconds for the entire verification suite. |
| `LOG_LEVEL` | Operational Controls | Proposed (Phase 03) | Optional | `"INFO"` | `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"` | No | Granularity of runtime console logging. |
| `TOKEN_BUDGET_PER_RUN` | Operational Controls | Proposed (Phase 07) | Optional | `12000` | Integer: `4000` to `30000` | No | Maximum cumulative prompt + completion token spend per failure triage session. |

---

## 3. Current vs Proposed Configuration Structure

### 3.1 Current Implementation (Environment Variables Only)
In the existing codebase (`agent/self_healing_agent.py`), configuration is loaded directly from raw environment variables without schema validation:

```python
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY")
AI_PROVIDER       = os.environ.get("AI_PROVIDER", "claude").lower()
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN")
REPO_NAME         = os.environ.get("REPO_NAME")
PR_NUMBER         = os.environ.get("PR_NUMBER")
COMMIT_SHA        = os.environ.get("COMMIT_SHA", "unknown")
RUN_ID            = os.environ.get("RUN_ID", "unknown")
LOG_FILE          = "combined-logs.txt"
```

*Identified Flaw*: If `AI_PROVIDER` is set to an empty string (`""`) in GitHub Actions secrets, `os.environ.get("AI_PROVIDER", "claude")` evaluates to `""`, causing the agent to crash with an unhandled `ValueError`.

### 3.2 Target v1 Implementation (Schema-Validated Config)
In v1, configuration will be managed via a validated Pydantic model (`AgentConfig`) capable of loading defaults, parsing environment variables, and reading an optional `.ai-agent.yaml` repository configuration file.

---

## 4. Safe Configuration Examples

### 4.1 GitHub Actions Workflow Configuration (`.github/workflows/ci.yml`)
Below is the recommended safe configuration for invoking the agent within GitHub Actions without leaking secrets or failing on empty variables:

```yaml
      - name: Run ACID AI
        if: steps.install.outcome == 'failure' || steps.lint.outcome == 'failure' || steps.test.outcome == 'failure' || steps.docker.outcome == 'failure'
        env:
          # AI Provider & Model Configuration (Choices pending owner approval)
          AI_PROVIDER: ${{ secrets.AI_PROVIDER }} # Set by owner: 'claude' or 'gemini'
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          ANTHROPIC_MODEL: ${{ secrets.ANTHROPIC_MODEL }} # e.g., 'claude-sonnet-4-6' (pending owner approval)
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_MODEL: ${{ secrets.GEMINI_MODEL }} # e.g., 'gemini-3.8-flash' or 'gemini-4-argon' (pending owner approval)

          # GitHub Context & Scoped Authentication
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          REPO_NAME: ${{ github.repository }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          COMMIT_SHA: ${{ github.sha }}
          RUN_ID: ${{ github.run_id }}

          # Operational Limits
          LOG_LEVEL: 'INFO'
          MAX_REPAIR_ATTEMPTS: '2'
        run: |
          python -m agent.cli --stage-outcomes stage-outcomes.json
```

### 4.2 Declarative Repository Configuration File (`.ai-agent.yaml`)
Repositories can customize repair policies and verification commands by placing an `.ai-agent.yaml` at their root:

```yaml
# .ai-agent.yaml — Repository Specific ACID AI Repair Policy
version: "1.0"

repair:
  max_attempts: 2
  allowed_paths:
    - "sample-app/**"
    - "src/**"
    - "tests/**"
  prohibited_paths:
    - ".github/**"
    - ".git/**"
    - "**/Dockerfile" # Lock Dockerfile if container changes require human-only edits
  max_files_modified: 3
  max_lines_modified: 100

execution:
  sandbox_isolation_strategy: "container_docker" # Pending owner approval before Phase 05
  timeout_seconds: 180
  commands:
    - "flake8 sample-app/ --max-line-length=120"
    - "pytest sample-app/tests/ -v"

delivery:
  mode: "draft_pr" # Options: "draft_pr", "comment_only"
  branch_prefix: "agent/fix-"
  add_labels:
    - "ai-repair"
    - "automated-fix"
```

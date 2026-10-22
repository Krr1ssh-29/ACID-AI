"""Data models and schemas for the AI CI/CD Failure Triage Agent."""
from enum import Enum
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class StepOutcome(str, Enum):
    """Execution conclusion for a single CI pipeline step."""
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class PipelineStatus(str, Enum):
    """Overall evaluation status for a CI/CD pipeline run."""
    HEALTHY = "healthy"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class StepEvidence(BaseModel):
    """Evidence extracted for a single CI pipeline step."""
    step_id: str = Field(..., description="Identifier of the pipeline step")
    outcome: StepOutcome = Field(default=StepOutcome.UNKNOWN, description="Conclusion of step")
    log_snippet: str = Field(default="", description="Relevant log text for this step")
    failure_category: Optional[str] = Field(None, description="Inferred category (install/lint/test/docker)")


class PipelineEvidence(BaseModel):
    """Validated structured evidence across all CI steps."""
    status: PipelineStatus = Field(..., description="Overall evaluated pipeline status")
    step_outcomes: Dict[str, StepOutcome] = Field(default_factory=dict, description="Step outcomes map")
    detected_failures: List[str] = Field(default_factory=list, description="Categories of detected failures")
    logs_by_step: Dict[str, str] = Field(default_factory=dict, description="Captured log output by step")
    combined_log: str = Field(default="", description="Combined diagnostic log text")
    error_message: Optional[str] = Field(None, description="Error message if status is ERROR")


class FixSuggestion(BaseModel):
    """Represents a specific proposed fix for an identified failure."""
    type: Literal["install", "lint", "test", "docker"] = Field(
        ..., description="The failure category this fix targets"
    )
    title: str = Field(..., description="Short descriptive title of the fix")
    description: str = Field(..., description="Actionable explanation of the fix")
    code: Optional[str] = Field(None, description="Exact code or command to apply the fix")

    def __getitem__(self, item: str):
        """Allow subscript access for backwards-compatibility with legacy dictionary callers."""
        return getattr(self, item)

    def get(self, item: str, default=None):
        """Allow get access for backwards-compatibility with legacy dictionary callers."""
        return getattr(self, item, default)


class FailureContext(BaseModel):
    """Context extracted from logs by the failure classification stage."""
    detected: List[str] = Field(
        default_factory=list, description="List of detected failure type names"
    )
    raw: Dict[str, bool] = Field(
        default_factory=dict, description="Raw boolean detection flags for each stage"
    )
    status: PipelineStatus = Field(
        default=PipelineStatus.INCONCLUSIVE, description="Overall evaluated pipeline status"
    )
    step_outcomes: Dict[str, StepOutcome] = Field(
        default_factory=dict, description="Parsed step outcomes by stage name"
    )
    details: Optional[str] = Field(
        None, description="Diagnostic details or explanation of inconclusive state"
    )

    def __getitem__(self, item: str):
        """Allow subscript access for backwards-compatibility with legacy dictionary callers."""
        return getattr(self, item)

    def get(self, item: str, default=None):
        """Allow get access for backwards-compatibility with legacy dictionary callers."""
        return getattr(self, item, default)


class AnalysisResult(BaseModel):
    """Structured diagnostic analysis returned by AI diagnosis or fallback."""
    severity: Literal["critical", "high", "medium", "low"] = Field(
        default="high", description="Severity of the detected failure"
    )
    failure_types: List[str] = Field(
        default_factory=list, description="Categories of failures implicated"
    )
    root_cause: str = Field(
        ..., description="Grounded explanation of what caused the failure"
    )
    fixes: List[FixSuggestion] = Field(
        default_factory=list, description="Ordered list of recommended fixes"
    )
    prevention: str = Field(
        default="No prevention advice available.",
        description="Preventative guidance to avoid regression",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        default="medium", description="Confidence level of the diagnosis"
    )
    log_evidence: Optional[str] = Field(
        default=None, description="Supporting log lines or snippet cited as evidence"
    )

    @field_validator("failure_types", mode="before")
    @classmethod
    def normalize_failure_types(cls, v):
        if isinstance(v, str):
            return [part.strip() for part in v.split(",") if part.strip()]
        return v

    def __getitem__(self, item: str):
        """Allow subscript access for backwards-compatibility with legacy dictionary callers."""
        return getattr(self, item)

    def get(self, item: str, default=None):
        """Allow get access for backwards-compatibility with legacy dictionary callers."""
        return getattr(self, item, default)


class AgentConfig(BaseModel):
    """Configuration parameters for the agent runtime."""
    ai_provider: Literal["claude", "gemini"] = Field(
        default="claude", description="Active AI provider backend"
    )
    anthropic_api_key: Optional[str] = Field(
        None, description="API key for Anthropic Claude"
    )
    gemini_api_key: Optional[str] = Field(
        None, description="API key for Google Gemini"
    )
    anthropic_model: Optional[str] = Field(
        "claude-sonnet-4-6", description="Model identifier for Anthropic Claude"
    )
    gemini_model: Optional[str] = Field(
        "gemini-3.8-flash", description="Model identifier for Google Gemini"
    )
    github_token: Optional[str] = Field(
        None, description="GitHub authentication token for commenting"
    )
    repo_name: Optional[str] = Field(
        None, description="GitHub repository in owner/repo format"
    )
    pr_number: Optional[str] = Field(
        None, description="Pull request number string if running on PR"
    )
    commit_sha: str = Field(
        default="unknown", description="Git commit SHA being triaged"
    )
    run_id: str = Field(
        default="unknown", description="GitHub Actions workflow run ID"
    )
    log_file: str = Field(
        default="combined-logs.txt", description="Path to combined failure log file"
    )
    ai_timeout_seconds: int = Field(
        default=60, ge=5, le=300, description="Timeout for external AI requests"
    )
    max_retries: int = Field(
        default=2, ge=0, le=5, description="Maximum retries for recoverable AI errors"
    )
    retry_backoff_factor: float = Field(
        default=0.5, ge=0.0, description="Base backoff multiplier for retries"
    )
    max_patch_files: int = Field(
        default=5, ge=1, le=20, description="Maximum files allowed in a single patch"
    )
    max_patch_lines: int = Field(
        default=150, ge=1, le=1000, description="Maximum total modified lines allowed in a patch"
    )
    generate_patch: bool = Field(
        default=False, description="Whether to trigger patch generation after diagnosis"
    )
    verification_commands: List[str] = Field(
        default_factory=lambda: ["pytest sample-app/tests/", "flake8 sample-app/"],
        description="Allowlisted commands executed in isolated sandbox",
    )
    verification_timeout_seconds: int = Field(
        default=180, ge=10, le=600, description="Wall-clock execution timeout in sandbox (seconds)"
    )
    sandbox_memory_limit: str = Field(
        default="2g", description="Memory ceiling for sandbox container (e.g. 2g)"
    )
    sandbox_cpu_limit: str = Field(
        default="2.0", description="CPU quota ceiling for sandbox container"
    )
    sandbox_pids_limit: int = Field(
        default=100, ge=10, le=1000, description="PID count ceiling in sandbox"
    )
    sandbox_image: str = Field(
        default="python:3.11-slim", description="Disposable container image"
    )
    max_repair_attempts: int = Field(
        default=2, ge=1, le=2, description="Maximum bounded repair self-correction attempts"
    )
    base_branch: str = Field(
        default="main", description="Target base branch for repair pull requests"
    )
    github_actor: Optional[str] = Field(
        default=None, description="GitHub actor triggering workflow (used for anti-recursion)"
    )
    enable_repair_pr: bool = Field(
        default=True, description="Whether to attempt Draft PR creation for verified repairs"
    )
    max_prompt_tokens: int = Field(
        default=12000, ge=1000, le=100000, description="Maximum total prompt tokens allowed per run"
    )

    @field_validator("ai_provider", mode="before")
    @classmethod
    def normalize_provider(cls, v):
        if not v or not isinstance(v, str) or not v.strip():
            return "claude"
        return v.strip().lower()


class VerificationStatus(str, Enum):
    """Evaluation status resulting from isolated patch verification."""
    VERIFIED = "verified"
    VERIFIED_SUCCESS = "verified"
    TEST_FAILED = "test_failed"
    TIMEOUT = "timeout"
    PATCH_REJECTED = "patch_rejected"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


class VerificationResult(BaseModel):
    """Outcome report from running candidate code inside the isolated sandbox."""
    status: VerificationStatus = Field(
        default=VerificationStatus.INFRASTRUCTURE_FAILURE,
        description="Conclusion of the isolated verification run",
    )
    is_verified: bool = Field(
        default=False,
        description="True ONLY if all verification commands exited with code 0 inside sandbox",
    )
    exit_code: int = Field(
        default=1,
        description="Process exit code of the final executed verification command",
    )
    executed_commands: List[str] = Field(
        default_factory=list,
        description="Commands executed inside the isolated sandbox",
    )
    output: str = Field(
        default="",
        description="Captured, bounded stdout/stderr from verification execution",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Explanation if execution failed, timed out, or encountered errors",
    )
    attempt: int = Field(
        default=1, ge=1, le=2,
        description="Repair attempt number (bounded 2-attempt loop)",
    )
    truthfulness_statement: str = Field(
        default=(
            "Truthful verification notice: Passing verification proves ONLY that the executed "
            "test suite returned exit code 0 inside the isolated sandbox. It does not prove that "
            "the patch is bug-free or free of edge-case regressions."
        ),
        description="Explicit truthfulness statement per Threat Model T-13 and ARCHITECTURE.md.",
    )

    def __getitem__(self, item: str):
        """Allow subscript access for backwards-compatibility."""
        return getattr(self, item)

    def get(self, item: str, default=None):
        """Allow get access for backwards-compatibility."""
        return getattr(self, item, default)


class PatchStatus(str, Enum):
    """Lifecycle status of a generated code patch proposal."""
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"
    FAILED = "failed"


class FilePatch(BaseModel):
    """Represents candidate modifications targeting a single repository file."""
    path: str = Field(..., description="Repository-relative target file path")
    original_path: Optional[str] = Field(None, description="Original source file path from diff header")
    target_path: Optional[str] = Field(None, description="Target destination file path from diff header")
    additions: int = Field(default=0, ge=0, description="Number of inserted lines (+)")
    deletions: int = Field(default=0, ge=0, description="Number of deleted lines (-)")
    hunks_count: int = Field(default=0, ge=0, description="Number of diff hunks")
    diff_content: str = Field(default="", description="Unified diff text for this file")
    status: Literal["modified", "added", "deleted"] = Field(
        default="modified", description="Operation status for this file"
    )

    def __getitem__(self, item: str):
        """Allow subscript access for backwards-compatibility."""
        return getattr(self, item)

    def get(self, item: str, default=None):
        """Allow get access for backwards-compatibility."""
        return getattr(self, item, default)


class PatchValidationError(BaseModel):
    """Represents a specific safety policy violation or syntax error in a patch."""
    code: str = Field(..., description="Machine-readable policy error code")
    message: str = Field(..., description="Human-readable explanation of the validation failure")
    file_path: Optional[str] = Field(None, description="Target file path implicated in the violation")

    def __getitem__(self, item: str):
        """Allow subscript access for backwards-compatibility."""
        return getattr(self, item)

    def get(self, item: str, default=None):
        """Allow get access for backwards-compatibility."""
        return getattr(self, item, default)


class PatchValidationResult(BaseModel):
    """Programmatic safety evaluation outcome for a candidate patch."""
    is_valid: bool = Field(default=True, description="Whether the patch passed all safety checks")
    errors: List[PatchValidationError] = Field(
        default_factory=list, description="List of policy violations or errors"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Advisory warnings (e.g. dependency manifest modified)"
    )

    def __getitem__(self, item: str):
        """Allow subscript access for backwards-compatibility."""
        return getattr(self, item)

    def get(self, item: str, default=None):
        """Allow get access for backwards-compatibility."""
        return getattr(self, item, default)


class PatchProposal(BaseModel):
    """Structured code patch proposed to remediate a diagnosed CI/CD failure."""
    status: PatchStatus = Field(
        default=PatchStatus.PENDING, description="Current lifecycle state of the patch"
    )
    explanation: str = Field(
        default="", description="Concise explanation of the intended correction matching root cause"
    )
    diff: str = Field(
        default="", description="Raw unified diff formatted patch"
    )
    files: List[FilePatch] = Field(
        default_factory=list, description="Parsed individual file modifications"
    )
    validation: Optional[PatchValidationResult] = Field(
        default=None, description="Safety policy validation outcome"
    )
    requires_human_review: bool = Field(
        default=True, description="Human review required before merging"
    )
    is_verified: bool = Field(
        default=False, description="Verification status (strictly False until Phase 05)"
    )
    verification_claim_disclaimer: str = Field(
        default=(
            "UNVERIFIED: This patch proposal has not yet undergone isolated verification (Phase 05). "
            "Passing tests or bug-free fixes are not claimed or guaranteed."
        ),
        description="Explicit truthfulness disclaimer per Threat Model T-13 and NFR guidelines."
    )

    def __getitem__(self, item: str):
        """Allow subscript access for backwards-compatibility."""
        return getattr(self, item)

    def get(self, item: str, default=None):
        """Allow get access for backwards-compatibility."""
        return getattr(self, item, default)


class PublishStatus(str, Enum):
    """Status outcome of a repair publishing attempt."""
    PUBLISHED = "published"
    SKIPPED_UNVERIFIED = "skipped_unverified"
    SKIPPED_ALREADY_EXISTS = "skipped_already_exists"
    SKIPPED_RECURSION = "skipped_recursion"
    FORK_LIMITATION = "fork_limitation"
    PERMISSION_ERROR = "permission_error"
    API_ERROR = "api_error"


class PublishResult(BaseModel):
    """Structured result from attempting to publish a repair branch / draft PR."""
    status: PublishStatus = Field(..., description="Outcome status of the publish attempt")
    branch_name: Optional[str] = Field(None, description="Created or target repair branch name")
    pr_number: Optional[int] = Field(None, description="Created or existing pull request number")
    pr_url: Optional[str] = Field(None, description="HTML or API URL of the created pull request")
    commit_sha: Optional[str] = Field(None, description="SHA of the created repair commit")
    is_draft: bool = Field(default=True, description="Strictly True; all repairs are Draft PRs")
    message: str = Field(default="", description="Descriptive status or diagnostic message")
    truthfulness_statement: str = Field(
        default=(
            "Truthful verification notice: Passing verification proves ONLY that the executed "
            "test suite returned exit code 0 inside the isolated sandbox. It does not prove that "
            "the patch is bug-free or free of edge-case regressions. Human review is required."
        ),
        description="Explicit truthfulness statement per Threat Model T-13 and ARCHITECTURE.md.",
    )

    def __getitem__(self, item: str):
        """Allow subscript access for backwards-compatibility."""
        return getattr(self, item)

    def get(self, item: str, default=None):
        """Allow get access for backwards-compatibility."""
        return getattr(self, item, default)


class TokenBudgetExceededError(RuntimeError):
    """Raised when an operation would exceed the prompt token budget for a run."""
    pass

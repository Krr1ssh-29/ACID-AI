"""ACID AI — AI-Powered CI/CD Failure Diagnosis & Self-Healing package.

This package provides automated failure classification, AI-assisted diagnosis,
and report formatting for CI/CD pipeline runs.
"""

__version__ = "0.1.0"

from agent.models import (
    AnalysisResult,
    FixSuggestion,
    FailureContext,
    AgentConfig,
    StepOutcome,
    PipelineStatus,
    StepEvidence,
    PipelineEvidence,
    PatchStatus,
    FilePatch,
    PatchValidationError,
    PatchValidationResult,
    PatchProposal,
    VerificationStatus,
    VerificationResult,
)
from agent.config import load_config, validate_credentials
from agent.collector import read_logs, read_logs_bounded
from agent.classifier import classify_failures
from agent.evidence import strip_ansi, parse_step_outcomes, split_stage_logs, extract_stack_trace_snippet
from agent.parser import parse_ai_response
from agent.formatter import format_pr_comment
from agent.github import post_pr_comment
from agent.providers import (
    analyse_with_ai,
    analyse_with_claude,
    analyse_with_gemini,
    BaseAIProvider,
    AnthropicProvider,
    GeminiProvider,
    get_provider,
)
from agent.validator import validate_patch, parse_unified_diff
from agent.patcher import PatchGenerator, generate_patch
from agent.sandbox import (
    SandboxIsolationBackend,
    DockerSandbox,
    sanitize_sandbox_env,
)
from agent.runner import (
    VerificationRunner,
    run_repair_loop,
    is_command_allowlisted,
    copy_disposable_repo,
    apply_patch_to_disposable_tree,
)


def main(argv=None):
    """Execute the failure triage CLI pipeline."""
    from agent.cli import main as _main
    return _main(argv)


__all__ = [
    "__version__",
    "AnalysisResult",
    "FixSuggestion",
    "FailureContext",
    "AgentConfig",
    "StepOutcome",
    "PipelineStatus",
    "StepEvidence",
    "PipelineEvidence",
    "PatchStatus",
    "FilePatch",
    "PatchValidationError",
    "PatchValidationResult",
    "PatchProposal",
    "VerificationStatus",
    "VerificationResult",
    "load_config",
    "validate_credentials",
    "read_logs",
    "read_logs_bounded",
    "strip_ansi",
    "parse_step_outcomes",
    "split_stage_logs",
    "extract_stack_trace_snippet",
    "classify_failures",
    "parse_ai_response",
    "format_pr_comment",
    "post_pr_comment",
    "analyse_with_ai",
    "analyse_with_claude",
    "analyse_with_gemini",
    "BaseAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "get_provider",
    "validate_patch",
    "parse_unified_diff",
    "PatchGenerator",
    "generate_patch",
    "SandboxIsolationBackend",
    "DockerSandbox",
    "sanitize_sandbox_env",
    "VerificationRunner",
    "run_repair_loop",
    "is_command_allowlisted",
    "copy_disposable_repo",
    "apply_patch_to_disposable_tree",
    "main",
]

"""Configuration loading and validation for the triage agent."""
import os
from typing import Optional, Mapping
from agent.models import AgentConfig


def load_config(env: Optional[Mapping[str, str]] = None) -> AgentConfig:
    """Load configuration safely from environment variables or a provided mapping.

    Handles empty strings, case-insensitivity, and defaults without throwing
    unhandled exceptions or performing any network operations.
    """
    if env is None:
        env = os.environ

    raw_provider = env.get("AI_PROVIDER")
    # Gracefully handle empty string AI_PROVIDER=""
    ai_provider = raw_provider.strip().lower() if raw_provider and raw_provider.strip() else "claude"

    raw_pr = env.get("PR_NUMBER")
    pr_number = None if not raw_pr or raw_pr.strip() in ("", "None", "null") else raw_pr.strip()

    raw_timeout = env.get("AI_TIMEOUT_SECONDS")
    try:
        timeout = int(raw_timeout) if raw_timeout else 60
    except ValueError:
        timeout = 60

    raw_retries = env.get("AI_MAX_RETRIES")
    try:
        max_retries = int(raw_retries) if raw_retries else 2
    except ValueError:
        max_retries = 2

    raw_backoff = env.get("AI_RETRY_BACKOFF")
    try:
        backoff = float(raw_backoff) if raw_backoff else 0.5
    except ValueError:
        backoff = 0.5

    raw_max_patch_files = env.get("MAX_PATCH_FILES")
    try:
        max_patch_files = int(raw_max_patch_files) if raw_max_patch_files else 5
    except ValueError:
        max_patch_files = 5

    raw_max_patch_lines = env.get("MAX_PATCH_LINES")
    try:
        max_patch_lines = int(raw_max_patch_lines) if raw_max_patch_lines else 150
    except ValueError:
        max_patch_lines = 150

    raw_gen_patch = env.get("GENERATE_PATCH", "")
    generate_patch = raw_gen_patch.strip().lower() in ("true", "1", "yes")

    raw_vtimeout = env.get("VERIFICATION_TIMEOUT_SECONDS")
    try:
        vtimeout = int(raw_vtimeout) if raw_vtimeout else 180
    except ValueError:
        vtimeout = 180

    sandbox_image = env.get("SANDBOX_IMAGE", "cicd-sandbox:latest") or "cicd-sandbox:latest"
    raw_ro = env.get("SANDBOX_READ_ONLY_ROOTFS", "true")
    sandbox_ro = raw_ro.strip().lower() in ("true", "1", "yes")
    sandbox_storage = env.get("SANDBOX_STORAGE_SIZE", "256m") or "256m"
    sandbox_mode = env.get("SANDBOX_STORAGE_MODE", "read_only_tmpfs") or "read_only_tmpfs"

    raw_attempts = env.get("MAX_REPAIR_ATTEMPTS")
    try:
        max_attempts = int(raw_attempts) if raw_attempts else 3
    except ValueError:
        max_attempts = 3

    base_branch = env.get("BASE_BRANCH") or env.get("TARGET_BRANCH") or "main"
    github_actor = env.get("GITHUB_ACTOR")
    raw_enable_repair_pr = env.get("ENABLE_REPAIR_PR", "false")
    enable_repair_pr = raw_enable_repair_pr.strip().lower() in ("true", "1", "yes")

    raw_max_tokens = env.get("MAX_PROMPT_TOKENS")
    try:
        max_prompt_tokens = int(raw_max_tokens) if raw_max_tokens else 12000
    except ValueError:
        max_prompt_tokens = 12000

    raw_publisher_token = env.get("REPAIR_PUBLISHER_TOKEN")
    publisher_token = raw_publisher_token.strip() if raw_publisher_token and raw_publisher_token.strip() else None

    event_name = env.get("EVENT_NAME") or env.get("GITHUB_EVENT_NAME")
    ref_name = env.get("REF_NAME") or env.get("GITHUB_REF_NAME")
    head_ref = env.get("HEAD_REF") or env.get("GITHUB_HEAD_REF")
    base_ref = env.get("BASE_REF") or env.get("GITHUB_BASE_REF")
    pr_head_sha = env.get("PR_HEAD_SHA")
    pr_head_repo = env.get("PR_HEAD_REPO")

    return AgentConfig(
        ai_provider=ai_provider,
        anthropic_api_key=env.get("ANTHROPIC_API_KEY"),
        gemini_api_key=env.get("GEMINI_API_KEY"),
        anthropic_model=env.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        gemini_model=env.get("GEMINI_MODEL", "gemini-3.8-flash"),
        github_token=env.get("GITHUB_TOKEN"),
        publisher_token=publisher_token,
        repo_name=env.get("REPO_NAME"),
        pr_number=pr_number,
        commit_sha=env.get("COMMIT_SHA", "unknown") or "unknown",
        run_id=env.get("RUN_ID", "unknown") or "unknown",
        log_file=env.get("LOG_FILE", "combined-logs.txt") or "combined-logs.txt",
        ai_timeout_seconds=timeout,
        max_retries=max_retries,
        retry_backoff_factor=backoff,
        max_patch_files=max_patch_files,
        max_patch_lines=max_patch_lines,
        generate_patch=generate_patch,
        verification_timeout_seconds=vtimeout,
        sandbox_image=sandbox_image,
        sandbox_read_only_rootfs=sandbox_ro,
        sandbox_storage_size=sandbox_storage,
        sandbox_storage_mode=sandbox_mode,
        max_repair_attempts=max_attempts,
        base_branch=base_branch,
        github_actor=github_actor,
        enable_repair_pr=enable_repair_pr,
        max_prompt_tokens=max_prompt_tokens,
        event_name=event_name,
        ref_name=ref_name,
        head_ref=head_ref,
        base_ref=base_ref,
        pr_head_sha=pr_head_sha,
        pr_head_repo=pr_head_repo,
    )


def validate_credentials(config: AgentConfig) -> Optional[str]:
    """Check that the active AI provider has its required API key configured.

    Returns:
        Error message string if invalid, or None if valid.
    """
    if config.ai_provider == "claude" and not config.anthropic_api_key:
        return "AI_PROVIDER=claude but ANTHROPIC_API_KEY not set."
    if config.ai_provider == "gemini" and not config.gemini_api_key:
        return "AI_PROVIDER=gemini but GEMINI_API_KEY not set."
    return None

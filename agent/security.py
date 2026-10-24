"""Security utilities for credential redaction, prompt sanitization, and token control.

Provides automated filters for scrubing API keys and secrets from outbound logs,
PR comments, and artifacts, as well as prompt injection delimiters and token budgeting.
"""
import re
from typing import Optional, List, Any

REDACTION_MASK = "[REDACTED_SECRET]"

# Compiled regular expressions for known sensitive credential formats
SECRET_PATTERNS: List[re.Pattern] = [
    # Google Gemini & Cloud API Keys (e.g., AIzaSy...)
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    # Anthropic Claude API Keys (e.g., sk-ant-api03-...)
    re.compile(r"\bsk-ant-[a-zA-Z0-9_\-\.]{20,}\b"),
    # GitHub Classic Personal Access Tokens (ghp_...)
    re.compile(r"\bghp_[a-zA-Z0-9]{20,}\b"),
    # GitHub OAuth Access Tokens (gho_...)
    re.compile(r"\bgho_[a-zA-Z0-9]{20,}\b"),
    # GitHub User-to-Server Tokens (ghu_...)
    re.compile(r"\bghu_[a-zA-Z0-9]{20,}\b"),
    # GitHub Server-to-Server Tokens (ghs_...)
    re.compile(r"\bghs_[a-zA-Z0-9]{20,}\b"),
    # GitHub Refresh Tokens (ghr_...)
    re.compile(r"\bghr_[a-zA-Z0-9]{20,}\b"),
    # GitHub Fine-Grained Personal Access Tokens (github_pat_...)
    re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{40,}\b"),
    # Authorization Bearer Headers
    re.compile(r"(?i)\bBearer\s+[a-zA-Z0-9_\-\.~+/]+=*"),
    # AWS Access Key IDs
    re.compile(r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"),
    # Slack Bot / User Tokens
    re.compile(r"\bxox[baprs]-[0-9a-zA-Z]{10,48}\b"),
    # PEM Private Keys
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----"),
    # Generic key assignment patterns (e.g., api_key = "...", token: '...')
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|auth[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{8,})['\"]?"
    ),
]


def redact_secrets(text: str, custom_secrets: Optional[List[Optional[str]]] = None) -> str:
    """Scrub sensitive credentials, tokens, and API keys from a string.

    Applies both exact-match replacement for known active secrets and regex-based
    pattern matching for recognized credential formats.

    Args:
        text: String to sanitize (logs, PR bodies, error messages, diffs).
        custom_secrets: Optional list of specific active secret strings to redact.

    Returns:
        Sanitized string with credentials replaced by [REDACTED_SECRET].
    """
    if not text:
        return ""

    sanitized = str(text)

    # 1. Exact-match redaction for active runtime secrets
    if custom_secrets:
        # Sort descending by length to avoid partial substring masking
        valid_secrets = sorted(
            [s for s in custom_secrets if s and isinstance(s, str) and len(s) >= 4],
            key=len,
            reverse=True,
        )
        for secret in valid_secrets:
            sanitized = sanitized.replace(secret, REDACTION_MASK)

    # 2. Pattern-based redaction for known credential formats
    for pattern in SECRET_PATTERNS:
        # Check if pattern has groups for key=value assignments
        if pattern.groups == 2:
            def _replace_assignment(m: re.Match) -> str:
                return f"{m.group(1)}={REDACTION_MASK}"
            sanitized = pattern.sub(_replace_assignment, sanitized)
        else:
            sanitized = pattern.sub(REDACTION_MASK, sanitized)

    return sanitized


def redact_data(data: Any, custom_secrets: Optional[List[Optional[str]]] = None) -> Any:
    """Recursively scrub secrets from nested dictionaries, lists, and strings.

    Args:
        data: Data structure to redact (dict, list, or primitive).
        custom_secrets: Optional list of active secrets to redact.

    Returns:
        Sanitized data structure matching input shape.
    """
    if isinstance(data, str):
        return redact_secrets(data, custom_secrets)
    elif isinstance(data, dict):
        return {k: redact_data(v, custom_secrets) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_data(item, custom_secrets) for item in data]
    elif isinstance(data, tuple):
        return tuple(redact_data(item, custom_secrets) for item in data)
    elif isinstance(data, set):
        return {redact_data(item, custom_secrets) for item in data}
    return data


def sanitize_for_prompt(text: str, max_chars: int = 8000) -> str:
    """Sanitize untrusted external text before interpolating into LLM prompts.

    Defangs XML boundary tags, removes null bytes, and bounds total character length.

    Args:
        text: Raw untrusted text (e.g. CI logs, code snippets).
        max_chars: Maximum character limit from the end of the text.

    Returns:
        Sanitized string safe for delimiter-wrapped prompts.
    """
    if not text:
        return ""

    cleaned = str(text)

    # Strip null bytes and non-printable control chars (except newline, tab, cr)
    cleaned = "".join(ch for ch in cleaned if ch in ("\n", "\r", "\t") or ord(ch) >= 32)

    # Defang XML closing tags matching untrusted_* delimiters to prevent breakout
    cleaned = re.sub(
        r"</\s*(untrusted_[a-zA-Z0-9_\-]+)\s*>",
        r"[ESCAPED_DELIMITER_TAG:/\1]",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Enforce maximum character limit from the tail (most recent error context)
    if len(cleaned) > max_chars:
        cleaned = cleaned[-max_chars:]

    return cleaned


def estimate_prompt_tokens(text: str) -> int:
    """Estimate prompt token count using standard 4-char heuristic.

    Args:
        text: Prompt text.

    Returns:
        Estimated number of tokens.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)

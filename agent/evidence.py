"""Evidence normalization and log extraction utilities for Phase 02."""
import re
from typing import Dict
from agent.models import StepOutcome


# Regex matching ANSI escape sequences (colors, cursor movements, erase commands)
ANSI_ESCAPE_PATTERN = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
)


def strip_ansi(text: str) -> str:
    """Remove ANSI terminal control and color sequences from log text.

    Args:
        text: Raw terminal log string possibly containing escape sequences.

    Returns:
        Clean plain-text string with ANSI escape codes removed.
    """
    if not text:
        return ""
    return ANSI_ESCAPE_PATTERN.sub("", text)


def parse_step_outcomes(log_text: str) -> Dict[str, StepOutcome]:
    """Extract step outcomes from the '=== STEP OUTCOMES ===' block in combined logs.

    Expected format:
        === STEP OUTCOMES ===
        install: success
        lint: failure
        test: success
        docker: skipped

    Args:
        log_text: Raw or normalized combined log string.

    Returns:
        Mapping of step name (e.g. 'install', 'lint') to StepOutcome enum value.
    """
    outcomes: Dict[str, StepOutcome] = {}
    if not log_text:
        return outcomes

    clean_text = strip_ansi(log_text)
    pattern = re.compile(
        r"^(install|lint|test|docker)\s*:\s*(success|failure|skipped|cancelled|unknown)\s*$",
        re.MULTILINE | re.IGNORECASE,
    )

    for match in pattern.finditer(clean_text):
        step_name = match.group(1).lower()
        outcome_str = match.group(2).lower()
        try:
            outcomes[step_name] = StepOutcome(outcome_str)
        except ValueError:
            outcomes[step_name] = StepOutcome.UNKNOWN

    return outcomes


def split_stage_logs(log_text: str) -> Dict[str, str]:
    """Split concatenated combined logs into isolated per-stage logs.

    Recognized headers:
        === INSTALL LOGS ===
        === LINT LOGS ===
        === TEST LOGS ===
        === DOCKER LOGS ===
        === STEP OUTCOMES ===

    Args:
        log_text: Raw combined logs.

    Returns:
        Dictionary mapping stage name (e.g. 'install', 'lint', 'test', 'docker')
        to the stage's isolated log content.
    """
    stages: Dict[str, str] = {
        "install": "",
        "lint": "",
        "test": "",
        "docker": "",
    }
    if not log_text:
        return stages

    clean_text = strip_ansi(log_text)
    section_pattern = re.compile(
        r"===\s*([A-Z]+)\s+LOGS\s*===(.*?)(?=(?:===\s*[A-Z]+\s+(?:LOGS|OUTCOMES)\s*===)|\Z)",
        re.DOTALL,
    )

    for match in section_pattern.finditer(clean_text):
        sec_name = match.group(1).lower()
        content = match.group(2).strip()
        if sec_name in stages:
            stages[sec_name] = content

    return stages


def extract_stack_trace_snippet(log_text: str, max_lines: int = 50) -> str:
    """Extract a concise diagnostic snippet containing failure stack traces or errors.

    Args:
        log_text: Log text to inspect.
        max_lines: Maximum lines to retain in snippet.

    Returns:
        Extracted diagnostic window or the tail of the log text.
    """
    if not log_text:
        return ""

    lines = log_text.splitlines()
    error_indices = []

    # Search for common error markers
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if any(marker in line_lower for marker in [
            "traceback (most recent call last)",
            "assertionerror",
            "failed tests/",
            "e302 expected",
            "syntaxerror",
            "no module named",
            "error: failed to solve",
        ]):
            error_indices.append(idx)

    if not error_indices:
        # Fall back to the last max_lines
        return "\n".join(lines[-max_lines:])

    # Capture from the first significant error marker
    start_idx = max(0, error_indices[0] - 2)
    end_idx = min(len(lines), start_idx + max_lines)
    return "\n".join(lines[start_idx:end_idx])

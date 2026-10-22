"""Accurate failure classification based on authoritative step outcomes and narrow signals."""
import re
from typing import Dict, List
from agent.models import StepOutcome, PipelineStatus, FailureContext
from agent.evidence import parse_step_outcomes, strip_ansi

# Narrow regex patterns for fallback heuristic matching when step outcomes are unavailable
# Designed specifically to avoid false positives on tool names like 'pip', 'pytest', 'flake8', 'step'
NARROW_FAILURE_PATTERNS = {
    "install": [
        re.compile(r"\bERROR:\s+No matching distribution found\b", re.IGNORECASE),
        re.compile(r"\bERROR:\s+Could not find a version that satisfies the requirement\b", re.IGNORECASE),
        re.compile(r"\bModuleNotFoundError:\s+No module named\b"),
        re.compile(r"\bResolutionImpossible\b"),
        re.compile(r"\bpip install.*(?:failed|error)\b", re.IGNORECASE),
        re.compile(r"\bCould not install packages due to an OSError\b", re.IGNORECASE),
    ],
    "lint": [
        re.compile(r"\b[a-zA-Z0-9_\-\./]+:\d+:\d+:\s+[EWF]\d+\b"),  # e.g., app.py:12:1: E302
        re.compile(r"\b(?:SyntaxError|IndentationError):\s+"),
        re.compile(r"\bflake8.*(?:failed|error:)\b", re.IGNORECASE),
    ],
    "test": [
        re.compile(r"\bFAILED\s+tests/"),
        re.compile(r"\bAssertionError\b"),
        re.compile(r"\b=== FAILURES ===\b"),
        re.compile(r"\b[1-9]\d*\s+failed\b"),  # Matches '1 failed', '3 failed', never '0 failed'
        re.compile(r"\bpytest:\s*error:\b", re.IGNORECASE),
        re.compile(r"\bPYTEST_FAILED=true\b"),
    ],
    "docker": [
        re.compile(r"\bERROR:\s+failed to solve:", re.IGNORECASE),
        re.compile(r"\bfailed to build:\b", re.IGNORECASE),
        re.compile(r"\bThe command\s+'.*'\s+returned a non-zero code:", re.IGNORECASE),
        re.compile(r"\bexecutor failed running\b", re.IGNORECASE),
        re.compile(r"\bDocker build failed\b", re.IGNORECASE),
    ],
}

POSITIVE_COMPLETION_PATTERNS = [
    re.compile(r"\bpassed in \d+", re.IGNORECASE),
    re.compile(r"\b0 errors\b", re.IGNORECASE),
    re.compile(r"\b0 failed\b", re.IGNORECASE),
    re.compile(r"\bAll checks passed\b", re.IGNORECASE),
    re.compile(r"\bDocker image built successfully\b", re.IGNORECASE),
    re.compile(r"\bDocker image created\b", re.IGNORECASE),
    re.compile(r"\bSuccessfully tagged\b", re.IGNORECASE),
    re.compile(r"\b=== PIPELINE RUN SUMMARY ===\b"),
]


def classify_failures(logs: str) -> FailureContext:
    """Classify CI/CD pipeline failures using authoritative step outcomes or narrow fallback signals.

    Strategy:
    1. Primary: If '=== STEP OUTCOMES ===' metadata exists in the log, evaluate exact
       step conclusion flags ('success', 'failure', 'skipped', 'cancelled').
    2. Fallback: If step outcomes are absent, use narrowly targeted regex patterns
       that match genuine compiler/test/installer errors rather than general tool names.
    3. Status attribution: Explicitly evaluate PipelineStatus (HEALTHY, FAILED, INCONCLUSIVE, ERROR).
       Never assume a pipeline is healthy if evidence is absent, empty, or contradictory.

    Args:
        logs: Diagnostic log content string.

    Returns:
        FailureContext containing detected failure categories, raw booleans,
        evaluated PipelineStatus, step outcomes map, and optional details.
    """
    if not logs or not logs.strip():
        return FailureContext(
            detected=[],
            raw={"install": False, "lint": False, "test": False, "docker": False},
            status=PipelineStatus.INCONCLUSIVE,
            details="Log text is empty or missing content",
        )

    clean_logs = strip_ansi(logs)

    if clean_logs.startswith("Error reading log file") or "no log file found" in clean_logs.lower():
        return FailureContext(
            detected=[],
            raw={"install": False, "lint": False, "test": False, "docker": False},
            status=PipelineStatus.ERROR,
            details=clean_logs.strip(),
        )

    # ── 1. Authoritative Step Outcomes Evaluation ────────────────────
    step_outcomes = parse_step_outcomes(clean_logs)
    if step_outcomes:
        detected_categories: List[str] = []
        raw_flags: Dict[str, bool] = {
            "install": False,
            "lint": False,
            "test": False,
            "docker": False,
        }

        has_cancelled = False
        has_failure = False
        has_success = False

        for step_name, outcome in step_outcomes.items():
            if outcome == StepOutcome.FAILURE:
                has_failure = True
                if step_name in raw_flags:
                    raw_flags[step_name] = True
                    detected_categories.append(step_name)
            elif outcome == StepOutcome.CANCELLED:
                has_cancelled = True
            elif outcome == StepOutcome.SUCCESS:
                has_success = True

        if has_failure:
            status = PipelineStatus.FAILED
            details = f"Authoritative step failure detected in: {', '.join(detected_categories)}"
        elif has_cancelled:
            status = PipelineStatus.INCONCLUSIVE
            details = "Pipeline execution was cancelled"
        elif has_success:
            status = PipelineStatus.HEALTHY
            details = "All executed steps reported success"
        else:
            status = PipelineStatus.INCONCLUSIVE
            details = "All pipeline steps were skipped or outcome unknown"

        return FailureContext(
            detected=detected_categories,
            raw=raw_flags,
            status=status,
            step_outcomes=step_outcomes,
            details=details,
        )

    # ── 2. Narrow Heuristic Fallback Evaluation ───────────────────────
    raw_flags = {}
    detected_categories = []

    for category, patterns in NARROW_FAILURE_PATTERNS.items():
        matched = any(pattern.search(clean_logs) for pattern in patterns)
        raw_flags[category] = matched
        if matched:
            detected_categories.append(category)

    if detected_categories:
        status = PipelineStatus.FAILED
        details = f"Failure patterns identified in log content: {', '.join(detected_categories)}"
    else:
        # Check if positive completion evidence is present
        has_positive_evidence = any(p.search(clean_logs) for p in POSITIVE_COMPLETION_PATTERNS)
        if has_positive_evidence:
            status = PipelineStatus.HEALTHY
            details = "No failure patterns found; positive completion markers verified"
        else:
            # Missing both failure signals and completion markers
            status = PipelineStatus.INCONCLUSIVE
            details = "No failure patterns detected, but completion markers are missing"

    return FailureContext(
        detected=detected_categories,
        raw=raw_flags,
        status=status,
        step_outcomes={},
        details=details,
    )

"""Tests for evidence extraction, ANSI stripping, and step outcome parsing."""
from agent.evidence import (
    strip_ansi,
    parse_step_outcomes,
    split_stage_logs,
    extract_stack_trace_snippet,
)
from agent.models import StepOutcome


def test_strip_ansi_colors():
    """Verify stripping of standard ANSI color codes."""
    colored_text = "\x1b[31mRed Error\x1b[0m \x1b[1;32mGreen Success\x1b[0m"
    clean = strip_ansi(colored_text)
    assert clean == "Red Error Green Success"


def test_strip_ansi_cursor_and_clear():
    """Verify stripping of cursor movements and clear codes."""
    raw = "\x1b[2J\x1b[HWelcome to build\x1b[1K"
    clean = strip_ansi(raw)
    assert clean == "Welcome to build"


def test_strip_ansi_preserves_plain_text():
    """Verify normal plain text is not corrupted."""
    text = "Normal output without escape codes\nLine 2: 100% complete"
    assert strip_ansi(text) == text


def test_strip_ansi_empty():
    """Verify empty or None text handling."""
    assert strip_ansi("") == ""
    assert strip_ansi(None) == ""


def test_parse_step_outcomes_valid():
    """Verify parsing of standard STEP OUTCOMES block."""
    log_content = (
        "Some preceding log text\n"
        "=== STEP OUTCOMES ===\n"
        "install: success\n"
        "lint: failure\n"
        "test: success\n"
        "docker: skipped\n"
    )
    outcomes = parse_step_outcomes(log_content)
    assert outcomes["install"] == StepOutcome.SUCCESS
    assert outcomes["lint"] == StepOutcome.FAILURE
    assert outcomes["test"] == StepOutcome.SUCCESS
    assert outcomes["docker"] == StepOutcome.SKIPPED


def test_parse_step_outcomes_with_ansi_and_whitespace():
    """Verify outcomes are parsed even if ANSI colors are embedded."""
    log_content = (
        "=== STEP OUTCOMES ===\n"
        "\x1b[32minstall: success\x1b[0m\n"
        "\x1b[31mlint: failure\x1b[0m\n"
        "test: CANCELLED\n"
    )
    outcomes = parse_step_outcomes(log_content)
    assert outcomes["install"] == StepOutcome.SUCCESS
    assert outcomes["lint"] == StepOutcome.FAILURE
    assert outcomes["test"] == StepOutcome.CANCELLED


def test_parse_step_outcomes_missing_or_empty():
    """Verify empty dict returned when STEP OUTCOMES block is absent."""
    assert parse_step_outcomes("No outcomes block here") == {}
    assert parse_step_outcomes("") == {}


def test_split_stage_logs_standard():
    """Verify splitting combined logs into per-stage sections."""
    combined = (
        "=== INSTALL LOGS ===\n"
        "pip install -r requirements.txt\n"
        "=== LINT LOGS ===\n"
        "flake8: sample-app/app.py:12:1: E302\n"
        "=== TEST LOGS ===\n"
        "pytest run: 3 passed\n"
        "=== DOCKER LOGS ===\n"
        "docker build success\n"
        "=== STEP OUTCOMES ===\n"
        "install: success\n"
    )
    stages = split_stage_logs(combined)
    assert "pip install" in stages["install"]
    assert "flake8: sample-app/app.py" in stages["lint"]
    assert "pytest run: 3 passed" in stages["test"]
    assert "docker build success" in stages["docker"]


def test_split_stage_logs_missing_sections():
    """Verify missing sections default to empty strings without crashing."""
    combined = (
        "=== TEST LOGS ===\n"
        "pytest failed\n"
    )
    stages = split_stage_logs(combined)
    assert stages["test"] == "pytest failed"
    assert stages["install"] == ""
    assert stages["lint"] == ""
    assert stages["docker"] == ""


def test_extract_stack_trace_snippet_with_traceback():
    """Verify extraction centered around Python traceback."""
    lines = [f"Info line {i}" for i in range(20)]
    lines.append("Traceback (most recent call last):")
    lines.append('  File "app.py", line 10, in <module>')
    lines.append("    raise ValueError('Bad value')")
    lines.extend([f"Trailing line {i}" for i in range(20)])
    log = "\n".join(lines)

    snippet = extract_stack_trace_snippet(log, max_lines=10)
    assert "Traceback (most recent call last):" in snippet
    assert "raise ValueError('Bad value')" in snippet


def test_extract_stack_trace_snippet_fallback():
    """Verify extraction falls back to tail if no known traceback markers exist."""
    lines = [f"Line {i}" for i in range(40)]
    log = "\n".join(lines)
    snippet = extract_stack_trace_snippet(log, max_lines=5)
    assert "Line 39" in snippet
    assert len(snippet.splitlines()) == 5

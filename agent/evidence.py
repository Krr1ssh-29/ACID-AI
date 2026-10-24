"""Evidence normalization and log extraction utilities for Phase 02."""
import re
from typing import Dict, Any
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


def extract_affected_files(log_text: str, repo_root: str) -> list[str]:
    """Identify repository files cited in failure traces that exist in the repository."""
    files, _, _ = inspect_affected_files(log_text, repo_root)
    return files


def inspect_affected_files(
    log_text: str,
    repo_root: str,
    max_files: int = 5,
    max_lines_per_file: int = 80,
) -> tuple[list[str], str, dict[str, Any]]:
    """Scan failure logs for cited repository file paths, inspect their contents, and format source snippets.

    CRITICAL BOUNDARIES:
    - Never inspects or includes secret/credential files (.env, .pem, id_rsa, etc.).
    - Never inspects Git internals (.git/) or GitHub workflows (.github/).
    - Only reads files that exist within the repository.
    - Redacts all sensitive patterns before returning snippets.

    Args:
        log_text: Raw or normalized failure log text.
        repo_root: Path to the repository or disposable workspace.
        max_files: Maximum number of affected files to extract.
        max_lines_per_file: Maximum lines of source code to include per file.

    Returns:
        Tuple of:
            - List of relative affected file paths (e.g. ['sample-app/app.py'])
            - Formatted source snippets string with line numbers for prompt context
            - Metadata dictionary mapping file path to detected line numbers
    """
    import os
    from agent.security import redact_secrets

    if not log_text or not repo_root:
        return [], "", {}

    clean_text = strip_ansi(log_text)
    abs_root = os.path.abspath(repo_root).replace("\\", "/")
    file_lines: dict[str, list[int]] = {}

    def add_candidate(raw_path: str, line_no: int | None = None) -> None:
        if not raw_path:
            return
        clean_p = raw_path.strip().strip("'\"()[]").replace("\\", "/")
        # Ignore python stdlib, virtual environments, site-packages, etc.
        ignored_segments = (
            ".venv",
            "venv",
            "site-packages",
            "lib/python",
            "appdata",
            "__pycache__",
            "python3",
            "pytest",
            "pluggy",
        )
        if any(seg in clean_p.lower() for seg in ignored_segments):
            return

        # If path is absolute, check if it's within abs_root
        rel_path = None
        if os.path.isabs(clean_p) or (len(clean_p) > 1 and clean_p[1] == ":"):
            clean_abs = os.path.abspath(clean_p).replace("\\", "/")
            if clean_abs.startswith(abs_root + "/"):
                rel_path = clean_abs[len(abs_root) + 1:]
            else:
                # Subpath match (e.g. /app/sample-app/app.py where repo has sample-app/app.py)
                parts = clean_p.strip("/").split("/")
                for i in range(len(parts)):
                    sub = "/".join(parts[i:])
                    if os.path.isfile(os.path.join(repo_root, sub)):
                        rel_path = sub
                        break
        else:
            rel_path = clean_p.lstrip("./")

        if not rel_path:
            return

        norm_path = rel_path.strip()
        if ".." in norm_path or norm_path.startswith("/"):
            return
        if norm_path == ".git" or norm_path.startswith(".git/") or "/.git/" in f"/{norm_path}/":
            return
        if norm_path == ".github" or norm_path.startswith(".github/") or "/.github/" in f"/{norm_path}/":
            return

        base_name = os.path.basename(norm_path).lower()
        secret_keys = ("id_rsa", ".pem", ".key", "secret", "token", "password", ".env")
        if any(keyword in base_name for keyword in secret_keys):
            return

        # Verify path exists as a regular file in repo_root
        full_path = os.path.join(repo_root, norm_path)
        if not os.path.isfile(full_path):
            return

        if norm_path not in file_lines:
            file_lines[norm_path] = []
        if line_no is not None and line_no not in file_lines[norm_path]:
            file_lines[norm_path].append(line_no)

    # 1. Python tracebacks: File "path/to/file.py", line 123
    for m in re.finditer(r'File "([^"]+)", line (\d+)', clean_text):
        add_candidate(m.group(1), int(m.group(2)))

    # 2. Pytest assertion failure / error locations: path/to/file.py:123:
    for m in re.finditer(r'(?:^|[\s(])([a-zA-Z0-9_\-./\\]+\.py):(\d+):', clean_text):
        add_candidate(m.group(1), int(m.group(2)))

    # 3. Pytest FAILED summary: FAILED path/to/file.py::test_name
    for m in re.finditer(r'(?:FAILED|ERROR)\s+([a-zA-Z0-9_\-./\\]+\.py)::', clean_text):
        add_candidate(m.group(1), None)

    # 4. Flake8 style violations: path/to/file.py:123:1: E302
    for m in re.finditer(r'(?:^|[\s(])([a-zA-Z0-9_\-./\\]+\.py):(\d+):(?:\d+:)?\s+[EFWC]\d+', clean_text):
        add_candidate(m.group(1), int(m.group(2)))

    # 5. Dependency or manifest mentions
    if any(marker in clean_text.lower() for marker in ("requirement", "could not find a version", "pip install")):
        for manifest_cand in ("requirements.txt", "sample-app/requirements.txt", "pyproject.toml"):
            if os.path.isfile(os.path.join(repo_root, manifest_cand)):
                add_candidate(manifest_cand, None)

    # 6. Dockerfile mentions
    if any(marker in clean_text.lower() for marker in ("dockerfile", "copy failed", "build failed")):
        for docker_cand in ("Dockerfile", "sample-app/Dockerfile"):
            if os.path.isfile(os.path.join(repo_root, docker_cand)):
                add_candidate(docker_cand, None)

    # 7. For detected test files, also identify the implementation files being tested
    test_paths = list(file_lines.keys())
    for t_path in test_paths:
        base = os.path.basename(t_path)
        stem, ext = os.path.splitext(base)
        if ext != ".py":
            continue
        is_test = (
            stem.startswith("test_")
            or stem.endswith("_test")
            or "/tests/" in f"/{t_path}/"
            or "/test/" in f"/{t_path}/"
        )
        if not is_test:
            continue

        mod_name = ""
        if stem.startswith("test_"):
            mod_name = stem[5:]
        elif stem.endswith("_test"):
            mod_name = stem[:-5]

        t_dir = os.path.dirname(t_path)
        parent_dir = os.path.dirname(t_dir)
        candidate_dirs = [
            t_dir,
            parent_dir,
            os.path.join(parent_dir, "src"),
            os.path.join(t_dir, "src"),
            "",
            "src",
        ]

        if mod_name:
            for c_dir in candidate_dirs:
                cand_path = os.path.normpath(os.path.join(c_dir, f"{mod_name}.py")).replace("\\", "/")
                cand_full = os.path.join(repo_root, cand_path)
                if os.path.isfile(cand_full):
                    add_candidate(cand_path, None)
                    if cand_path in file_lines and not file_lines[cand_path]:
                        try:
                            with open(cand_full, "r", encoding="utf-8", errors="replace") as cf:
                                for line_idx, line_text in enumerate(cf, start=1):
                                    fn_match = re.search(r'def\s+([a-zA-Z0-9_]+)\s*\(', line_text)
                                    if fn_match and fn_match.group(1).lower() in clean_text.lower():
                                        file_lines[cand_path].append(line_idx)
                        except Exception:
                            pass

        t_full = os.path.join(repo_root, t_path)
        try:
            with open(t_full, "r", encoding="utf-8", errors="replace") as f:
                t_content = f.read()
            for imp_match in re.finditer(r'(?:from|import)\s+([a-zA-Z0-9_]+)', t_content):
                imp_mod = imp_match.group(1)
                for c_dir in candidate_dirs:
                    cand_path = os.path.normpath(os.path.join(c_dir, f"{imp_mod}.py")).replace("\\", "/")
                    cand_full = os.path.join(repo_root, cand_path)
                    if os.path.isfile(cand_full):
                        add_candidate(cand_path, None)
                        if cand_path in file_lines and not file_lines[cand_path]:
                            try:
                                with open(cand_full, "r", encoding="utf-8", errors="replace") as cf:
                                    for line_idx, line_text in enumerate(cf, start=1):
                                        fn_match = re.search(r'def\s+([a-zA-Z0-9_]+)\s*\(', line_text)
                                        if fn_match and fn_match.group(1).lower() in clean_text.lower():
                                            file_lines[cand_path].append(line_idx)
                            except Exception:
                                pass
        except Exception:
            pass

    affected_files = list(file_lines.keys())[:max_files]
    snippets_list = []

    for f_path in affected_files:
        full_path = os.path.join(repo_root, f_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            lines = content.splitlines()
        except Exception:
            continue

        target_lines = file_lines.get(f_path, [])
        if len(lines) <= max_lines_per_file:
            start_idx = 1
            end_idx = len(lines)
            selected_lines = lines
        elif target_lines:
            center = target_lines[0]
            half = max_lines_per_file // 2
            start_idx = max(1, center - half)
            end_idx = min(len(lines), start_idx + max_lines_per_file - 1)
            selected_lines = lines[start_idx - 1:end_idx]
        else:
            start_idx = 1
            end_idx = min(len(lines), max_lines_per_file)
            selected_lines = lines[:end_idx]

        file_snippet = [f"=== File: {f_path} (lines {start_idx}-{end_idx}) ==="]
        for idx, line_str in enumerate(selected_lines, start=start_idx):
            file_snippet.append(f"{idx:4d}: {line_str}")

        raw_snippet = "\n".join(file_snippet)
        snippets_list.append(redact_secrets(raw_snippet))

    source_snippets = "\n\n".join(snippets_list)
    return affected_files, source_snippets, file_lines

"""Bounded log collection and safe reading functionality."""
import os
from typing import Optional
from agent.evidence import strip_ansi

DEFAULT_LOG_FILE = "combined-logs.txt"
# Default budget: 50 KB (51,200 bytes) per ROADMAP.md Phase 02 specification
DEFAULT_MAX_BYTES = 51200
TRUNCATION_MARKER = "...[truncated: log exceeded size limit, showing tail]...\n"


def read_logs_bounded(
    log_file: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    """Read CI pipeline failure logs with strict memory-bounded tail reading.

    Memory safety:
    Instead of loading entire unbounded files into memory before slicing, this
    function seeks directly to (file_size - max_bytes) on disk and reads only
    the requested byte budget. An arbitrarily large file (e.g. 10 GB) will never
    allocate more than max_bytes in RAM.

    Args:
        log_file: Path to the log file. Defaults to 'combined-logs.txt'.
        max_bytes: Maximum bytes to read from the tail of the file.

    Returns:
        String containing plain-text log content with ANSI escape sequences removed,
        with TRUNCATION_MARKER prepended if content exceeded max_bytes.
    """
    target = log_file or DEFAULT_LOG_FILE
    if not os.path.exists(target):
        return "No log file found — pipeline may have failed before log collection."

    try:
        file_size = os.path.getsize(target)
        if file_size == 0:
            return ""

        with open(target, "rb") as f:
            if file_size <= max_bytes:
                raw_bytes = f.read()
                text = raw_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")
                return strip_ansi(text)
            else:
                f.seek(file_size - max_bytes)
                raw_bytes = f.read(max_bytes)
                text = raw_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")
                # Drop first potentially truncated line to avoid partial line fragments
                if "\n" in text:
                    text = text.split("\n", 1)[1]
                return TRUNCATION_MARKER + strip_ansi(text)
    except OSError as e:
        return f"Error reading log file '{target}': {e}"


def read_logs(
    log_file: Optional[str] = None,
    max_chars: Optional[int] = None,
) -> str:
    """Backwards-compatible wrapper delegating to memory-bounded reader.

    Args:
        log_file: Path to the log file. Defaults to 'combined-logs.txt'.
        max_chars: Maximum character/byte limit to read.

    Returns:
        Log text string with truncation and ANSI stripping applied.
    """
    budget = max_chars if max_chars is not None else DEFAULT_MAX_BYTES
    return read_logs_bounded(log_file, max_bytes=budget)

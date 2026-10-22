"""Tests for memory-bounded log collection and safe reading in agent.collector."""
from agent.collector import read_logs, read_logs_bounded, TRUNCATION_MARKER


def test_read_logs_existing_file_within_limit(tmp_path):
    """Verify read_logs returns exact file content when within truncation limit."""
    log_file = tmp_path / "test-logs.txt"
    sample_text = "Standard error output line 1\nStandard error output line 2\n"
    log_file.write_text(sample_text, encoding="utf-8")

    content = read_logs(str(log_file), max_chars=8000)
    assert content == sample_text


def test_read_logs_bounded_memory_for_large_file(tmp_path):
    """Verify reader reads only max_bytes from tail of an oversized file."""
    log_file = tmp_path / "large-logs.txt"
    # Create 200 KB file with distinct head and tail
    head_content = "HEAD_LINE_" * 15000 + "\n"
    tail_content = "TAIL_DIAGNOSTIC_LINE_1\nTAIL_DIAGNOSTIC_LINE_2\nFINAL_ERROR: test failed\n"
    log_file.write_text(head_content + tail_content, encoding="utf-8")

    # Read with 2 KB budget
    content = read_logs_bounded(str(log_file), max_bytes=2048)
    assert content.startswith(TRUNCATION_MARKER)
    assert "FINAL_ERROR: test failed" in content
    assert "TAIL_DIAGNOSTIC_LINE_2" in content
    # Total content size should be bounded (TRUNCATION_MARKER + <= max_bytes)
    assert len(content) <= len(TRUNCATION_MARKER) + 2048


def test_read_logs_strips_ansi_codes(tmp_path):
    """Verify ANSI terminal escape sequences are stripped during file reading."""
    log_file = tmp_path / "colored.txt"
    colored_text = "\x1b[31m[ERROR]\x1b[0m \x1b[1mPytest failed\x1b[0m\n"
    log_file.write_text(colored_text, encoding="utf-8")

    content = read_logs(str(log_file))
    assert "\x1b" not in content
    assert content == "[ERROR] Pytest failed\n"


def test_read_logs_invalid_utf8_recovery(tmp_path):
    """Verify corrupt or invalid UTF-8 byte sequences are handled safely without crashing."""
    log_file = tmp_path / "corrupt.txt"
    # Write invalid UTF-8 byte sequences alongside valid text
    corrupt_bytes = b"Valid preamble\n\xff\xfe\xfa\x80\x81\nValid postscript\n"
    log_file.write_bytes(corrupt_bytes)

    content = read_logs(str(log_file))
    assert "Valid preamble" in content
    assert "Valid postscript" in content
    assert "\ufffd" in content  # Unicode replacement character used


def test_read_logs_empty_file(tmp_path):
    """Verify empty 0-byte file returns empty string."""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_bytes(b"")

    content = read_logs(str(empty_file))
    assert content == ""


def test_read_logs_missing_file():
    """Verify fallback message when log file does not exist."""
    content = read_logs("nonexistent-file-that-does-not-exist.txt")
    assert "No log file found" in content
    assert "pipeline may have failed before log collection" in content


def test_read_logs_os_error_handling(tmp_path, monkeypatch):
    """Verify graceful handling when file cannot be accessed."""
    log_file = tmp_path / "locked.txt"
    log_file.write_text("hello", encoding="utf-8")

    def mock_open(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr("builtins.open", mock_open)
    content = read_logs(str(log_file))
    assert "Error reading log file" in content

"""Tests for AI response parsing in agent.parser."""
import pytest
import json
from agent.parser import parse_ai_response


def test_parse_clean_json():
    """Verify parsing a valid, clean JSON string."""
    raw = '{"severity": "high", "root_cause": "Module missing"}'
    data = parse_ai_response(raw)
    assert data["severity"] == "high"
    assert data["root_cause"] == "Module missing"


def test_parse_json_with_markdown_fences():
    """Verify parsing JSON wrapped in ```json ... ``` code blocks."""
    raw = """```json
{
  "severity": "critical",
  "failure_types": ["install"],
  "root_cause": "Missing dependency",
  "fixes": []
}
```"""
    data = parse_ai_response(raw)
    assert data["severity"] == "critical"
    assert data["failure_types"] == ["install"]


def test_parse_json_with_plain_fences():
    """Verify parsing JSON wrapped in plain ``` ... ``` code blocks."""
    raw = """```
{
  "severity": "medium",
  "root_cause": "Flake8 line length"
}
```"""
    data = parse_ai_response(raw)
    assert data["severity"] == "medium"
    assert data["root_cause"] == "Flake8 line length"


def test_parse_json_with_conversational_text():
    """Verify extracting JSON when surrounded by model conversational preamble."""
    raw = """Sure! Here is the JSON diagnosis for your failed CI run:
{
  "severity": "high",
  "root_cause": "Assertion failed on line 28",
  "fixes": [
    {
      "type": "test",
      "title": "Fix expected status",
      "description": "Change expected code from 500 to 200"
    }
  ]
}
I hope this helps fix your build!"""
    data = parse_ai_response(raw)
    assert data["severity"] == "high"
    assert len(data["fixes"]) == 1
    assert data["fixes"][0]["type"] == "test"


def test_parse_malformed_json_raises_error():
    """Verify json.JSONDecodeError is raised when text contains no valid JSON."""
    raw = "I am sorry, but I cannot analyze these logs because they are empty."
    with pytest.raises(json.JSONDecodeError):
        parse_ai_response(raw)

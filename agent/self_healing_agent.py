"""ACID AI — Self-Healing CI/CD Pipeline Agent.

----------------------------------
Analyses pipeline failures across:
- Dependency installation errors
- Lint failures (flake8)
- Test failures (pytest)
- Docker build failures

Supports multiple AI providers:
- Anthropic Claude (production)
- Google Gemini (free tier / testing)

Configure via AI_PROVIDER environment variable: "claude" or "gemini"

Posts structured diagnosis + fix suggestions as a PR comment.
Author: Ayushi Vasishtha
Refactored for Phase 01: Modularized into agent/ package while preserving
exact backward-compatible API and script invocation behavior.
"""

import os
import sys

# Ensure repository root is in sys.path when invoked directly as a script
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from typing import Dict, Any

from agent.collector import read_logs as _read_logs
from agent.classifier import classify_failures as _classify_failures
from agent.parser import parse_ai_response as _parse_ai_response
from agent.formatter import format_pr_comment as _format_pr_comment
from agent.github import post_pr_comment as _post_pr_comment
from agent.providers import (
    SYSTEM_PROMPT,
    analyse_with_claude as _analyse_with_claude,
    analyse_with_gemini as _analyse_with_gemini,
    analyse_with_ai as _analyse_with_ai,
)
from agent.cli import main as _cli_main

# ── Config ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "claude").lower()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("REPO_NAME")
PR_NUMBER = os.environ.get("PR_NUMBER")
COMMIT_SHA = os.environ.get("COMMIT_SHA", "unknown")
RUN_ID = os.environ.get("RUN_ID", "unknown")
LOG_FILE = "combined-logs.txt"

__all__ = [
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "AI_PROVIDER",
    "GITHUB_TOKEN",
    "REPO_NAME",
    "PR_NUMBER",
    "COMMIT_SHA",
    "RUN_ID",
    "LOG_FILE",
    "SYSTEM_PROMPT",
    "read_logs",
    "classify_failures",
    "parse_ai_response",
    "analyse_with_claude",
    "analyse_with_gemini",
    "analyse_with_ai",
    "format_pr_comment",
    "post_pr_comment",
    "main",
]


def read_logs() -> str:
    """Read failure logs from the default combined-logs.txt path."""
    return _read_logs(LOG_FILE)


def classify_failures(logs: str) -> Dict[str, Any]:
    """Scan log text for failure patterns across four categories."""
    return _classify_failures(logs)


def parse_ai_response(raw_text: str) -> Dict[str, Any]:
    """Extract and parse structured JSON from raw model output."""
    return _parse_ai_response(raw_text)


def analyse_with_claude(logs: str, failure_context: Dict[str, Any]) -> Dict[str, Any]:
    """Diagnose pipeline failure using Anthropic Claude."""
    return _analyse_with_claude(logs, failure_context, api_key=os.environ.get("ANTHROPIC_API_KEY"))


def analyse_with_gemini(logs: str, failure_context: Dict[str, Any]) -> Dict[str, Any]:
    """Diagnose pipeline failure using Google Gemini."""
    return _analyse_with_gemini(logs, failure_context, api_key=os.environ.get("GEMINI_API_KEY"))


def analyse_with_ai(logs: str, failure_context: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch failure analysis to the configured AI provider."""
    return _analyse_with_ai(logs, failure_context)


def format_pr_comment(analysis: Dict[str, Any], commit_sha: str, run_id: str, repo: str) -> str:
    """Format structured diagnosis and fixes into a GitHub PR markdown comment."""
    return _format_pr_comment(analysis, commit_sha, run_id, repo, ai_provider=os.environ.get("AI_PROVIDER", "claude"))


def post_pr_comment(comment: str) -> bool:
    """Post diagnostic report as a comment on the target GitHub Pull Request."""
    return _post_pr_comment(comment, repo_name=REPO_NAME, pr_number=PR_NUMBER, token=GITHUB_TOKEN)


def main():
    """Run the triage agent cli entrypoint."""
    sys.exit(_cli_main())


if __name__ == "__main__":
    main()

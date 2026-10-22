"""Tests for GitHub API integration in agent.github."""
from unittest.mock import MagicMock
from agent.github import post_pr_comment


def test_post_pr_comment_direct_push_no_pr(capsys):
    """Verify that absent PR_NUMBER prints comment locally and returns False."""
    success = post_pr_comment(
        comment="Diagnostic content",
        repo_name="owner/repo",
        pr_number=None,
        token="fake_token",
    )
    assert success is False
    captured = capsys.readouterr()
    assert "No PR number — direct push" in captured.out
    assert "Diagnostic content" in captured.out


def test_post_pr_comment_direct_push_string_none(capsys):
    """Verify that PR_NUMBER='None' string prints comment locally and returns False."""
    success = post_pr_comment(
        comment="Direct push analysis",
        repo_name="owner/repo",
        pr_number="None",
        token="fake_token",
    )
    assert success is False
    captured = capsys.readouterr()
    assert "No PR number — direct push" in captured.out


def test_post_pr_comment_missing_repo(capsys):
    """Verify handling when REPO_NAME is missing."""
    success = post_pr_comment(
        comment="Comment",
        repo_name=None,
        pr_number="123",
        token="fake_token",
    )
    assert success is False
    captured = capsys.readouterr()
    assert "Cannot post PR comment: REPO_NAME is not set" in captured.out


def test_post_pr_comment_success(monkeypatch):
    """Verify successful PR comment creation returns True on HTTP 201."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201

    mock_post = MagicMock(return_value=mock_resp)
    monkeypatch.setattr("requests.post", mock_post)

    success = post_pr_comment(
        comment="LGTM failure diagnosis",
        repo_name="test-org/test-repo",
        pr_number="42",
        token="gh_test_token",
    )
    assert success is True

    # Verify endpoint and headers
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.github.com/repos/test-org/test-repo/issues/42/comments"
    assert kwargs["headers"]["Authorization"] == "token gh_test_token"
    assert kwargs["headers"]["Accept"] == "application/vnd.github.v3+json"
    assert kwargs["json"]["body"] == "LGTM failure diagnosis"


def test_post_pr_comment_api_error(monkeypatch):
    """Verify failure returns False when GitHub API returns non-201."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Resource not accessible by integration"

    mock_post = MagicMock(return_value=mock_resp)
    monkeypatch.setattr("requests.post", mock_post)

    success = post_pr_comment(
        comment="Some comment",
        repo_name="test-org/test-repo",
        pr_number="42",
        token="bad_token",
    )
    assert success is False

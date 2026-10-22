"""GitHub API integration for posting comments."""
import os
import requests
from typing import Optional


def post_pr_comment(
    comment: str,
    repo_name: Optional[str] = None,
    pr_number: Optional[str] = None,
    token: Optional[str] = None,
) -> bool:
    """Post diagnostic report as a comment on the target GitHub Pull Request.

    If PR_NUMBER is absent, 'None', or empty, treats execution as a direct push,
    printing the comment to stdout and returning False.

    Args:
        comment: Markdown comment content to post.
        repo_name: Repository in 'owner/repo' format.
        pr_number: Pull request number string.
        token: GitHub token with pull-requests:write or issues:write permissions.

    Returns:
        True if comment was successfully created (HTTP 201), False otherwise.
    """
    repo = repo_name or os.environ.get("REPO_NAME")
    pr = pr_number or os.environ.get("PR_NUMBER")
    github_token = token or os.environ.get("GITHUB_TOKEN")

    if not pr or pr in ("None", "null", ""):
        print("⚠️  No PR number — direct push. Printing analysis:")
        print(comment)
        return False

    if not repo:
        print("❌ Cannot post PR comment: REPO_NAME is not set.")
        return False

    url = f"https://api.github.com/repos/{repo}/issues/{pr}/comments"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        response = requests.post(url, headers=headers, json={"body": comment}, timeout=30)
        if response.status_code == 201:
            print(f"✅ Analysis posted to PR #{pr}")
            return True
        else:
            from agent.security import redact_secrets
            clean_text = redact_secrets(response.text, [github_token])
            print(f"❌ Failed to post comment: {response.status_code} — {clean_text}")
            return False
    except requests.RequestException as e:
        from agent.security import redact_secrets
        clean_err = redact_secrets(str(e), [github_token])
        print(f"❌ Network error posting PR comment: {clean_err}")
        return False

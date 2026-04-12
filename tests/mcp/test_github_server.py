"""Unit tests for mcp/github_server.py"""
from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Not implemented yet")
class TestGitHubServer:
    def test_create_pr_returns_url_and_number(self):
        from mcp.github_server import create_pr
        result = create_pr("Fix bug", "body", "fix/bug-123")
        assert "url" in result
        assert "pr_number" in result

    def test_push_branch_returns_sha(self):
        from mcp.github_server import push_branch
        result = push_branch("fix/bug-123", [{"path": "main.py", "content": "# code"}])
        assert "sha" in result

    def test_read_diff_returns_diff_string(self):
        from mcp.github_server import read_diff
        result = read_diff(1)
        assert "diff" in result
        assert isinstance(result["diff"], str)

    def test_get_pr_status_returns_state(self):
        from mcp.github_server import get_pr_status
        result = get_pr_status(1)
        assert "state" in result
        assert result["state"] in ("open", "closed", "merged")

"""
MCP server: GitHub tools.

Tools exposed:
  - create_pr(title, body, head_branch, base_branch) -> {url, pr_number}
  - push_branch(branch_name, files: list[{path, content}]) -> {sha}
  - read_diff(pr_number) -> {diff: str}
  - get_pr_status(pr_number) -> {state, checks_passed, mergeable}

Transport: stdio (local process spawned by Deep Agents MCP adapter)
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("github-server")


@mcp.tool()
def create_pr(title: str, body: str, head_branch: str, base_branch: str = "main") -> dict:
    """Create a GitHub pull request and return its URL and number."""
    raise NotImplementedError


@mcp.tool()
def push_branch(branch_name: str, files: list[dict]) -> dict:
    """Push files to a new or existing branch. files: [{path, content}]."""
    raise NotImplementedError


@mcp.tool()
def read_diff(pr_number: int) -> dict:
    """Read the unified diff for a pull request."""
    raise NotImplementedError


@mcp.tool()
def get_pr_status(pr_number: int) -> dict:
    """Get PR state, CI check results, and mergeability."""
    raise NotImplementedError


if __name__ == "__main__":
    mcp.run(transport="stdio")

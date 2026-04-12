"""
MCP server: web search tools.

Tools exposed:
  - search(query, max_results) -> list[{url, title, snippet}]
  - fetch_page(url) -> {content: str}  (for researcher reading docs)

Transport: stdio
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("web-search-server")


@mcp.tool()
def search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web and return structured results."""
    raise NotImplementedError


@mcp.tool()
def fetch_page(url: str) -> dict:
    """Fetch a web page and return its text content."""
    raise NotImplementedError


if __name__ == "__main__":
    mcp.run(transport="stdio")

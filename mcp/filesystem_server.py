"""
MCP server: skills/ filesystem tools.

Tools exposed:
  - read_skill(name) -> {content: str}
  - write_skill(name, content) -> {path: str}        # create new only
  - append_skill(name, content) -> {path: str}       # append to existing
  - list_skills() -> list[str]

skills/ is append-only during a run — write_skill raises if file exists.
Transport: stdio
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("filesystem-server")


@mcp.tool()
def read_skill(name: str) -> dict:
    """Read a skill document by name (without .md extension)."""
    raise NotImplementedError


@mcp.tool()
def write_skill(name: str, content: str) -> dict:
    """Create a new skill document. Raises if it already exists."""
    raise NotImplementedError


@mcp.tool()
def append_skill(name: str, content: str) -> dict:
    """Append content to an existing skill document."""
    raise NotImplementedError


@mcp.tool()
def list_skills() -> list[str]:
    """List all available skill document names."""
    raise NotImplementedError


if __name__ == "__main__":
    mcp.run(transport="stdio")

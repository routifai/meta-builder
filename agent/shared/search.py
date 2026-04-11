"""
Search capability for the researcher agent.

Strategy:
  1. If TAVILY_API_KEY is set → use Tavily directly (plain Python function,
     passed as a tool to Deep Agents subagents).
  2. If not → fall back to Anthropic's built-in server-side web search
     (web_search_20260209). Requires no extra key but may be blocked by
     some enterprise Anthropic subscriptions.

Usage
-----
    from agent.shared.search import get_search_tool, SEARCH_MODE

    tool_fn = get_search_tool()          # callable, or None if using Anthropic built-in
    tool_defs = get_anthropic_tools()    # list to pass to messages.create(tools=...)
"""
from __future__ import annotations

import os
from typing import Literal

# ---------------------------------------------------------------------------
# Tavily search — primary
# ---------------------------------------------------------------------------

def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web via Tavily and return structured results.

    Returns:
        list of { url, title, content, score }
    """
    from tavily import TavilyClient
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = client.search(query, max_results=max_results)
    return response.get("results", [])


def _tavily_fetch(url: str) -> str:
    """Fetch full page content via Tavily extract."""
    from tavily import TavilyClient
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = client.extract(urls=[url])
    results = response.get("results", [])
    return results[0].get("raw_content", "") if results else ""


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

SearchMode = Literal["tavily", "anthropic_builtin"]


def get_search_mode() -> SearchMode:
    """Return which search backend is active."""
    if os.environ.get("TAVILY_API_KEY"):
        return "tavily"
    return "anthropic_builtin"


SEARCH_MODE: SearchMode = get_search_mode()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_search_tool() -> callable | None:
    """
    Return a plain Python callable to pass as a Deep Agents tool.

    Returns None when the Anthropic built-in should be used instead —
    in that case, add get_anthropic_tools() to your messages.create call.
    """
    if get_search_mode() == "tavily":
        return _tavily_search
    return None


def get_fetch_tool() -> callable | None:
    """
    Return a plain Python callable for fetching a full page by URL.
    Returns None when Anthropic built-in is active (no equivalent).
    """
    if get_search_mode() == "tavily":
        return _tavily_fetch
    return None


def get_anthropic_tools() -> list[dict]:
    """
    Return the Anthropic built-in tool definitions to include in
    messages.create(tools=...) when Tavily is not available.
    """
    if get_search_mode() == "anthropic_builtin":
        return [{"type": "web_search_20260209", "name": "web_search"}]
    return []


def search(query: str, max_results: int = 5) -> list[dict]:
    """
    Convenience function — search using whichever backend is active.
    Only works when called from Python (not inside an agent tool call loop).
    Falls back gracefully when Anthropic built-in is active.
    """
    if get_search_mode() == "tavily":
        return _tavily_search(query, max_results)
    # Anthropic built-in can't be called directly from Python —
    # it must be invoked via the messages API tool loop.
    raise RuntimeError(
        "Direct search() call requires TAVILY_API_KEY. "
        "When using Anthropic built-in search, run the search inside an agent tool loop."
    )

"""
Knowledge gap filler — lets agents request targeted research mid-execution.

When an agent (e.g. coder) needs domain knowledge that is missing or incomplete,
it calls fill_knowledge_gap(). This function:
  1. Checks SkillsStore first — return immediately if the skill already exists.
  2. If missing — runs a targeted single-domain researcher call and writes
     the result to skills_dir before returning the content.

This gives agents a pivot-back capability without requiring orchestrator
coordination. The agent self-heals its own knowledge gaps inline.

Usage (inside an agent's tool loop):
    from agent.shared.knowledge import fill_knowledge_gap

    content = await fill_knowledge_gap(
        domain="fastmcp",
        question="how to register tools and handle arguments",
        intent_spec=spec,
        skills_dir=skills_dir,
        client=client,
    )
"""
from __future__ import annotations

import os

import anthropic

from agent.shared.search import get_search_mode
from agent.shared.state import SkillsStore

# Imported at module level so tests can patch them via agent.shared.knowledge.*
from agent.mesh.researcher import _research_tavily, _research_builtin


async def fill_knowledge_gap(
    domain: str,
    question: str,
    intent_spec: dict,
    skills_dir: str = "skills",
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> str:
    """
    Return skill content for `domain`, researching it on demand if missing.

    Args:
        domain:       Domain slug to look up, e.g. "fastmcp", "perplexity-api".
                      Normalised to lowercase-hyphen format automatically.
        question:     What the caller specifically needs to know. Used to focus
                      the research prompt when the domain is missing.
        intent_spec:  Current run's IntentSpec — provides raw_goal context for
                      the research synthesis prompt.
        skills_dir:   Where skill files are stored (same dir the current run uses).
        client:       Optional AsyncAnthropic client for DI in tests.

    Returns:
        The full text content of the skill doc.

    Raises:
        ValueError: if domain is empty.
    """
    if not domain or not domain.strip():
        raise ValueError("domain must be a non-empty string")

    slug = domain.strip().lower().replace(" ", "-")
    store = SkillsStore(skills_dir)

    # ── 1. Fast path: skill already exists ────────────────────────────
    try:
        content = store.read(slug)
        return content
    except FileNotFoundError:
        pass  # fall through to research

    # ── 2. Slow path: targeted single-domain research ──────────────────
    _client = client or anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    # Enrich the raw_goal with the specific question so synthesis is focused
    raw_goal = intent_spec.get("raw_goal", "")
    focused_goal = f"{raw_goal} — specifically: {question}"

    search_mode = get_search_mode()
    if search_mode == "tavily":
        result = await _research_tavily(slug, focused_goal, _client)
    else:
        result = await _research_builtin(slug, focused_goal, _client)

    # Write to skills store (append if already exists — race condition safety)
    try:
        store.write_new(slug, result["skill_content"])
    except FileExistsError:
        # Another concurrent call already wrote it — just read and return
        return store.read(slug)

    return result["skill_content"]


def get_knowledge_tool_definition() -> dict:
    """
    Return the Anthropic tool definition for fill_knowledge_gap.

    Pass this in tools= when building an agent that should be able to
    request domain knowledge mid-execution.
    """
    return {
        "name": "fill_knowledge_gap",
        "description": (
            "Request technical knowledge about a specific domain when you need "
            "information that is not already in your context. "
            "The system will check existing skill docs first (fast), "
            "then research the topic on demand if missing (slow, ~5s). "
            "Use this when you need API details, code patterns, or best practices "
            "for a library or technology before writing code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": (
                        "Technology or library slug to look up. "
                        "Use lowercase-hyphen format: 'fastmcp', 'perplexity-api', "
                        "'fly-workers', 'postgres', 'httpx'. "
                        "Match an existing skill slug when possible."
                    ),
                },
                "question": {
                    "type": "string",
                    "description": (
                        "What you specifically need to know. "
                        "Be precise: 'how to register tools in FastMCP', "
                        "'Perplexity SDK async client authentication', "
                        "'fly.toml healthcheck configuration for Python'. "
                        "This focuses the research when the skill is missing."
                    ),
                },
            },
            "required": ["domain", "question"],
        },
    }

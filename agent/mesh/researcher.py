"""
Researcher — Block 2, runs concurrently with architect.

Input:  intent_spec: IntentSpec
Output: ResearchResult
  {
    "recommended_stack": dict[str, str],   # domain -> chosen library/tool
    "skills_written": list[str],           # paths to skills/ files created/updated
    "references": list[str],               # URLs consulted
  }

Side effect: writes skill docs to skills/ for each domain in intent.
"""
from __future__ import annotations

import asyncio
import os
from typing import TypedDict

import anthropic

from agent.shared.search import get_search_mode, get_anthropic_tools
from agent.shared.state import SkillsStore


class ResearchResult(TypedDict):
    recommended_stack: dict[str, str]
    skills_written: list[str]
    references: list[str]


# ---------------------------------------------------------------------------
# Domain extraction
# ---------------------------------------------------------------------------

_INTEGRATION_TO_DOMAIN: dict[str, str] = {
    "perplexity": "perplexity-api",
    "openai": "openai-api",
    "github": "github-api",
    "slack": "slack-api",
    "stripe": "stripe-api",
    "postgres": "postgres",
    "redis": "redis-state",
    "anthropic": "anthropic-sdk",
    "fly": "fly-workers",
    "docker": "docker",
}

_BUILD_TARGET_TO_DOMAIN: dict[str, str] = {
    "mcp-server": "mcp-protocol",
    "rest-api": "fastapi",
    "cli-tool": "python-cli",
    "web-app": "fastapi",
    "python-library": "python-library",
    "graphql-api": "graphql",
}

_DEPLOY_TARGET_TO_DOMAIN: dict[str, str] = {
    "fly.io": "fly-workers",
    "aws": "aws",
    "gcp": "gcp",
    "azure": "azure",
    "render": "render",
}


def _extract_domains(
    integrations: list[str],
    build_target: str | None,
    deploy_target: str | None,
) -> list[str]:
    """Map intent fields to researchable domain slugs."""
    domains: list[str] = []

    for integration in integrations:
        slug = _INTEGRATION_TO_DOMAIN.get(integration.lower(), f"{integration.lower()}-api")
        if slug not in domains:
            domains.append(slug)

    if build_target:
        slug = _BUILD_TARGET_TO_DOMAIN.get(build_target.lower())
        if not slug:
            # Unknown build target — use the raw value as a domain slug so it still gets researched
            slug = build_target.lower().replace(" ", "-")
        if slug not in domains:
            domains.append(slug)

    if deploy_target:
        slug = _DEPLOY_TARGET_TO_DOMAIN.get(deploy_target.lower())
        if slug and slug not in domains:
            domains.append(slug)

    return domains or ["python"]


# ---------------------------------------------------------------------------
# Research backends
# ---------------------------------------------------------------------------

async def _research_tavily(domain: str, raw_goal: str, client: anthropic.AsyncAnthropic) -> dict:
    """Search via Tavily, then synthesize a skill doc."""
    from agent.shared.search import _tavily_search

    results = await asyncio.to_thread(
        _tavily_search,
        f"{domain} python best practices official documentation 2024",
        5,
    )
    references = [r.get("url", "") for r in results if r.get("url")]
    context = "\n\n".join(
        f"## {r.get('title', 'Source')}\nURL: {r.get('url', '')}\n{r.get('content', '')}"
        for r in results
    )
    return await _synthesize(domain, raw_goal, context, references, client)


async def _research_builtin(domain: str, raw_goal: str, client: anthropic.AsyncAnthropic) -> dict:
    """Use Anthropic built-in web_search tool, then synthesize a skill doc."""
    search_tools = get_anthropic_tools()
    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"Search for best practices, official documentation, and recommended Python libraries "
                f"for '{domain}' when building: {raw_goal}. "
                f"Provide a summary including URLs."
            ),
        }
    ]

    context_parts: list[str] = []
    max_turns = 6
    model = os.environ.get("RESEARCHER_MODEL", "claude-haiku-4-5-20251001")

    for _ in range(max_turns):
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            tools=search_tools,
            messages=messages,
        )

        for block in response.content:
            if hasattr(block, "text") and block.text:
                context_parts.append(block.text)

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "",
                }
                for block in response.content
                if block.type == "tool_use"
            ]
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
        else:
            break

    context = "\n\n".join(context_parts) or f"Research on {domain}"
    return await _synthesize(domain, raw_goal, context, [], client)


# ---------------------------------------------------------------------------
# Skill synthesis
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = (
    "You are a technical documentation writer for an autonomous software delivery system. "
    "Write concise, accurate skill documents that capture key facts, API patterns, and gotchas. "
    "Be specific — include import statements and short code snippets where useful."
)


async def _synthesize(
    domain: str,
    raw_goal: str,
    context: str,
    references: list[str],
    client: anthropic.AsyncAnthropic,
) -> dict:
    """Ask the model to synthesize a skill document from gathered context."""
    model = os.environ.get("RESEARCHER_MODEL", "claude-haiku-4-5-20251001")

    response = await client.messages.create(
        model=model,
        max_tokens=1500,
        system=_SYNTHESIS_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a skill document for the domain '{domain}' "
                    f"to help build: {raw_goal}\n\n"
                    f"Research context:\n{context}\n\n"
                    f"Format the document exactly as:\n"
                    f"# {domain}\n\n"
                    f"## Overview\n[2-3 sentences]\n\n"
                    f"## Recommended library / tool\n[name and one-line reason]\n\n"
                    f"## Key patterns\n[3-5 bullet points with code snippets]\n\n"
                    f"## Gotchas\n[1-3 common mistakes]\n\n"
                    f"End with a final line: `recommended_tool: <tool-or-library-name>`"
                ),
            }
        ],
    )

    content = response.content[0].text if response.content else f"# {domain}\n\nNo content generated."

    # Parse recommended_tool from the last line
    recommended_tool = domain
    for line in reversed(content.splitlines()):
        line = line.strip()
        if line.startswith("recommended_tool:"):
            recommended_tool = line.split(":", 1)[1].strip()
            break

    return {
        "skill_content": content,
        "recommended_tool": recommended_tool,
        "references": references,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run(
    intent_spec: dict,
    *,
    client: anthropic.AsyncAnthropic | None = None,
    skills_dir: str = "skills",
) -> ResearchResult:
    """Research domains, write skill docs, return stack recommendations."""
    if not intent_spec:
        raise ValueError("intent_spec is empty")

    # Raises KeyError on missing required field — surfaces to caller as expected
    raw_goal: str = intent_spec["raw_goal"]

    integrations: list[str] = intent_spec.get("integrations", [])
    build_target: str | None = intent_spec.get("build_target")
    deploy_target: str | None = intent_spec.get("deploy_target")

    _client = client or anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    domains = _extract_domains(integrations, build_target, deploy_target)
    store = SkillsStore(skills_dir)
    search_mode = get_search_mode()

    recommended_stack: dict[str, str] = {}
    skills_written: list[str] = []
    all_references: list[str] = []

    # Research all domains concurrently — each is an independent API call
    research_fn = _research_tavily if search_mode == "tavily" else _research_builtin
    domain_results = await asyncio.gather(
        *[research_fn(domain, raw_goal, _client) for domain in domains]
    )

    # Write results to the skills store sequentially (filesystem, not thread-safe)
    for domain, result in zip(domains, domain_results):
        try:
            store.write_new(domain, result["skill_content"])
        except FileExistsError:
            store.append(domain, f"\n\n---\n## Researcher update\n\n{result['skill_content']}")

        skills_written.append(f"skills/{domain}.md")
        recommended_stack[domain] = result["recommended_tool"]
        all_references.extend(result["references"])

    return ResearchResult(
        recommended_stack=recommended_stack,
        skills_written=skills_written,
        references=all_references,
    )

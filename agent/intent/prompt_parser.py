"""
Prompt parser — Block 1, Agent 1.

Uses the Anthropic SDK with tool use to extract structured entities from
a raw one-sentence goal string.

Input:  raw_goal: str
Output: ParsedGoal dict
  {
    "raw_goal": str,
    "domains": list[str],
    "entities": {
        "build_target": str | None,
        "integrations": list[str],
        "deploy_target": str | None,
    },
    "unknown_fields": list[str],
  }
"""
from __future__ import annotations

import json
import os
from typing import TypedDict

import anthropic

# ---------------------------------------------------------------------------
# Domain keyword map — used as context in the extraction prompt so the LLM
# produces consistent domain tags that match skills/ filenames.
# ---------------------------------------------------------------------------
KNOWN_DOMAINS = [
    "mcp-protocol",
    "anthropic-sdk",
    "deep-agents",
    "redis-state",
    "github-actions",
    "fly-workers",
    "perplexity-api",
    "openai-api",
    "github-api",
    "slack-api",
    "stripe-api",
    "postgres",
    "sqlite",
    "fastapi",
    "flask",
    "docker",
    "aws",
    "gcp",
    "azure",
    "rest-api",
    "graphql",
    "websocket",
]

# ---------------------------------------------------------------------------
# Tool schema — structured extraction via tool use
# ---------------------------------------------------------------------------
EXTRACT_TOOL = {
    "name": "extract_goal_entities",
    "description": (
        "Extract structured information from a software goal string. "
        "Identify the thing being built, integrations, deployment target, "
        "and which technical domains are relevant."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "build_target": {
                "type": ["string", "null"],
                "description": (
                    "What is being built: e.g. 'mcp-server', 'rest-api', "
                    "'cli-tool', 'python-library', 'web-app'. null if not determinable."
                ),
            },
            "integrations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "External services, APIs, or databases mentioned: "
                    "e.g. ['perplexity', 'github', 'stripe', 'postgres']. "
                    "Use lowercase, short names."
                ),
            },
            "deploy_target": {
                "type": ["string", "null"],
                "description": (
                    "Where it will be deployed: e.g. 'fly.io', 'aws', 'render', "
                    "'local', 'vercel'. 'prod' maps to null (no specific platform given). "
                    "null if no deployment is mentioned."
                ),
            },
            "domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    f"Technical domain tags relevant to this goal. "
                    f"Use from this list when applicable: {KNOWN_DOMAINS}. "
                    "Add new tags (lowercase-hyphenated) for domains not in the list."
                ),
            },
            "unknown_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Fields that could not be determined from the goal string. "
                    "List field names: 'build_target', 'deploy_target', 'integrations'."
                ),
            },
        },
        "required": [
            "build_target",
            "integrations",
            "deploy_target",
            "domains",
            "unknown_fields",
        ],
    },
}

SYSTEM_PROMPT = (
    "You are a goal parser for an autonomous software delivery system. "
    "Given a one-sentence software goal, extract structured entities. "
    "Be precise and minimal — only extract what is explicitly stated or strongly implied. "
    "Do not hallucinate integrations or deploy targets that are not mentioned."
)


class ParsedGoal(TypedDict):
    raw_goal: str
    domains: list[str]
    entities: dict[str, object]
    unknown_fields: list[str]


def parse_prompt(
    raw_goal: str,
    *,
    client: anthropic.Anthropic | None = None,
    model: str | None = None,
) -> ParsedGoal:
    """
    Extract domains and entities from a raw one-sentence goal string.

    Args:
        raw_goal:  The human's goal, e.g. "build an MCP server for Perplexity search"
        client:    Optional pre-built Anthropic client (for testing / dependency injection)
        model:     Model override. Defaults to PARSER_MODEL env var or claude-haiku-4-5-20251001.

    Raises:
        ValueError: if raw_goal is empty or whitespace-only
        anthropic.APIError: on API failures (propagated to caller)
    """
    if not raw_goal or not raw_goal.strip():
        raise ValueError("raw_goal must be a non-empty string")

    _client = client or anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )
    _model = model or os.environ.get("PARSER_MODEL", "claude-haiku-4-5-20251001")

    response = _client.messages.create(
        model=_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_goal_entities"},
        messages=[{"role": "user", "content": raw_goal}],
    )

    # The model is forced to call the tool — find the tool_use block
    tool_block = next(
        (b for b in response.content if b.type == "tool_use"),
        None,
    )
    if tool_block is None:
        raise RuntimeError(
            f"Model did not call extract_goal_entities tool. "
            f"Response: {response.content}"
        )

    extracted: dict = tool_block.input

    return ParsedGoal(
        raw_goal=raw_goal,
        domains=extracted.get("domains", []),
        entities={
            "build_target": extracted.get("build_target"),
            "integrations": extracted.get("integrations", []),
            "deploy_target": extracted.get("deploy_target"),
        },
        unknown_fields=extracted.get("unknown_fields", []),
    )

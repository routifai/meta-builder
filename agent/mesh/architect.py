"""
Architect — Block 2, runs concurrently with researcher.

Input:  intent_spec: IntentSpec, research_result: ResearchResult
Output: ArchitectureSpec
  {
    "file_tree":         list[str],           # relative paths of all files to create
    "module_interfaces": dict[str, dict],     # module -> { input: {...}, output: {...} }
    "dependencies":      dict[str, list[str]],# module -> list of modules it depends on
    "tech_choices":      dict[str, str],      # component -> chosen technology/library
  }
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

import anthropic


class ArchitectureSpec(TypedDict):
    file_tree: list[str]
    module_interfaces: dict[str, dict]
    dependencies: dict[str, list[str]]
    tech_choices: dict[str, str]


# ---------------------------------------------------------------------------
# Tool schema — forces structured architecture output
# ---------------------------------------------------------------------------

_ARCHITECT_TOOL = {
    "name": "define_architecture",
    "description": (
        "Define the complete software architecture for the project: "
        "file layout, module contracts, dependency graph, and tech choices."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_tree": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "All source files to create, as relative paths. "
                    "e.g. ['src/main.py', 'src/server.py', 'tests/test_server.py', "
                    "'Dockerfile', 'fly.toml', 'requirements.txt']"
                ),
            },
            "module_interfaces": {
                "type": "object",
                "description": (
                    "For each logical module, define its input and output shape. "
                    "Keys are module names (e.g. 'search_handler', 'mcp_server'). "
                    "Values are objects with 'input' and/or 'output' keys describing the contract."
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "object",
                            "description": "Expected input parameters as field-name: type pairs",
                        },
                        "output": {
                            "type": "object",
                            "description": "Return value shape as field-name: type pairs",
                        },
                        "description": {
                            "type": "string",
                            "description": "One-line description of what this module does",
                        },
                    },
                },
            },
            "dependencies": {
                "type": "object",
                "description": (
                    "For each module, the list of other modules it imports or depends on. "
                    "Keys match the keys in module_interfaces."
                ),
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "tech_choices": {
                "type": "object",
                "description": (
                    "For each architectural component, the chosen library or technology. "
                    "e.g. {'web_framework': 'fastapi', 'mcp_layer': 'fastmcp', "
                    "'search_client': 'openai', 'deployment': 'fly.io'}"
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["file_tree", "module_interfaces", "dependencies", "tech_choices"],
    },
}

_SYSTEM_PROMPT = (
    "You are a senior software architect for an autonomous software delivery system. "
    "Given an intent spec and research notes, produce a precise, minimal architecture. "
    "File trees should be small and focused — include only what is needed. "
    "Module interfaces should use concrete Python type names (str, dict, list[str], etc.). "
    "Tech choices must match the recommended_stack from the research phase."
)


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def _load_skill_docs(skills_written: list[str], skills_dir: str) -> str:
    """Load relevant skill docs to give the architect domain context."""
    parts: list[str] = []
    base = Path(skills_dir)
    for rel_path in skills_written:
        name = Path(rel_path).name
        candidate = base / name
        if candidate.exists():
            parts.append(f"### {name}\n{candidate.read_text()}")
    return "\n\n---\n\n".join(parts) if parts else ""


def _build_prompt(intent_spec: dict, research_result: dict, skill_docs: str) -> str:
    raw_goal = intent_spec["raw_goal"]
    build_target = intent_spec.get("build_target", "unknown")
    deploy_target = intent_spec.get("deploy_target", "unknown")
    integrations = intent_spec.get("integrations", [])
    recommended_stack = research_result.get("recommended_stack", {})

    stack_lines = "\n".join(f"  - {domain}: {tool}" for domain, tool in recommended_stack.items())

    prompt = (
        f"Goal: {raw_goal}\n"
        f"Build target: {build_target}\n"
        f"Deploy target: {deploy_target}\n"
        f"Integrations: {', '.join(integrations) or 'none'}\n\n"
        f"Recommended stack from research:\n{stack_lines or '  (none)'}\n"
    )

    if skill_docs:
        prompt += f"\nSkill docs for context:\n{skill_docs}\n"

    prompt += (
        "\nCall define_architecture with a concrete, minimal architecture for this project. "
        "Keep the file_tree to the essential files only. "
        "Every module in module_interfaces must have at least one of: input, output."
    )
    return prompt


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run(
    intent_spec: dict,
    research_result: dict,
    *,
    client: anthropic.AsyncAnthropic | None = None,
    skills_dir: str = "skills",
) -> ArchitectureSpec:
    """Produce file tree and module interface contracts from intent + research."""
    if not intent_spec:
        raise ValueError("intent_spec is empty")

    # Validate required field — raises KeyError if missing
    raw_goal: str = intent_spec["raw_goal"]  # noqa: F841

    _client = client or anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )
    model = os.environ.get("ARCHITECT_MODEL", "claude-haiku-4-5-20251001")

    skills_written: list[str] = research_result.get("skills_written", [])
    skill_docs = _load_skill_docs(skills_written, skills_dir)
    prompt = _build_prompt(intent_spec, research_result, skill_docs)

    response = await _client.messages.create(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        tools=[_ARCHITECT_TOOL],
        tool_choice={"type": "tool", "name": "define_architecture"},
        messages=[{"role": "user", "content": prompt}],
    )

    tool_block = next(
        (b for b in response.content if b.type == "tool_use"),
        None,
    )
    if tool_block is None:
        raise RuntimeError(
            f"Model did not call define_architecture. Response: {response.content}"
        )

    extracted: dict = tool_block.input

    return ArchitectureSpec(
        file_tree=extracted.get("file_tree", []),
        module_interfaces=extracted.get("module_interfaces", {}),
        dependencies=extracted.get("dependencies", {}),
        tech_choices=extracted.get("tech_choices", {}),
    )

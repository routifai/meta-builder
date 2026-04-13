"""
Planner — runs after architect, before coder.

Input:  architecture_spec: ArchitectureSpec, intent_spec: IntentSpec
Output: PlanSpec
  {
    "file_plans": {
      "<relative_path>": {
        "description":  str,          # one-line purpose of this file
        "imports":      list[str],    # exact import lines the file should start with
        "constants":    list[str],    # module-level constants, e.g. "PORT = 8080"
        "classes":      list[{        # classes to define
          "name":       str,
          "bases":      list[str],
          "docstring":  str,
          "methods":    list[{"name": str, "signature": str, "docstring": str}]
        }],
        "functions":    list[{        # top-level functions to define
          "name":       str,
          "signature":  str,
          "docstring":  str
        }],
        "notes":        str,          # structural notes: "entry point", "expose POST /search", etc.
      }
    },
    "entry_point":    str,            # which file to run (e.g. "src/server.py")
    "test_strategy":  str,            # brief description of how tests should be structured
  }

The Planner bridges the gap between the Architect (what files exist, what they export)
and the Coder (what to write inside each file). The Coder receives this spec and just
fills in function bodies — no structural decisions required.
"""
from __future__ import annotations

import os
from typing import TypedDict

import anthropic


class MethodPlan(TypedDict):
    name: str
    signature: str
    docstring: str


class ClassPlan(TypedDict):
    name: str
    bases: list[str]
    docstring: str
    methods: list[MethodPlan]


class FunctionPlan(TypedDict):
    name: str
    signature: str
    docstring: str


class FilePlan(TypedDict):
    description: str
    imports: list[str]
    constants: list[str]
    classes: list[ClassPlan]
    functions: list[FunctionPlan]
    notes: str


class PlanSpec(TypedDict):
    file_plans: dict[str, FilePlan]
    entry_point: str
    test_strategy: str


# ---------------------------------------------------------------------------
# Tool schema — forces structured per-file blueprint output
# ---------------------------------------------------------------------------

_PLANNER_TOOL = {
    "name": "define_file_plans",
    "description": (
        "For each file in the architecture, define its exact contents: "
        "what imports, constants, classes, and functions it contains, "
        "with signatures and one-line docstrings. "
        "Also identify the entry point and testing strategy."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_plans": {
                "type": "object",
                "description": (
                    "Keys are relative file paths from the architecture's file_tree. "
                    "Values are per-file blueprints."
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "One-line purpose of this file",
                        },
                        "imports": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Exact import lines the file needs. "
                                "e.g. ['import os', 'from fastapi import FastAPI', "
                                "'from .models import SearchResult']"
                            ),
                        },
                        "constants": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Module-level constants as assignment strings. "
                                "e.g. ['PORT = 8080', 'DEFAULT_TIMEOUT = 30']"
                            ),
                        },
                        "classes": {
                            "type": "array",
                            "description": "Classes to define in this file",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "bases": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Base class names",
                                    },
                                    "docstring": {"type": "string"},
                                    "methods": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "signature": {
                                                    "type": "string",
                                                    "description": (
                                                        "Full signature including self and type hints. "
                                                        "e.g. 'def search(self, query: str) -> SearchResult'"
                                                    ),
                                                },
                                                "docstring": {"type": "string"},
                                            },
                                            "required": ["name", "signature", "docstring"],
                                        },
                                    },
                                },
                                "required": ["name", "bases", "docstring", "methods"],
                            },
                        },
                        "functions": {
                            "type": "array",
                            "description": "Top-level functions to define in this file",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "signature": {
                                        "type": "string",
                                        "description": (
                                            "Full signature with type hints. "
                                            "e.g. 'async def handle_search(request: SearchRequest) -> SearchResponse'"
                                        ),
                                    },
                                    "docstring": {"type": "string"},
                                },
                                "required": ["name", "signature", "docstring"],
                            },
                        },
                        "notes": {
                            "type": "string",
                            "description": (
                                "Structural notes for the coder. "
                                "e.g. 'Entry point — call uvicorn.run here', "
                                "'Expose POST /search route', "
                                "'Must export SearchResult for other modules to import'"
                            ),
                        },
                    },
                    "required": ["description", "imports", "constants", "classes", "functions", "notes"],
                },
            },
            "entry_point": {
                "type": "string",
                "description": (
                    "The file that starts the application. "
                    "e.g. 'src/main.py' or 'src/server.py'"
                ),
            },
            "test_strategy": {
                "type": "string",
                "description": (
                    "How tests should be structured. "
                    "e.g. 'Unit test each handler in isolation with mocked clients; "
                    "integration test the full search flow end-to-end.'"
                ),
            },
        },
        "required": ["file_plans", "entry_point", "test_strategy"],
    },
}

_SYSTEM_PROMPT = (
    "You are a senior software engineer producing precise implementation blueprints. "
    "Given an architecture spec (file tree, module interfaces, tech choices), "
    "plan the exact contents of every file: what imports, classes, and functions it contains, "
    "with precise Python signatures and one-line docstrings. "
    "Do not write implementation bodies — only signatures and docstrings. "
    "Ensure every file in the file_tree is covered. "
    "Ensure __init__.py files export the right symbols. "
    "Ensure test files have test functions for each public function/method. "
    "Keep each file focused and minimal — split responsibilities cleanly across files."
)


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def _build_prompt(intent_spec: dict, architecture_spec: dict) -> str:
    raw_goal = intent_spec.get("raw_goal", "")
    build_target = intent_spec.get("build_target", "unknown")
    deploy_target = intent_spec.get("deploy_target", "unknown")

    file_tree = architecture_spec.get("file_tree", [])
    module_interfaces = architecture_spec.get("module_interfaces", {})
    tech_choices = architecture_spec.get("tech_choices", {})
    dependencies = architecture_spec.get("dependencies", {})

    file_list = "\n".join(f"  - {f}" for f in file_tree)
    tech_list = "\n".join(f"  - {k}: {v}" for k, v in tech_choices.items())

    iface_lines: list[str] = []
    for module, contract in module_interfaces.items():
        iface_lines.append(f"  {module}:")
        if "description" in contract:
            iface_lines.append(f"    description: {contract['description']}")
        if "input" in contract:
            iface_lines.append(f"    input:  {contract['input']}")
        if "output" in contract:
            iface_lines.append(f"    output: {contract['output']}")

    dep_lines: list[str] = []
    for module, deps in dependencies.items():
        if deps:
            dep_lines.append(f"  {module} → {', '.join(deps)}")

    prompt = (
        f"Goal: {raw_goal}\n"
        f"Build target: {build_target}\n"
        f"Deploy target: {deploy_target}\n\n"
        f"Files to plan:\n{file_list}\n\n"
        f"Tech choices:\n{tech_list or '  (none)'}\n\n"
        f"Module interfaces:\n{chr(10).join(iface_lines) or '  (none)'}\n\n"
    )

    if dep_lines:
        prompt += f"Module dependencies:\n{chr(10).join(dep_lines)}\n\n"

    prompt += (
        "Call define_file_plans with a complete per-file blueprint. "
        "Every file in the file list above must appear in file_plans. "
        "Include all necessary imports for the tech choices listed. "
        "For test files, include one test function per public function/method being tested."
    )
    return prompt


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run(
    intent_spec: dict,
    architecture_spec: dict,
    *,
    client: anthropic.AsyncAnthropic | None = None,
    revision_note: str = "",
) -> PlanSpec:
    """
    Produce per-file implementation blueprints from intent + architecture spec.

    revision_note: if non-empty, appended to the prompt so the planner knows what
    went wrong in the previous plan and can adjust responsibilities / simplify.
    """
    if not intent_spec:
        raise ValueError("intent_spec is empty")
    if not architecture_spec:
        raise ValueError("architecture_spec is empty")

    _ = intent_spec["raw_goal"]  # validate required field

    file_tree = architecture_spec.get("file_tree", [])
    if not file_tree:
        raise ValueError("architecture_spec.file_tree is empty — nothing to plan")

    _client = client or anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )
    model = os.environ.get("PLANNER_MODEL", "claude-haiku-4-5-20251001")

    prompt = _build_prompt(intent_spec, architecture_spec)
    if revision_note:
        prompt += f"\n\n---\nRevision note (from previous failed plan):\n{revision_note}\n"

    # Retry up to 3 times if file_plans comes back empty — haiku sometimes
    # returns {} for deeply-nested additionalProperties schemas.
    for attempt in range(3):
        retry_prompt = prompt
        if attempt > 0:
            retry_prompt += (
                f"\n\nIMPORTANT: Previous attempt returned empty file_plans. "
                f"You MUST populate file_plans with entries for ALL {len(file_tree)} files: "
                f"{file_tree}. Do not return an empty object."
            )

        response = await _client.messages.create(
            model=model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            tools=[_PLANNER_TOOL],
            tool_choice={"type": "tool", "name": "define_file_plans"},
            messages=[{"role": "user", "content": retry_prompt}],
        )

        tool_block = next(
            (b for b in response.content if b.type == "tool_use"),
            None,
        )
        if tool_block is None:
            raise RuntimeError(
                f"Model did not call define_file_plans. Response: {response.content}"
            )

        extracted: dict = tool_block.input

        # The model occasionally serializes file_plans as a JSON string rather than
        # a nested object — parse it defensively.
        raw_file_plans = extracted.get("file_plans", {})
        if isinstance(raw_file_plans, str):
            import json as _json
            try:
                raw_file_plans = _json.loads(raw_file_plans)
            except Exception:
                raw_file_plans = {}

        if raw_file_plans:  # non-empty — good
            break

    return PlanSpec(
        file_plans=raw_file_plans,
        entry_point=extracted.get("entry_point", ""),
        test_strategy=extracted.get("test_strategy", ""),
    )

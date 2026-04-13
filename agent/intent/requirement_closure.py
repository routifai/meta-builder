"""
Requirement Closure — ensures all operational parameters are known before planning.

The system must NEVER start planning with incomplete specs. If a user says
"build a deepsearch MCP" but doesn't specify which provider, token limits, or
transport protocol — the planner will make silent assumptions and produce
wrong infrastructure.

This agent:
  1. Identifies the build_target-specific required fields.
  2. Checks which are missing or ambiguous in the current IntentSpec.
  3. Either auto-fills safe defaults (low-risk), suggests values for the user
     to confirm (medium-risk), or blocks with specific questions (high-risk).

Output:
  {
    "status":            "complete" | "needs_input" | "blocked",
    "missing_fields":    list[str],
    "auto_filled":       dict[str, any],   # fields filled with safe defaults
    "questions":         list[str],        # for needs_input: what to ask
    "blocked_reason":    str,              # for blocked: why we can't proceed
    "final_spec":        dict,             # updated IntentSpec with filled fields
  }

Domain templates define what's required per build_target. Unknown targets
get a minimal check (raw_goal + deploy_target are sufficient to proceed).

Decision logic:
  - All required fields known → status="complete"
  - Some fields missing, all have safe defaults → auto-fill → status="complete"
  - Some fields missing, critical ones have no safe default → status="needs_input"
  - Missing fields make the goal fundamentally ambiguous → status="blocked"
"""
from __future__ import annotations

import os
from typing import Any, Literal, TypedDict

import anthropic

MODEL = os.environ.get("CLOSURE_MODEL", "claude-haiku-4-5-20251001")


# ── Domain requirement templates ──────────────────────────────────────────────
# Each entry: field_name → {"description", "required": bool, "default": any|None,
#                            "options": list|None}
# required=True + default=None → must ask user
# required=True + default=X    → auto-fill with X
# required=False               → optional, skip if absent

_TEMPLATES: dict[str, dict[str, dict]] = {
    "mcp_server": {
        "transport": {
            "description": "MCP transport protocol",
            "required": True,
            "default": "stdio",
            "options": ["stdio", "sse", "websocket"],
        },
        "auth_method": {
            "description": "Authentication method",
            "required": True,
            "default": "api_key",
            "options": ["api_key", "oauth2", "none"],
        },
        "max_output_tokens": {
            "description": "Maximum tokens in tool response",
            "required": True,
            "default": 4096,
            "options": None,
        },
        "rate_limit_rpm": {
            "description": "Requests per minute limit",
            "required": False,
            "default": 60,
            "options": None,
        },
    },
    "web_app": {
        "framework": {
            "description": "Web framework",
            "required": True,
            "default": None,   # must ask — too many options with no safe default
            "options": ["fastapi", "flask", "django", "express", "nextjs"],
        },
        "database": {
            "description": "Database engine",
            "required": True,
            "default": "postgres",
            "options": ["postgres", "sqlite", "mysql", "mongodb", "none"],
        },
        "auth_method": {
            "description": "Authentication method",
            "required": True,
            "default": "jwt",
            "options": ["jwt", "session", "oauth2", "none"],
        },
    },
    "api": {
        "framework": {
            "description": "API framework",
            "required": True,
            "default": "fastapi",
            "options": ["fastapi", "flask", "express", "gin", "rails"],
        },
        "database": {
            "description": "Database engine",
            "required": False,
            "default": "postgres",
            "options": None,
        },
        "auth_method": {
            "description": "Authentication method",
            "required": True,
            "default": "api_key",
            "options": ["api_key", "jwt", "oauth2", "none"],
        },
    },
    "cli_tool": {
        "language": {
            "description": "Implementation language",
            "required": True,
            "default": "python",
            "options": ["python", "go", "rust", "node"],
        },
        "config_format": {
            "description": "Configuration file format",
            "required": False,
            "default": "toml",
            "options": ["toml", "yaml", "json", "env"],
        },
    },
    "ai_agent": {
        "llm_provider": {
            "description": "LLM provider for the agent",
            "required": True,
            "default": "anthropic",
            "options": ["anthropic", "openai", "google", "local"],
        },
        "memory_backend": {
            "description": "Agent memory / state storage",
            "required": True,
            "default": "in_memory",
            "options": ["in_memory", "redis", "postgres", "file"],
        },
        "max_iterations": {
            "description": "Max agent loop iterations",
            "required": True,
            "default": 10,
            "options": None,
        },
    },
    "data_pipeline": {
        "source_format": {
            "description": "Input data format",
            "required": True,
            "default": None,   # must ask
            "options": ["csv", "json", "parquet", "api", "database"],
        },
        "output_format": {
            "description": "Output data format",
            "required": True,
            "default": None,   # must ask
            "options": ["csv", "json", "parquet", "database", "api"],
        },
        "schedule": {
            "description": "Pipeline execution schedule",
            "required": False,
            "default": "on_demand",
            "options": None,
        },
    },
}

# Fields always required regardless of build_target
_UNIVERSAL_REQUIRED = {
    "deploy_target": {
        "description": "Where to deploy the application",
        "required": True,
        "default": "fly.io",
        "options": ["fly.io", "aws", "gcp", "azure", "local", "docker"],
    },
}


# ── Types ─────────────────────────────────────────────────────────────────────

class ClosureResult(TypedDict):
    status: Literal["complete", "needs_input", "blocked"]
    missing_fields: list[str]
    auto_filled: dict[str, Any]
    questions: list[str]
    blocked_reason: str
    final_spec: dict


# ── Core logic ────────────────────────────────────────────────────────────────

def _get_template(build_target: str) -> dict[str, dict]:
    """Return the requirement template for the given build_target, or minimal fallback."""
    # Normalize: "mcp server" → "mcp_server", "web app" → "web_app"
    normalized = build_target.lower().replace(" ", "_").replace("-", "_")

    # Exact match first
    if normalized in _TEMPLATES:
        return _TEMPLATES[normalized]

    # Partial match — "deepsearch_mcp" → "mcp_server"
    # Check substring match first, then segment-level overlap ("mcp" in "deepsearch_mcp")
    for key in _TEMPLATES:
        if key in normalized or normalized in key:
            return _TEMPLATES[key]
    for key in _TEMPLATES:
        key_parts = set(key.split("_"))
        target_parts = set(normalized.split("_"))
        if key_parts & target_parts:
            return _TEMPLATES[key]

    # No match — minimal template (only universal fields required)
    return {}


def close(intent_spec: dict) -> ClosureResult:
    """
    Check requirement completeness and fill safe defaults.

    This is a pure function (no LLM calls) — deterministic and fast.
    The LLM-based version (evaluate_with_llm) is used for ambiguous cases.

    Args:
        intent_spec: Current IntentSpec from defaults_agent.

    Returns:
        ClosureResult with status, auto_filled fields, and questions if needed.
    """
    build_target = intent_spec.get("build_target", "") or ""
    template = _get_template(build_target)

    # Merge universal + domain-specific requirements
    all_requirements = {**_UNIVERSAL_REQUIRED, **template}

    missing_fields: list[str] = []
    auto_filled: dict[str, Any] = {}
    questions: list[str] = []
    updated_spec = dict(intent_spec)

    for field_name, field_def in all_requirements.items():
        if not field_def.get("required", False):
            # Optional — auto-fill if missing and default exists
            if field_name not in intent_spec and field_def.get("default") is not None:
                auto_filled[field_name] = field_def["default"]
                updated_spec[field_name] = field_def["default"]
            continue

        current_value = intent_spec.get(field_name)

        # Field is present and non-empty → satisfied
        if current_value is not None and current_value != "":
            continue

        # Field is missing — try to auto-fill
        default = field_def.get("default")
        if default is not None:
            auto_filled[field_name] = default
            updated_spec[field_name] = default
            continue

        # Missing with no safe default → must ask
        missing_fields.append(field_name)
        options_str = ""
        if field_def.get("options"):
            options_str = f" (options: {', '.join(str(o) for o in field_def['options'])})"
        questions.append(
            f"What {field_def['description']} do you want?{options_str}"
        )

    # Determine status
    if missing_fields:
        # Check if any missing field is truly critical (no way to infer)
        status: Literal["complete", "needs_input", "blocked"] = "needs_input"
    else:
        status = "complete"

    return ClosureResult(
        status=status,
        missing_fields=missing_fields,
        auto_filled=auto_filled,
        questions=questions,
        blocked_reason="",
        final_spec=updated_spec,
    )


async def evaluate(
    intent_spec: dict,
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> ClosureResult:
    """
    Full requirement closure using both template checks and LLM analysis.

    The LLM step is used to catch domain-specific requirements not covered
    by the static templates (e.g. a "deepsearch MCP" needs to know which
    search provider API key to use).

    Returns the same ClosureResult as close() but with richer missing_fields
    and auto_filled sets discovered by the LLM.
    """
    # Fast path: run template-based check first
    template_result = close(intent_spec)

    # If template already has questions, return immediately (don't burn tokens)
    if template_result["status"] == "needs_input":
        return template_result

    # LLM enrichment for domain-specific gaps
    _client = client or anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    tool = {
        "name": "assess_requirements",
        "description": (
            "Identify missing operational parameters for this build goal. "
            "Only flag fields that are truly required to write correct code — "
            "not nice-to-haves."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "additional_missing": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "description": {"type": "string"},
                            "safe_default": {
                                "type": "string",
                                "description": "A safe default value, or empty string if none exists",
                            },
                            "question": {
                                "type": "string",
                                "description": "Question to ask the user if no safe default",
                            },
                        },
                        "required": ["field", "description", "safe_default", "question"],
                    },
                    "description": (
                        "Fields missing from the spec that are critical for implementation. "
                        "Do NOT include fields already present in the spec. "
                        "Be conservative — only flag genuinely required fields."
                    ),
                },
                "assessment": {
                    "type": "string",
                    "description": "Brief explanation of what's sufficient vs what's missing",
                },
            },
            "required": ["additional_missing", "assessment"],
        },
    }

    spec_summary = "\n".join(
        f"  {k}: {v}" for k, v in intent_spec.items() if v not in (None, "", [])
    )

    prompt = (
        f"Goal: {intent_spec.get('raw_goal', '')}\n"
        f"Build target: {intent_spec.get('build_target', '')}\n\n"
        f"Current spec fields:\n{spec_summary}\n\n"
        "Identify any critical missing operational parameters needed to write "
        "correct code for this goal. Only flag parameters that would cause wrong "
        "or broken code if assumed incorrectly."
    )

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=(
            "You are a requirements analyst for a software build system. "
            "Identify missing critical parameters that would cause incorrect code "
            "if assumed. Be conservative — don't ask for things that have safe universal defaults."
        ),
        tools=[tool],
        tool_choice={"type": "tool", "name": "assess_requirements"},
        messages=[{"role": "user", "content": prompt}],
    )

    tool_block = next(
        (b for b in response.content if b.type == "tool_use"), None
    )

    if tool_block is None:
        return template_result  # fallback to template result

    data = tool_block.input
    additional = data.get("additional_missing", [])

    updated_spec = dict(template_result["final_spec"])
    additional_missing: list[str] = []
    additional_auto_filled: dict[str, Any] = {}
    additional_questions: list[str] = []

    for item in additional:
        field = item.get("field", "")
        default = item.get("safe_default", "").strip()
        question = item.get("question", "")

        if field in updated_spec and updated_spec[field] not in (None, ""):
            continue  # already present

        if default:
            additional_auto_filled[field] = default
            updated_spec[field] = default
        else:
            additional_missing.append(field)
            if question:
                additional_questions.append(question)

    all_missing = template_result["missing_fields"] + additional_missing
    all_auto = {**template_result["auto_filled"], **additional_auto_filled}
    all_questions = template_result["questions"] + additional_questions

    final_status: Literal["complete", "needs_input", "blocked"]
    if all_missing:
        final_status = "needs_input"
    else:
        final_status = "complete"

    return ClosureResult(
        status=final_status,
        missing_fields=all_missing,
        auto_filled=all_auto,
        questions=all_questions,
        blocked_reason="",
        final_spec=updated_spec,
    )

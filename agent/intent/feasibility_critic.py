"""
Feasibility Critic — runs immediately after the intent block.

Checks the goal against reality BEFORE any research, planning, or code generation.
Agents should refuse to build things that are impossible, undefined, or out of scope
for a software-only system.

This is NOT a QA agent. It is a reality constraint enforcer:
  - "send apple to Mars" → block (physically impossible for software)
  - "build Uber in 5 minutes" → refine (scope too large, time constraint invalid)
  - "build a todo app" → proceed

Output:
  {
    "decision":    "proceed" | "refine" | "block",
    "confidence":  float,          # 0.0–1.0 (critic's confidence in its decision)
    "issues": [
      {"type": str, "message": str, "severity": "critical" | "warning"}
    ],
    "refined_goal": str | None,    # rewritten goal if decision == "refine"
    "suggestions":  list[str],     # alternatives if decision == "block"
    "reasoning":    str,           # short explanation
  }

Decision thresholds:
  - "proceed":  goal is achievable by a software system
  - "refine":   goal has fixable issues (vague scope, impossible constraint,
                missing context) — system rewrites it automatically
  - "block":    goal requires hardware, physics, or capabilities outside
                software scope with no meaningful software-only interpretation

The orchestrator blocks pipeline progression if decision == "block".
If decision == "refine", the refined_goal replaces the raw_goal before
proceeding to the requirement_closure agent.
"""
from __future__ import annotations

import os
from typing import Literal, TypedDict

import anthropic

MODEL = os.environ.get("CRITIC_MODEL", "claude-haiku-4-5-20251001")


# ── Types ─────────────────────────────────────────────────────────────────────

class FeasibilityIssue(TypedDict):
    type: str       # "impossible", "out_of_scope", "vague", "missing_constraint"
    message: str
    severity: Literal["critical", "warning"]


class FeasibilityResult(TypedDict):
    decision: Literal["proceed", "refine", "block"]
    confidence: float
    issues: list[FeasibilityIssue]
    refined_goal: str | None
    suggestions: list[str]
    reasoning: str


# ── Tool schema ───────────────────────────────────────────────────────────────

_TOOL = {
    "name": "evaluate_feasibility",
    "description": (
        "Evaluate whether a software build goal is achievable. "
        "Return a structured decision: proceed, refine, or block."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["proceed", "refine", "block"],
                "description": (
                    "proceed: goal is achievable by a software system as-is. "
                    "refine: goal has fixable issues — rewrite it in refined_goal. "
                    "block: goal is fundamentally impossible or out of software scope."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "Your confidence in this decision, 0.0–1.0",
            },
            "issues": {
                "type": "array",
                "description": "Specific issues found (can be empty for proceed)",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "physically_impossible",
                                "requires_hardware",
                                "scope_too_large",
                                "missing_critical_constraint",
                                "ambiguous_target",
                                "contradictory_requirements",
                                "out_of_software_scope",
                            ],
                        },
                        "message": {"type": "string"},
                        "severity": {"type": "string", "enum": ["critical", "warning"]},
                    },
                    "required": ["type", "message", "severity"],
                },
            },
            "refined_goal": {
                "type": "string",
                "description": (
                    "Required when decision=refine. "
                    "Rewrite the goal to be specific, achievable, and software-scoped. "
                    "e.g. 'send an apple to Mars' → 'build a mission planning API "
                    "for tracking Mars payload shipments'."
                ),
            },
            "suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "When decision=block, list 2-3 software-achievable alternatives "
                    "that might capture the user's underlying intent."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "One-paragraph explanation of the decision.",
            },
        },
        "required": ["decision", "confidence", "issues", "suggestions", "reasoning"],
    },
}

_SYSTEM = """\
You are a feasibility critic for an autonomous software factory.

Your role is to block or redirect goals that cannot be achieved by a software system
BEFORE the system wastes resources building the wrong thing.

Rules:
1. A "software system" means: APIs, web apps, CLIs, databases, automation scripts,
   MCP servers, data pipelines, mobile apps, AI agents, deployment configs.
2. Anything requiring physical hardware, manufacturing, aerospace systems,
   biological processes, or real-world logistics OUTSIDE software is out of scope.
3. Vague goals ("build something cool") must be refined, not blocked.
4. Large but achievable goals ("build Uber") → refine with realistic scope,
   not block (e.g. "build an Uber-like ride booking API").
5. Be honest and direct. Do not proceed with impossible goals to be "helpful".
6. When refining, keep the user's core intent. Do not change the domain entirely.

Assessment dimensions:
  - Physical feasibility: can software alone achieve this?
  - Scope feasibility: is this buildable in a reasonable timeframe?
  - Constraint completeness: are there missing critical parameters?
  - Contradiction detection: do requirements conflict?

Always call evaluate_feasibility with a complete structured assessment.\
"""


def _build_prompt(intent_spec: dict) -> str:
    raw_goal = intent_spec.get("raw_goal", "")
    build_target = intent_spec.get("build_target", "")
    deploy_target = intent_spec.get("deploy_target", "")
    integrations = intent_spec.get("integrations", [])
    must_ask = intent_spec.get("must_ask", [])

    lines = [f"Goal: {raw_goal}"]
    if build_target:
        lines.append(f"Parsed build target: {build_target}")
    if deploy_target:
        lines.append(f"Deploy target: {deploy_target}")
    if integrations:
        lines.append(f"Integrations: {', '.join(integrations)}")
    if must_ask:
        lines.append(f"Ambiguous fields (system couldn't determine): {', '.join(must_ask)}")

    lines.append(
        "\nEvaluate this goal. Call evaluate_feasibility with your structured assessment."
    )
    return "\n".join(lines)


async def evaluate(
    intent_spec: dict,
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> FeasibilityResult:
    """
    Evaluate whether the intent spec represents an achievable software goal.

    Args:
        intent_spec: The IntentSpec produced by the intent block.
        client:      Optional AsyncAnthropic client for DI in tests.

    Returns:
        FeasibilityResult with decision, confidence, issues, refined_goal, suggestions.

    Raises:
        ValueError: if intent_spec has no raw_goal.
        RuntimeError: if the model fails to call evaluate_feasibility.
    """
    if not intent_spec.get("raw_goal", "").strip():
        raise ValueError("intent_spec.raw_goal is empty")

    _client = client or anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "evaluate_feasibility"},
        messages=[{"role": "user", "content": _build_prompt(intent_spec)}],
    )

    tool_block = next(
        (b for b in response.content if b.type == "tool_use"),
        None,
    )
    if tool_block is None:
        raise RuntimeError(
            f"Model did not call evaluate_feasibility. Response: {response.content}"
        )

    data = tool_block.input
    return FeasibilityResult(
        decision=data["decision"],
        confidence=float(data.get("confidence", 0.8)),
        issues=data.get("issues", []),
        refined_goal=data.get("refined_goal") or None,
        suggestions=data.get("suggestions", []),
        reasoning=data.get("reasoning", ""),
    )

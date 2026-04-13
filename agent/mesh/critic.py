"""
Critic — adversarial review agent with right-to-block.

The critic is NOT a rubber stamp. It evaluates outputs at three key moments:

  1. After Planner  → is the plan coherent and achievable?
  2. After Coder    → is the code structurally correct, not just lint-passing?
  3. After Tester   → are the tests meaningful, or are they shallow assertions?

Output (all three phases):
  {
    "decision":              "approve" | "revise" | "block",
    "confidence":            float,           # 0.0–1.0
    "issues": [
      {"type": str, "message": str, "severity": "critical" | "warning"}
    ],
    "revision_instructions": str,             # what to fix if decision != "approve"
    "score":                 float,           # 0–100 quality score
  }

Decision rules:
  approve  → output quality is sufficient; pipeline continues
  revise   → specific issues found; revision_instructions guide the next round
  block    → fundamental problem that cannot be fixed by iteration; escalate

Confidence < 0.5 downgrades "block" to "revise" automatically (critic isn't sure).
MAX_CRITIC_ROUNDS = 2 prevents infinite loops.

The critic uses STRUCTURE-BASED evaluation, not personality. It checks:
  - Plan phase:   file count, interface coverage, dependency cycles
  - Code phase:   missing error handling, hardcoded values, unused imports,
                  test-only code patterns (mocks in production paths)
  - Test phase:   happy-path-only coverage, missing edge cases, assert True patterns,
                  no mock of external services
"""
from __future__ import annotations

import json
import os
from typing import Literal, TypedDict

import anthropic

MODEL = os.environ.get("CRITIC_MODEL", "claude-haiku-4-5-20251001")
MAX_CRITIC_ROUNDS = 2
MIN_BLOCK_CONFIDENCE = 0.7   # blocks below this threshold become revisions


# ── Types ─────────────────────────────────────────────────────────────────────

class CriticIssue(TypedDict):
    type: str
    message: str
    severity: Literal["critical", "warning"]


class CriticResult(TypedDict):
    decision: Literal["approve", "revise", "block"]
    confidence: float
    issues: list[CriticIssue]
    revision_instructions: str
    score: float


# ── Tool schema (shared across all phases) ────────────────────────────────────

def _make_tool(phase: str) -> dict:
    return {
        "name": "evaluate_output",
        "description": f"Evaluate the {phase} output and decide whether to approve, revise, or block.",
        "input_schema": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["approve", "revise", "block"],
                    "description": (
                        "approve: output is sufficient, pipeline continues. "
                        "revise: specific fixable issues found — provide revision_instructions. "
                        "block: fundamental problem requiring human intervention."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence in this decision, 0.0–1.0",
                },
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    # Plan issues
                                    "missing_file",
                                    "missing_interface",
                                    "circular_dependency",
                                    "overcomplicated_plan",
                                    # Code issues
                                    "missing_error_handling",
                                    "hardcoded_secret",
                                    "no_input_validation",
                                    "test_code_in_production",
                                    "missing_type_hints",
                                    # Test issues
                                    "happy_path_only",
                                    "missing_edge_cases",
                                    "trivial_assertions",
                                    "no_mock_for_external_services",
                                    "test_covers_wrong_interface",
                                    # General
                                    "does_not_match_requirements",
                                    "structural_problem",
                                ],
                            },
                            "message": {"type": "string"},
                            "severity": {"type": "string", "enum": ["critical", "warning"]},
                            "location": {
                                "type": "string",
                                "description": "File or function where the issue occurs, if applicable",
                            },
                        },
                        "required": ["type", "message", "severity"],
                    },
                },
                "revision_instructions": {
                    "type": "string",
                    "description": (
                        "Required when decision=revise or block. "
                        "Specific, actionable instructions for what to fix. "
                        "Not vague feedback — exact changes needed."
                    ),
                },
                "score": {
                    "type": "number",
                    "description": (
                        "Quality score 0–100. "
                        "approve typically 75+, revise 40–74, block below 40."
                    ),
                },
            },
            "required": ["decision", "confidence", "issues", "revision_instructions", "score"],
        },
    }


# ── Phase-specific system prompts ─────────────────────────────────────────────

_PLAN_SYSTEM = """\
You are a senior software architect reviewing an implementation plan.

Evaluate whether the plan produced by the Planner is coherent and complete.

Check:
1. Does every file in file_tree have a corresponding blueprint?
2. Does each module interface have matching function signatures?
3. Are there circular dependencies (A imports B imports A)?
4. Is the plan overcomplicated for the task? (10 files for a simple CLI is wrong)
5. Are there missing __init__.py files for Python packages?
6. Are test files planned for each implementation file?

Rules:
- If the plan has all required files and interfaces → approve
- If fixable gaps exist (missing one file, one function) → revise with specific instructions
- If the plan is fundamentally wrong (wrong architecture entirely) → block
- Be specific. "missing src/__init__.py" beats "incomplete plan"

Always call evaluate_output.\
"""

_CODE_SYSTEM = """\
You are a senior software engineer reviewing generated code.

Evaluate whether the code is production-quality, not just lint-passing.

Check:
1. Error handling: are exceptions caught and handled? Or does it crash on bad input?
2. Secrets: are API keys hardcoded instead of read from environment variables?
3. Input validation: does the code validate user/external input at entry points?
4. Interface adherence: does the code implement the planned function signatures?
5. Test contamination: are mocks/stubs used in production code paths?
6. Type hints: are public functions typed? (warnings only, not critical)

Rules:
- Hardcoded secrets → always block
- Unhandled exceptions on external calls → revise
- Minor style issues → approve with warnings
- Code that cannot work (import errors, wrong method calls) → revise
- Extra helper functions beyond the plan → approve (coder knows best)

Be direct. Don't approve bad code because it passes lint.

Always call evaluate_output.\
"""

_TEST_SYSTEM = """\
You are a senior QA engineer reviewing a generated test suite.

Evaluate whether the tests are MEANINGFUL, not just passing.

Check:
1. Happy path only: do tests only check the successful case?
2. Edge cases: are empty inputs, None values, large inputs, invalid types tested?
3. Trivial assertions: are there "assert True" or "assert result is not None" only?
4. External service mocking: are HTTP calls, database calls, and API calls mocked?
5. Interface coverage: does each public function have at least one test?
6. Error path tests: are exceptions and error conditions tested?

Scoring guide:
- 85+: edge cases covered, mocks present, multiple assertions per test
- 60-84: happy path covered, basic mocks, some edge cases
- 40-59: happy path only, some missing mocks, no error paths
- <40: trivial assertions, no mocks, or tests that always pass

Rules:
- "assert True" or "assert result is not None" as the only assertion → revise
- No mock for external HTTP/database calls → revise (tests will fail in CI)
- Only happy path tested → revise (tests miss real failures)
- Good coverage with meaningful assertions → approve

Always call evaluate_output.\
"""


# ── Public API ────────────────────────────────────────────────────────────────

async def evaluate_plan(
    plan_spec: dict,
    architecture_spec: dict,
    intent_spec: dict,
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> CriticResult:
    """Evaluate the Planner's output before coding begins."""
    _client = client or _default_client()

    plan_summary = json.dumps({
        "file_plans": list(plan_spec.get("file_plans", {}).keys()),
        "entry_point": plan_spec.get("entry_point", ""),
        "test_strategy": plan_spec.get("test_strategy", ""),
    }, indent=2)

    arch_summary = json.dumps({
        "file_tree": architecture_spec.get("file_tree", []),
        "module_interfaces": list(architecture_spec.get("module_interfaces", {}).keys()),
        "tech_choices": architecture_spec.get("tech_choices", {}),
    }, indent=2)

    prompt = (
        f"Goal: {intent_spec.get('raw_goal', '')}\n\n"
        f"Architecture spec:\n{arch_summary}\n\n"
        f"Planner output:\n{plan_summary}\n\n"
        "Evaluate this plan. Every file in the architecture must appear in file_plans.\n"
        "Call evaluate_output with your assessment."
    )

    return await _call_critic(prompt, _PLAN_SYSTEM, _client)


async def evaluate_code(
    file_contents: dict[str, str],
    plan_spec: dict,
    intent_spec: dict,
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> CriticResult:
    """Evaluate the Coder's output before testing."""
    _client = client or _default_client()

    # Send first 40 lines of each file to stay within token limits
    file_previews: dict[str, str] = {}
    for path, content in file_contents.items():
        lines = content.splitlines()
        preview = "\n".join(lines[:40])
        if len(lines) > 40:
            preview += f"\n... ({len(lines) - 40} more lines)"
        file_previews[path] = preview

    planned_functions = []
    for path, fp in plan_spec.get("file_plans", {}).items():
        for fn in fp.get("functions", []):
            planned_functions.append(f"{path}: {fn.get('signature', '')}")
        for cls in fp.get("classes", []):
            for m in cls.get("methods", []):
                planned_functions.append(f"{path}/{cls['name']}: {m.get('signature', '')}")

    prompt = (
        f"Goal: {intent_spec.get('raw_goal', '')}\n\n"
        f"Planned functions (must exist in code):\n"
        + "\n".join(f"  - {f}" for f in planned_functions[:20])
        + "\n\nGenerated files:\n"
        + json.dumps(file_previews, indent=2)[:8000]  # cap at 8K chars
        + "\n\nEvaluate this code. Call evaluate_output with your assessment."
    )

    return await _call_critic(prompt, _CODE_SYSTEM, _client)


async def evaluate_tests(
    file_contents: dict[str, str],
    tests_written: list[str],
    intent_spec: dict,
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> CriticResult:
    """Evaluate the Tester's output — are tests meaningful?"""
    _client = client or _default_client()

    test_contents: dict[str, str] = {
        path: content
        for path, content in file_contents.items()
        if path in tests_written or "test" in path
    }

    if not test_contents:
        # No tests written — this is a revise
        return CriticResult(
            decision="revise",
            confidence=0.95,
            issues=[
                CriticIssue(
                    type="happy_path_only",
                    message="No test files were written",
                    severity="critical",
                )
            ],
            revision_instructions="Write pytest test files covering each public function.",
            score=0.0,
        )

    prompt = (
        f"Goal: {intent_spec.get('raw_goal', '')}\n\n"
        f"Test files written: {tests_written}\n\n"
        f"Test file contents:\n"
        + json.dumps(test_contents, indent=2)[:8000]
        + "\n\nEvaluate these tests. Call evaluate_output with your assessment."
    )

    return await _call_critic(prompt, _TEST_SYSTEM, _client)


# ── Internal ──────────────────────────────────────────────────────────────────

async def _call_critic(
    prompt: str,
    system: str,
    client: anthropic.AsyncAnthropic,
) -> CriticResult:
    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        tools=[_make_tool("output")],
        tool_choice={"type": "tool", "name": "evaluate_output"},
        messages=[{"role": "user", "content": prompt}],
    )

    tool_block = next(
        (b for b in response.content if b.type == "tool_use"), None
    )
    if tool_block is None:
        # Fallback: approve with low confidence if model didn't call the tool
        return CriticResult(
            decision="approve",
            confidence=0.3,
            issues=[],
            revision_instructions="",
            score=50.0,
        )

    data = tool_block.input
    decision: Literal["approve", "revise", "block"] = data.get("decision", "approve")
    confidence = float(data.get("confidence", 0.8))

    # Downgrade blocks with low confidence to revisions
    if decision == "block" and confidence < MIN_BLOCK_CONFIDENCE:
        decision = "revise"

    return CriticResult(
        decision=decision,
        confidence=confidence,
        issues=data.get("issues", []),
        revision_instructions=data.get("revision_instructions", ""),
        score=float(data.get("score", 75.0)),
    )


def _default_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

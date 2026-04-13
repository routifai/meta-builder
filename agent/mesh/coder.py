"""
Coder — ReAct loop that writes implementation code.

Each call to run(ctx) is ONE round. The orchestrator calls it repeatedly
until ctx.coder_should_stop() returns True (no errors, or max rounds hit).

On each round the coder receives:
  - ctx.architecture_spec    — what to build (file tree, interfaces, tech choices)
  - ctx.research_result      — recommended stack + skill docs
  - ctx.file_contents        — what was already written (empty on round 1)
  - ctx.lint_errors          — from previous round's run_lint call
  - ctx.type_errors          — from previous round's run_type_check call
  - ctx.test_failures        — from tester or previous run_tests call

Tools available to coder:
  - write_file          — create/overwrite source files
  - read_file           — read files it or other agents wrote
  - run_lint            — ruff; updates ctx.lint_errors
  - run_type_check      — mypy; updates ctx.type_errors
  - run_tests           — pytest; updates ctx.test_failures
  - fill_knowledge_gap  — on-demand researcher for domain knowledge
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import anthropic

from agent.shared.capabilities import (
    get_capability_tool_definitions,
    read_file,
    run_lint,
    run_tests,
    run_type_check,
    write_file,
)
from agent.shared.knowledge import fill_knowledge_gap, get_knowledge_tool_definition
from agent.shared.run_context import RunContext
from agent.shared.sandbox import SandboxViolation

MODEL = "claude-opus-4-6"
MAX_TOKENS = 8192
_RETRY_DELAYS = [10, 30, 60]  # seconds to wait after each 429


async def _call_with_retry(client: anthropic.AsyncAnthropic, **kwargs) -> anthropic.types.Message:
    """Wrap messages.create with exponential backoff on rate limit errors."""
    for attempt, delay in enumerate(_RETRY_DELAYS + [None]):
        try:
            return await client.messages.create(**kwargs)
        except anthropic.RateLimitError:
            if delay is None:
                raise  # exhausted retries
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


async def run(ctx: RunContext, *, client: anthropic.AsyncAnthropic | None = None) -> None:
    """
    One round of coder work.

    Runs the Anthropic message loop until the model reaches end_turn.
    Updates ctx in-place via capability tool calls.
    """
    _client = client or anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    tools = get_capability_tool_definitions(
        ["write_file", "read_file", "run_lint", "run_type_check", "run_tests"]
    ) + [get_knowledge_tool_definition()]

    messages = _build_messages(ctx)

    while True:
        response = await _call_with_retry(
            _client,
            model=MODEL,
            tools=tools,
            messages=messages,
            system=_build_system(ctx),
            max_tokens=MAX_TOKENS,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            # Unexpected stop — treat as done
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result_content = await _dispatch(block.name, block.input, ctx, _client)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_content,
                }
            )

        # Serialize Pydantic content blocks to plain dicts before feeding back.
        # Passing SDK objects directly triggers a Pydantic 2.9 serialization bug
        # ("argument 'by_alias': NoneType cannot be converted to PyBool").
        assistant_content = [
            b.model_dump() if hasattr(b, "model_dump") else b
            for b in response.content
        ]
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})


# ── Internal helpers ──────────────────────────────────────────────────────────


def _build_system(ctx: RunContext) -> str:
    arch = ctx.architecture_spec or {}
    plan = ctx.plan_spec or {}

    base = (
        "You are a senior software engineer writing production-quality code.\n\n"
        "SANDBOX RULES (non-negotiable):\n"
        "  - You may ONLY write files using write_file with relative paths.\n"
        "  - ALL files go into the sandbox workspace (e.g. 'src/main.py', 'Dockerfile').\n"
        "  - Do NOT use '..' in any path — it will be rejected.\n"
        "  - Do NOT reference or modify files outside the workspace.\n"
        "  - The main repository is READ-ONLY; you have no access to it.\n\n"
        f"Build target: {ctx.intent_spec.get('build_target', 'unknown')}\n"
        f"Deploy target: {ctx.intent_spec.get('deploy_target', 'unknown')}\n"
        f"Integrations: {', '.join(ctx.intent_spec.get('integrations', []))}\n\n"
        "Architecture:\n"
        f"  File tree: {arch.get('file_tree', [])}\n"
        f"  Tech choices: {json.dumps(arch.get('tech_choices', {}))}\n"
        f"  Module interfaces: {json.dumps(arch.get('module_interfaces', {}))}\n\n"
    )

    if plan:
        file_plans = plan.get("file_plans", {})
        entry_point = plan.get("entry_point", "")
        test_strategy = plan.get("test_strategy", "")

        plan_lines: list[str] = ["Implementation blueprint (write exactly these signatures):\n"]
        for path, fp in file_plans.items():
            plan_lines.append(f"## {path}")
            if fp.get("description"):
                plan_lines.append(f"  Purpose: {fp['description']}")
            if fp.get("notes"):
                plan_lines.append(f"  Notes: {fp['notes']}")
            if fp.get("imports"):
                plan_lines.append(f"  Imports: {', '.join(fp['imports'][:6])}")
            if fp.get("constants"):
                plan_lines.append(f"  Constants: {', '.join(fp['constants'])}")
            for cls in fp.get("classes", []):
                plan_lines.append(f"  class {cls['name']}({', '.join(cls.get('bases', []))}):")
                plan_lines.append(f"    \"{cls.get('docstring', '')}\"")
                for m in cls.get("methods", []):
                    plan_lines.append(f"    {m['signature']}  # {m.get('docstring', '')}")
            for fn in fp.get("functions", []):
                plan_lines.append(f"  {fn['signature']}  # {fn.get('docstring', '')}")
            plan_lines.append("")

        base += "\n".join(plan_lines)
        if entry_point:
            base += f"\nEntry point: {entry_point}\n"
        if test_strategy:
            base += f"Test strategy: {test_strategy}\n"
        base += "\n"

    base += (
        "Instructions:\n"
        "1. Write all files using the blueprint above — implement the function bodies.\n"
        "2. Do not change function signatures or add extra files beyond the file tree.\n"
        "3. After writing files, run run_lint to check for style issues.\n"
        "4. Run run_tests to verify correctness.\n"
        "5. If there are errors, fix them and re-run the checks.\n"
        "6. Use fill_knowledge_gap if you need API details for a library.\n"
        "7. When lint passes and tests pass (or no tests exist), call end_turn.\n"
    )
    return base


def _build_messages(ctx: RunContext) -> list[dict]:
    """Build the initial message list including any error context from prior rounds."""
    content_parts = []

    if ctx.coder_rounds == 1 and not ctx.lint_errors and not ctx.type_errors and not ctx.test_failures:
        content_parts.append(
            {
                "type": "text",
                "text": (
                    f"Round 1: Write the implementation for "
                    f"{ctx.intent_spec.get('build_target', 'the project')}.\n"
                    f"Use the architecture spec from your system prompt.\n"
                    f"Files already in context: {list(ctx.file_contents.keys()) or 'none'}"
                ),
            }
        )
    else:
        error_lines = [f"Round {ctx.coder_rounds}: Fix the issues below.\n"]

        if ctx.plan_violations:
            error_lines.append(f"Plan violations ({len(ctx.plan_violations)}) — fix these first:")
            for v in ctx.plan_violations[:10]:
                error_lines.append(f"  - {v}")
            if len(ctx.plan_violations) > 10:
                error_lines.append(f"  ... and {len(ctx.plan_violations) - 10} more")

        if ctx.lint_errors:
            error_lines.append(f"\nLint errors ({len(ctx.lint_errors)}):")
            for e in ctx.lint_errors[:10]:
                error_lines.append(f"  - {e.get('filename', '')}:{e.get('row', '')} {e.get('code', '')} {e.get('message', '')}")
            if len(ctx.lint_errors) > 10:
                error_lines.append(f"  ... and {len(ctx.lint_errors) - 10} more")

        if ctx.type_errors:
            error_lines.append(f"\nType errors ({len(ctx.type_errors)}):")
            for e in ctx.type_errors[:10]:
                error_lines.append(f"  - {e.get('message', str(e))}")

        if ctx.test_failures:
            error_lines.append(f"\nTest failures ({len(ctx.test_failures)}):")
            for f in ctx.test_failures[:5]:
                error_lines.append(f"  - {f.get('test', '')}: {f.get('error', '')[:200]}")

        content_parts.append({"type": "text", "text": "\n".join(error_lines)})

    return [{"role": "user", "content": content_parts}]


async def _dispatch(
    tool_name: str,
    tool_input: dict[str, Any],
    ctx: RunContext,
    client: anthropic.AsyncAnthropic,
) -> str:
    """Dispatch a tool call from the coder's ReAct loop."""
    if tool_name == "write_file":
        try:
            abs_path = write_file(tool_input["path"], tool_input["content"], ctx)
            return f"Written: {abs_path}"
        except SandboxViolation as exc:
            return f"SANDBOX VIOLATION — write rejected: {exc}"

    if tool_name == "read_file":
        try:
            content = read_file(tool_input["path"], ctx)
            return content
        except FileNotFoundError as exc:
            return f"Error: {exc}"

    if tool_name == "run_lint":
        try:
            result = run_lint(tool_input["files"], ctx)
        except SandboxViolation as exc:
            return f"SANDBOX VIOLATION — lint rejected: {exc}"
        if result["passed"]:
            return "Lint passed — no errors."
        errors_summary = json.dumps(result["errors"][:20], indent=2)
        return f"Lint failed ({len(result['errors'])} errors):\n{errors_summary}"

    if tool_name == "run_type_check":
        try:
            result = run_type_check(tool_input["files"], ctx)
        except SandboxViolation as exc:
            return f"SANDBOX VIOLATION — type check rejected: {exc}"
        if result["passed"]:
            return "Type check passed — no errors."
        errors_summary = json.dumps(result["errors"][:20], indent=2)
        return f"Type check failed ({len(result['errors'])} errors):\n{errors_summary}"

    if tool_name == "run_tests":
        test_paths = tool_input.get("test_paths")
        result = run_tests(ctx, test_paths=test_paths)
        if result["passed"]:
            return (
                f"Tests passed: {result['tests_passed']}/{result['tests_run']} "
                f"(coverage: {result['coverage_pct']:.1f}%)"
            )
        failure_summary = json.dumps(result["failures"][:10], indent=2)
        return (
            f"Tests failed: {result['tests_failed']}/{result['tests_run']} failed.\n"
            f"Failures:\n{failure_summary}"
        )

    if tool_name == "fill_knowledge_gap":
        content = await fill_knowledge_gap(
            domain=tool_input["domain"],
            question=tool_input["question"],
            intent_spec=ctx.intent_spec,
            skills_dir=ctx.skills_dir,
            client=client,
        )
        return content

    return f"Unknown tool: {tool_name}"

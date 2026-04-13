"""
Tester — dual-role agent that writes and runs the test suite.

run(ctx) does two things in sequence:
  1. Write test files — LLM generates tests based on ctx.file_contents
     and ctx.architecture_spec (the module interfaces are the test contracts).
  2. Run tests — calls capabilities.run_tests(ctx), which populates
     ctx.test_failures, ctx.tests_passed, ctx.tests_failed.

The orchestrator calls this after coder's inner loop completes.
If ctx.test_failures is non-empty after run(), the orchestrator
feeds the failures back to coder for another round.

Key design: run_tests() is shared infrastructure. Coder calls it mid-loop
to self-verify. Tester calls it after writing its test suite. Same function,
same RunContext update path — no duplication.
"""
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from agent.shared.capabilities import (
    get_capability_tool_definitions,
    run_tests,
    write_file,
)
from agent.shared.run_context import RunContext
from agent.shared.sandbox import SandboxViolation

MODEL = os.environ.get("TESTER_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 8192


async def run(ctx: RunContext, *, client: anthropic.AsyncAnthropic | None = None) -> None:
    """
    Write a test suite and run it.

    After this call:
      - ctx.tests_written  — paths of generated test files
      - ctx.test_failures  — list of failed tests (empty = all passed)
      - ctx.tests_run      — total tests executed
      - ctx.tests_passed   — passing count
      - ctx.tests_failed   — failing count
    """
    _client = client or anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    # Step 1: write tests via LLM loop
    await _write_test_suite(ctx, _client)

    # Step 2: run them — updates ctx.test_failures etc.
    run_tests(ctx, test_paths=ctx.tests_written if ctx.tests_written else None)


# ── Internal helpers ──────────────────────────────────────────────────────────


async def _write_test_suite(
    ctx: RunContext,
    client: anthropic.AsyncAnthropic,
) -> None:
    """LLM loop that generates test files and writes them via write_file."""
    tools = get_capability_tool_definitions(["write_file"])

    messages = [{"role": "user", "content": _build_prompt(ctx)}]

    while True:
        response = await client.messages.create(
            model=MODEL,
            tools=tools,
            messages=messages,
            system=_build_system(ctx),
            max_tokens=MAX_TOKENS,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "write_file":
                try:
                    abs_path = write_file(block.input["path"], block.input["content"], ctx)
                except SandboxViolation as exc:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"SANDBOX VIOLATION — write rejected: {exc}",
                        }
                    )
                    continue
                # Track test files separately
                if block.input["path"] not in ctx.tests_written:
                    ctx.tests_written.append(block.input["path"])
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Written: {abs_path}",
                    }
                )

        assistant_content = [
            b.model_dump() if hasattr(b, "model_dump") else b
            for b in response.content
        ]
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})


def _build_system(ctx: RunContext) -> str:
    arch = ctx.architecture_spec or {}
    return (
        "You are a senior software engineer writing pytest tests.\n\n"
        "SANDBOX RULES (non-negotiable):\n"
        "  - Write ALL test files using write_file with relative paths.\n"
        "  - Tests MUST go under 'tests/' (e.g. 'tests/test_main.py').\n"
        "  - Do NOT use '..' in any path — it will be rejected.\n"
        "  - Do NOT reference files outside the sandbox workspace.\n\n"
        f"Build target: {ctx.intent_spec.get('build_target', 'unknown')}\n"
        f"Deploy target: {ctx.intent_spec.get('deploy_target', 'unknown')}\n\n"
        "Module interfaces (your test contracts):\n"
        f"{json.dumps(arch.get('module_interfaces', {}), indent=2)}\n\n"
        "Instructions:\n"
        "1. Write pytest test files for each module interface.\n"
        "2. Place ALL tests under 'tests/' (e.g. 'tests/test_main.py').\n"
        "3. Use write_file to write each test file.\n"
        "4. Cover: happy path, edge cases, error handling.\n"
        "5. Mock external services (HTTP calls, databases, APIs).\n"
        "6. When done writing all test files, call end_turn.\n"
    )


def _build_prompt(ctx: RunContext) -> str:
    file_list = "\n".join(f"  - {p}" for p in ctx.files_written) or "  (none written yet)"
    return (
        f"Write a test suite for the implementation below.\n\n"
        f"Files written by coder:\n{file_list}\n\n"
        f"Write tests that validate each module's public interface. "
        f"Aim for >80% coverage of the happy path and key error paths."
    )

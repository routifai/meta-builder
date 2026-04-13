"""
Capabilities — the tool layer shared by agents and orchestrator.

These are plain Python functions (not agent methods). They can be:
  1. Called directly by the orchestrator between phases.
  2. Registered as Anthropic tool definitions and called by agent ReAct loops.

All file-writing operations are sandboxed:
  - write_file  → resolves paths via ctx.sandbox.safe_path()
                  (writes ONLY to runs/{run_id}/workspace/)
  - read_file   → workspace first, then read-only fallback for skills/
  - run_lint    → operates on workspace paths
  - run_type_check → operates on workspace paths
  - run_tests   → pytest runs inside workspace; saves JSON report to artifacts/

SandboxViolation is raised (and surfaced to the LLM as a tool error) if an
agent attempts to write outside the workspace.

Usage:
    from agent.shared.capabilities import (
        write_file, read_file, run_lint, run_type_check,
        run_tests, run_command, get_capability_tool_definitions,
    )
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from agent.shared.sandbox import SandboxViolation

if TYPE_CHECKING:
    from agent.shared.run_context import RunContext


# ── Return types ──────────────────────────────────────────────────────────────


class LintResult(TypedDict):
    passed: bool
    errors: list[dict]
    raw_output: str


class TypeCheckResult(TypedDict):
    passed: bool
    errors: list[dict]
    raw_output: str


class SuiteResult(TypedDict):
    passed: bool
    tests_run: int
    tests_passed: int
    tests_failed: int
    coverage_pct: float
    failures: list[dict]
    raw_output: str


class CommandResult(TypedDict):
    returncode: int
    stdout: str
    stderr: str
    succeeded: bool


# ── File capabilities ─────────────────────────────────────────────────────────


def write_file(path: str, content: str, run_context: "RunContext") -> str:
    """
    Write content to path inside the run's sandbox workspace.

    Path is resolved via ctx.sandbox.safe_path() — any attempt to write
    outside runs/{run_id}/workspace/ raises SandboxViolation.

    Records the file in run_context.file_contents and run_context.files_written.
    Returns the absolute path written as a string.

    Raises:
        SandboxViolation: if path escapes the workspace sandbox.
    """
    abs_path = run_context.sandbox.safe_path(path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")

    path_str = str(abs_path)
    run_context.file_contents[path] = content
    if path not in run_context.files_written:
        run_context.files_written.append(path)

    return path_str


def read_file(path: str, run_context: "RunContext") -> str:
    """
    Read a file, checking multiple sources in priority order:

      1. run_context.file_contents[path]    — in-memory cache (fastest)
      2. runs/{run_id}/workspace/{path}     — files written this run
      3. skills/ (read-only global access)  — allowed for knowledge queries

    Absolute paths pointing outside skills/ or workspace are rejected.

    Raises:
        FileNotFoundError: if the file is not found in any allowed location.
        SandboxViolation: if the path escapes the workspace and is not in skills/.
    """
    # 1. In-memory cache
    if path in run_context.file_contents:
        return run_context.file_contents[path]

    # 2. Workspace (sandboxed write zone)
    try:
        workspace_path = run_context.sandbox.safe_path(path)
        if workspace_path.exists():
            return workspace_path.read_text(encoding="utf-8")
    except SandboxViolation:
        # Path escapes workspace — check if it's a read-only skills path
        pass

    # 3. Read-only fallback: skills directory
    cleaned = path.lstrip("/")
    skills_root = Path(run_context.skills_dir).resolve()
    skills_candidate = (Path(run_context.skills_dir) / cleaned).resolve()
    try:
        skills_candidate.relative_to(skills_root)
        if skills_candidate.exists():
            return skills_candidate.read_text(encoding="utf-8")
    except ValueError:
        pass

    raise FileNotFoundError(
        f"File not found in workspace or skills: {path!r}\n"
        f"Workspace: {run_context.workspace_path}\n"
        f"Skills dir: {run_context.skills_dir}"
    )


# ── Quality capabilities ──────────────────────────────────────────────────────


def run_lint(files: list[str], run_context: "RunContext") -> LintResult:
    """
    Run ruff on the given files and update run_context.lint_errors.

    Files are resolved via sandbox.safe_path() — only workspace files are linted.
    Returns a LintResult with structured error dicts.

    Raises:
        SandboxViolation: if any file path escapes the workspace.
    """
    abs_files = [str(run_context.sandbox.safe_path(f)) for f in files]

    try:
        proc = subprocess.run(
            ["ruff", "check", "--output-format=json"] + abs_files,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        # ruff not installed — skip lint, treat as passed so pipeline continues
        run_context.lint_errors = []
        run_context.lint_passed = True
        return LintResult(passed=True, errors=[], raw_output="ruff not found — lint skipped")

    errors: list[dict] = []
    raw = proc.stdout + proc.stderr
    if proc.stdout.strip():
        try:
            errors = json.loads(proc.stdout)
        except json.JSONDecodeError:
            errors = [{"message": proc.stdout.strip(), "code": "PARSE_ERROR"}]

    passed = proc.returncode == 0
    run_context.lint_errors = errors
    run_context.lint_passed = passed

    return LintResult(passed=passed, errors=errors, raw_output=raw)


def run_type_check(files: list[str], run_context: "RunContext") -> TypeCheckResult:
    """
    Run mypy on the given files and update run_context.type_errors.

    Files are resolved via sandbox.safe_path() — only workspace files are checked.
    Returns a TypeCheckResult with structured error dicts.

    Raises:
        SandboxViolation: if any file path escapes the workspace.
    """
    abs_files = [str(run_context.sandbox.safe_path(f)) for f in files]

    try:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [
                    "mypy",
                    "--output=json",
                    "--no-error-summary",
                    f"--cache-dir={tmp}",
                ]
                + abs_files,
                capture_output=True,
                text=True,
            )
    except FileNotFoundError:
        # mypy not installed — skip type check, treat as passed
        run_context.type_errors = []
        run_context.type_check_passed = True
        return TypeCheckResult(passed=True, errors=[], raw_output="mypy not found — type check skipped")

    errors: list[dict] = []
    raw = proc.stdout + proc.stderr
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            errors.append(json.loads(line))
        except json.JSONDecodeError:
            errors.append({"message": line, "severity": "error"})

    passed = proc.returncode == 0
    run_context.type_errors = errors
    run_context.type_check_passed = passed

    return TypeCheckResult(passed=passed, errors=errors, raw_output=raw)


def run_tests(
    run_context: "RunContext",
    test_paths: list[str] | None = None,
) -> SuiteResult:
    """
    Run pytest inside the sandbox workspace and update run_context test state.

    - pytest cwd is set to workspace/ (not the main repo)
    - If test_paths is None, discovers tests inside workspace/ only
    - JSON report is saved to artifacts/test-results.json

    Updates:
      - run_context.test_failures
      - run_context.tests_run / tests_passed / tests_failed
      - run_context.coverage_pct (if pytest-cov is available)

    Raises:
        SandboxViolation: if any test_path escapes the workspace.
    """
    sandbox = run_context.sandbox
    sandbox.create()  # ensure artifacts/ exists before writing report

    workspace = sandbox.workspace
    artifacts = sandbox.artifacts
    report_path = artifacts / "test-results.json"

    if test_paths:
        abs_paths = [str(sandbox.safe_path(p)) for p in test_paths]
    else:
        abs_paths = [str(workspace)]

    cmd = [
        "pytest",
        "--json-report",
        f"--json-report-file={report_path}",
        "--tb=short",
        "-q",
    ] + abs_paths

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(workspace),
    )
    raw = proc.stdout + proc.stderr

    failures: list[dict] = []
    tests_run = 0
    tests_passed = 0
    tests_failed = 0
    coverage_pct = 0.0

    if report_path.exists():
        try:
            report = json.loads(report_path.read_text())
            summary = report.get("summary", {})
            tests_run = summary.get("total", 0)
            tests_passed = summary.get("passed", 0)
            tests_failed = summary.get("failed", 0)

            for test in report.get("tests", []):
                if test.get("outcome") in ("failed", "error"):
                    failures.append(
                        {
                            "test": test.get("nodeid", ""),
                            "error": test.get("call", {}).get("longrepr", ""),
                        }
                    )

            cov = report.get("coverage", {})
            if cov:
                coverage_pct = float(cov.get("totals", {}).get("percent_covered", 0.0))
        except (json.JSONDecodeError, KeyError):
            pass

    passed = proc.returncode == 0
    run_context.test_failures = failures
    run_context.tests_run = tests_run
    run_context.tests_passed = tests_passed
    run_context.tests_failed = tests_failed
    run_context.coverage_pct = coverage_pct

    return SuiteResult(
        passed=passed,
        tests_run=tests_run,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        coverage_pct=coverage_pct,
        failures=failures,
        raw_output=raw,
    )


# ── Shell capability ──────────────────────────────────────────────────────────


def run_command(
    cmd: list[str],
    run_context: "RunContext",
    *,
    cwd: str | None = None,
    timeout: int = 120,
) -> CommandResult:
    """
    Run an arbitrary shell command (for deployer and monitor_setup).

    cwd defaults to the run's workspace directory.
    This function is NOT exposed to LLM agents — orchestrator use only.
    """
    working_dir = cwd or run_context.workspace_path

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=timeout,
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            succeeded=proc.returncode == 0,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            returncode=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s: {' '.join(cmd)}",
            succeeded=False,
        )


# ── Anthropic tool definitions ────────────────────────────────────────────────

_TOOL_DEFINITIONS: dict[str, dict] = {
    "write_file": {
        "name": "write_file",
        "description": (
            "Write a file to the sandbox workspace. "
            "ALL generated code, tests, Dockerfiles, and config must be "
            "written here. Paths are relative to the workspace root "
            "(e.g. 'src/main.py', 'tests/test_main.py', 'Dockerfile'). "
            "Do NOT use absolute paths or '..' — these are rejected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path inside the workspace, e.g. 'src/server.py'. "
                        "Do not use '..' or leading '/'."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Full text content to write to the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
    "read_file": {
        "name": "read_file",
        "description": (
            "Read the content of a file. "
            "Checks in-memory cache first, then workspace, then skills/. "
            "Use this to inspect files you or a previous agent wrote."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path, e.g. 'src/server.py'",
                },
            },
            "required": ["path"],
        },
    },
    "run_lint": {
        "name": "run_lint",
        "description": (
            "Run ruff linter on the specified workspace files. "
            "Returns structured errors with line numbers and rule codes. "
            "Call this after writing or modifying Python files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of relative file paths to lint.",
                },
            },
            "required": ["files"],
        },
    },
    "run_type_check": {
        "name": "run_type_check",
        "description": (
            "Run mypy type checker on the specified workspace files. "
            "Returns structured type errors. "
            "Call after writing files that have type annotations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of relative file paths to type-check.",
                },
            },
            "required": ["files"],
        },
    },
    "run_tests": {
        "name": "run_tests",
        "description": (
            "Run the test suite using pytest inside the sandbox workspace. "
            "Returns pass/fail counts and structured failure details. "
            "If test_paths is omitted, discovers all tests inside workspace/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "test_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of specific test file paths (relative). "
                        "If omitted, runs all tests in workspace/."
                    ),
                },
            },
            "required": [],
        },
    },
}


def get_capability_tool_definitions(subset: list[str]) -> list[dict]:
    """
    Return Anthropic tool definitions for the named capabilities.

    Example:
        get_capability_tool_definitions(["write_file", "run_lint", "run_tests"])

    Valid names: write_file, read_file, run_lint, run_type_check, run_tests
    (run_command is not exposed to LLM agents — orchestrator only)
    """
    unknown = set(subset) - set(_TOOL_DEFINITIONS)
    if unknown:
        raise ValueError(f"Unknown capability names: {unknown}")
    return [_TOOL_DEFINITIONS[name] for name in subset]

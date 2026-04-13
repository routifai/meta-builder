"""Unit tests for agent/shared/capabilities.py"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.shared.capabilities import (
    LintResult,
    SuiteResult,
    TypeCheckResult,
    get_capability_tool_definitions,
    read_file,
    run_command,
    run_lint,
    run_tests,
    run_type_check,
    write_file,
)
from agent.shared.run_context import RunContext


def make_ctx(tmp_path) -> RunContext:
    ctx = RunContext(
        run_id="cap-test",
        intent_spec={"raw_goal": "test"},
        output_dir=str(tmp_path),
    )
    ctx.sandbox.create()  # create workspace/ artifacts/ logs/
    return ctx


# ── write_file ────────────────────────────────────────────────────────────────


class TestWriteFile:
    def test_writes_file_to_disk(self, tmp_path):
        ctx = make_ctx(tmp_path)
        write_file("src/main.py", "print('hello')", ctx)
        assert (tmp_path / "workspace" / "src" / "main.py").read_text() == "print('hello')"

    def test_records_in_file_contents(self, tmp_path):
        ctx = make_ctx(tmp_path)
        write_file("src/main.py", "x = 1", ctx)
        assert ctx.file_contents["src/main.py"] == "x = 1"

    def test_records_in_files_written(self, tmp_path):
        ctx = make_ctx(tmp_path)
        write_file("src/a.py", "a", ctx)
        write_file("src/b.py", "b", ctx)
        assert "src/a.py" in ctx.files_written
        assert "src/b.py" in ctx.files_written

    def test_no_duplicate_in_files_written(self, tmp_path):
        ctx = make_ctx(tmp_path)
        write_file("src/a.py", "v1", ctx)
        write_file("src/a.py", "v2", ctx)
        assert ctx.files_written.count("src/a.py") == 1

    def test_creates_parent_dirs(self, tmp_path):
        ctx = make_ctx(tmp_path)
        write_file("a/b/c/deep.py", "content", ctx)
        assert (tmp_path / "workspace" / "a" / "b" / "c" / "deep.py").exists()

    def test_returns_absolute_path(self, tmp_path):
        ctx = make_ctx(tmp_path)
        result = write_file("main.py", "x", ctx)
        assert result == str(tmp_path / "workspace" / "main.py")


# ── read_file ─────────────────────────────────────────────────────────────────


class TestReadFile:
    def test_reads_from_in_memory_cache(self, tmp_path):
        ctx = make_ctx(tmp_path)
        ctx.file_contents["cached.py"] = "# in memory"
        result = read_file("cached.py", ctx)
        assert result == "# in memory"

    def test_reads_from_disk_when_not_in_cache(self, tmp_path):
        ctx = make_ctx(tmp_path)
        # write into workspace/ (where sandbox expects files)
        (tmp_path / "workspace" / "disk.py").write_text("# on disk")
        result = read_file("disk.py", ctx)
        assert result == "# on disk"

    def test_cache_takes_priority_over_disk(self, tmp_path):
        ctx = make_ctx(tmp_path)
        (tmp_path / "workspace" / "both.py").write_text("# disk version")
        ctx.file_contents["both.py"] = "# cache version"
        result = read_file("both.py", ctx)
        assert result == "# cache version"

    def test_raises_file_not_found(self, tmp_path):
        ctx = make_ctx(tmp_path)
        with pytest.raises(FileNotFoundError):
            read_file("nonexistent.py", ctx)


# ── run_lint ──────────────────────────────────────────────────────────────────


class TestRunLint:
    def test_passing_lint_returns_no_errors(self, tmp_path):
        ctx = make_ctx(tmp_path)
        (tmp_path / "clean.py").write_text("x = 1\n")

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "[]"
        fake_result.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_result):
            result = run_lint(["clean.py"], ctx)

        assert result["passed"] is True
        assert result["errors"] == []
        assert ctx.lint_passed is True
        assert ctx.lint_errors == []

    def test_failing_lint_updates_context(self, tmp_path):
        ctx = make_ctx(tmp_path)
        (tmp_path / "bad.py").write_text("import os\n")

        fake_errors = [{"code": "F401", "message": "'os' imported but unused", "row": 1}]
        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = json.dumps(fake_errors)
        fake_result.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_result):
            result = run_lint(["bad.py"], ctx)

        assert result["passed"] is False
        assert len(result["errors"]) == 1
        assert ctx.lint_passed is False
        assert ctx.lint_errors == fake_errors

    def test_non_json_stdout_wrapped_as_error(self, tmp_path):
        ctx = make_ctx(tmp_path)
        (tmp_path / "f.py").write_text("")

        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = "ruff: config error\n"
        fake_result.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_result):
            result = run_lint(["f.py"], ctx)

        assert result["passed"] is False
        assert result["errors"][0]["code"] == "PARSE_ERROR"


# ── run_type_check ────────────────────────────────────────────────────────────


class TestRunTypeCheck:
    def test_passing_type_check(self, tmp_path):
        ctx = make_ctx(tmp_path)
        (tmp_path / "typed.py").write_text("x: int = 1\n")

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = ""
        fake_result.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_result):
            result = run_type_check(["typed.py"], ctx)

        assert result["passed"] is True
        assert result["errors"] == []
        assert ctx.type_check_passed is True

    def test_type_errors_parsed_from_json_lines(self, tmp_path):
        ctx = make_ctx(tmp_path)
        (tmp_path / "bad.py").write_text("x: int = 'oops'\n")

        error_line = json.dumps(
            {"message": "Incompatible types in assignment", "severity": "error"}
        )
        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = error_line + "\n"
        fake_result.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_result):
            result = run_type_check(["bad.py"], ctx)

        assert result["passed"] is False
        assert len(result["errors"]) == 1
        assert ctx.type_errors[0]["severity"] == "error"

    def test_non_json_lines_wrapped(self, tmp_path):
        ctx = make_ctx(tmp_path)
        (tmp_path / "f.py").write_text("")

        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = "bad.py:1: error: something\n"
        fake_result.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_result):
            result = run_type_check(["f.py"], ctx)

        assert result["passed"] is False
        assert len(result["errors"]) == 1
        assert "something" in result["errors"][0]["message"]


# ── run_tests ─────────────────────────────────────────────────────────────────


class TestRunTests:
    def _make_report(self, passed=2, failed=0, failures=None) -> dict:
        tests = []
        for i in range(passed):
            tests.append({"nodeid": f"test_{i}", "outcome": "passed", "call": {}})
        for f in (failures or []):
            tests.append(
                {
                    "nodeid": f["test"],
                    "outcome": "failed",
                    "call": {"longrepr": f["error"]},
                }
            )
        return {
            "summary": {
                "total": passed + failed,
                "passed": passed,
                "failed": failed,
            },
            "tests": tests,
        }

    def test_passing_tests_updates_context(self, tmp_path):
        ctx = make_ctx(tmp_path)
        report = self._make_report(passed=3, failed=0)
        # sandbox.create() is called by make_ctx — artifacts/ exists
        (tmp_path / "artifacts" / "test-results.json").write_text(json.dumps(report))

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc):
            result = run_tests(ctx)

        assert result["passed"] is True
        assert ctx.test_failures == []

    def test_failing_tests_populate_failures(self, tmp_path):
        ctx = make_ctx(tmp_path)
        failures = [{"test": "test_broken", "error": "AssertionError: 1 != 2"}]
        report = self._make_report(passed=1, failed=1, failures=failures)
        (tmp_path / "artifacts" / "test-results.json").write_text(json.dumps(report))

        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc):
            result = run_tests(ctx)

        assert result["passed"] is False
        assert len(ctx.test_failures) == 1
        assert ctx.test_failures[0]["test"] == "test_broken"

    def test_missing_report_gives_empty_result(self, tmp_path):
        ctx = make_ctx(tmp_path)
        # No report written — artifacts/test-results.json absent

        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.stdout = "ERROR: no tests found"
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc):
            result = run_tests(ctx)

        assert result["tests_run"] == 0
        assert result["failures"] == []


# ── run_command ───────────────────────────────────────────────────────────────


class TestRunCommand:
    def test_successful_command(self, tmp_path):
        ctx = make_ctx(tmp_path)

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "deployed\n"
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc):
            result = run_command(["fly", "deploy"], ctx)

        assert result["succeeded"] is True
        assert "deployed" in result["stdout"]

    def test_timeout_returns_failure(self, tmp_path):
        import subprocess as _sp

        ctx = make_ctx(tmp_path)

        with patch(
            "agent.shared.capabilities.subprocess.run",
            side_effect=_sp.TimeoutExpired(cmd=["long"], timeout=5),
        ):
            result = run_command(["long"], ctx, timeout=5)

        assert result["succeeded"] is False
        assert "timed out" in result["stderr"].lower()
        assert result["returncode"] == -1


# ── get_capability_tool_definitions ──────────────────────────────────────────


class TestGetCapabilityToolDefinitions:
    def test_returns_requested_tools(self):
        tools = get_capability_tool_definitions(["write_file", "run_tests"])
        names = {t["name"] for t in tools}
        assert names == {"write_file", "run_tests"}

    def test_all_tools_have_required_schema_fields(self):
        tools = get_capability_tool_definitions(
            ["write_file", "read_file", "run_lint", "run_type_check", "run_tests"]
        )
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_raises_on_unknown_capability(self):
        with pytest.raises(ValueError, match="Unknown capability"):
            get_capability_tool_definitions(["run_deploy"])

    def test_write_file_requires_path_and_content(self):
        (tool,) = get_capability_tool_definitions(["write_file"])
        required = tool["input_schema"]["required"]
        assert "path" in required
        assert "content" in required

    def test_run_tests_requires_nothing(self):
        (tool,) = get_capability_tool_definitions(["run_tests"])
        assert tool["input_schema"].get("required", []) == []

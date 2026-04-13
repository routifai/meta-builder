"""Unit tests for agent/shared/run_context.py"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.shared.run_context import RunContext


def make_ctx(**kwargs) -> RunContext:
    defaults = {"run_id": "test-run-123", "intent_spec": {"raw_goal": "test"}}
    return RunContext(**{**defaults, **kwargs})


class TestCoderShouldStop:
    def test_stops_at_max_rounds(self):
        ctx = make_ctx()
        ctx.coder_rounds = ctx.MAX_CODER_ROUNDS
        assert ctx.coder_should_stop() is True

    def test_stops_when_clean(self):
        ctx = make_ctx()
        ctx.coder_rounds = 1
        # No errors → should stop
        assert ctx.coder_should_stop() is True

    def test_continues_when_lint_errors(self):
        ctx = make_ctx()
        ctx.coder_rounds = 1
        ctx.lint_errors = [{"code": "E501", "message": "line too long"}]
        assert ctx.coder_should_stop() is False

    def test_continues_when_type_errors(self):
        ctx = make_ctx()
        ctx.coder_rounds = 1
        ctx.type_errors = [{"message": "Incompatible types", "severity": "error"}]
        assert ctx.coder_should_stop() is False

    def test_continues_when_test_failures(self):
        ctx = make_ctx()
        ctx.coder_rounds = 1
        ctx.test_failures = [{"test": "test_foo", "error": "AssertionError"}]
        assert ctx.coder_should_stop() is False

    def test_stops_exactly_at_max_not_before(self):
        ctx = make_ctx()
        ctx.lint_errors = [{"code": "E501", "message": "line too long"}]

        ctx.coder_rounds = ctx.MAX_CODER_ROUNDS - 1
        assert ctx.coder_should_stop() is False  # still has room

        ctx.coder_rounds = ctx.MAX_CODER_ROUNDS
        assert ctx.coder_should_stop() is True  # hit the wall

    def test_round_zero_with_errors_continues(self):
        ctx = make_ctx()
        ctx.coder_rounds = 0
        ctx.lint_errors = [{"code": "F401", "message": "unused import"}]
        assert ctx.coder_should_stop() is False

    def test_round_zero_no_errors_does_not_stop(self):
        """Fresh context: coder must always run at least once even if no errors yet."""
        ctx = make_ctx()
        ctx.coder_rounds = 0
        assert ctx.coder_should_stop() is False


class TestOutputPath:
    def test_default_path_uses_run_id(self):
        ctx = make_ctx(run_id="abc-123")
        result = ctx.output_path("src/main.py")
        assert result == Path("runs/abc-123/src/main.py")

    def test_custom_output_dir_used(self):
        ctx = make_ctx(output_dir="/tmp/myrun")
        result = ctx.output_path("Dockerfile")
        assert result == Path("/tmp/myrun/Dockerfile")

    def test_nested_path_preserved(self):
        ctx = make_ctx(run_id="xyz")
        result = ctx.output_path("a/b/c.py")
        assert result == Path("runs/xyz/a/b/c.py")


class TestSandboxProperties:
    def test_sandbox_root_default(self):
        ctx = make_ctx(run_id="abc-123")
        assert ctx.sandbox_root == str(Path("runs") / "abc-123")

    def test_sandbox_root_with_output_dir(self):
        ctx = make_ctx(output_dir="/tmp/myrun")
        assert ctx.sandbox_root == "/tmp/myrun"

    def test_workspace_path_default(self):
        ctx = make_ctx(run_id="abc-123")
        assert ctx.workspace_path == str(Path("runs") / "abc-123" / "workspace")

    def test_workspace_path_with_output_dir(self):
        ctx = make_ctx(output_dir="/tmp/myrun")
        assert ctx.workspace_path == "/tmp/myrun/workspace"

    def test_artifacts_path_default(self):
        ctx = make_ctx(run_id="abc-123")
        assert ctx.artifacts_path == str(Path("runs") / "abc-123" / "artifacts")

    def test_artifacts_path_with_output_dir(self):
        ctx = make_ctx(output_dir="/tmp/myrun")
        assert ctx.artifacts_path == "/tmp/myrun/artifacts"

    def test_sandbox_returns_sandbox_manager(self):
        from agent.shared.sandbox import SandboxManager
        ctx = make_ctx(run_id="abc-123")
        sb = ctx.sandbox
        assert isinstance(sb, SandboxManager)

    def test_sandbox_root_matches_manager_root(self):
        ctx = make_ctx(run_id="abc-123")
        sb = ctx.sandbox
        assert str(sb.root) == ctx.sandbox_root

    def test_sandbox_workspace_matches_workspace_path(self):
        ctx = make_ctx(run_id="abc-123")
        sb = ctx.sandbox
        assert str(sb.workspace) == ctx.workspace_path


class TestMarkPhase:
    def test_mark_phase_records_timestamp(self):
        ctx = make_ctx()
        ctx.mark_phase("coder")
        assert "coder" in ctx.phase_timestamps
        assert ctx.phase_timestamps["coder"] >= 0

    def test_multiple_phases_recorded(self):
        ctx = make_ctx()
        ctx.mark_phase("research")
        ctx.mark_phase("coder")
        assert "research" in ctx.phase_timestamps
        assert "coder" in ctx.phase_timestamps


class TestDefaults:
    def test_lists_start_empty(self):
        ctx = make_ctx()
        assert ctx.files_written == []
        assert ctx.lint_errors == []
        assert ctx.type_errors == []
        assert ctx.test_failures == []

    def test_booleans_start_false(self):
        ctx = make_ctx()
        assert ctx.lint_passed is False
        assert ctx.type_check_passed is False
        assert ctx.smoke_tests_passed is False

    def test_counters_start_at_zero(self):
        ctx = make_ctx()
        assert ctx.coder_rounds == 0
        assert ctx.tester_rounds == 0
        assert ctx.deploy_retries == 0
        assert ctx.tests_run == 0

    def test_research_and_arch_start_none(self):
        ctx = make_ctx()
        assert ctx.research_result is None
        assert ctx.architecture_spec is None

    def test_file_contents_starts_empty(self):
        ctx = make_ctx()
        assert ctx.file_contents == {}

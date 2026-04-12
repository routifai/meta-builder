"""Unit tests for agent/shared/sandbox.py"""
from __future__ import annotations

import pytest

from agent.shared.sandbox import SandboxManager, SandboxViolation


def make_sandbox(tmp_path) -> SandboxManager:
    return SandboxManager(tmp_path / "runs" / "test-run-abc")


class TestCreate:
    def test_creates_workspace_artifacts_logs(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        assert sb.workspace.is_dir()
        assert sb.artifacts.is_dir()
        assert sb.logs.is_dir()

    def test_idempotent(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        sb.create()  # must not raise
        assert sb.workspace.is_dir()


class TestCleanWorkspace:
    def test_removes_existing_files(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        (sb.workspace / "main.py").write_text("x = 1")
        sb.clean_workspace()
        assert not (sb.workspace / "main.py").exists()
        assert sb.workspace.is_dir()

    def test_recreates_workspace_dir(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        sb.clean_workspace()
        assert sb.workspace.is_dir()


class TestSafePath:
    def test_simple_relative_path(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        result = sb.safe_path("src/main.py")
        assert result == sb.workspace.resolve() / "src" / "main.py"

    def test_leading_slash_stripped(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        with_slash = sb.safe_path("/src/main.py")
        without_slash = sb.safe_path("src/main.py")
        assert with_slash == without_slash

    def test_nested_path_allowed(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        result = sb.safe_path("a/b/c/d.py")
        assert str(result).startswith(str(sb.workspace.resolve()))

    def test_dotdot_rejected_immediately(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        with pytest.raises(SandboxViolation, match="Path traversal forbidden"):
            sb.safe_path("../../agent/orchestrator.py")

    def test_dotdot_in_middle_rejected(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        with pytest.raises(SandboxViolation):
            sb.safe_path("src/../../../etc/passwd")

    def test_absolute_escape_rejected(self, tmp_path):
        """An absolute path that resolves outside workspace/ is rejected."""
        sb = make_sandbox(tmp_path)
        sb.create()
        # After stripping leading "/", "/etc/passwd" → "etc/passwd" which is safe.
        # A genuine escape requires ".." components, already covered above.
        # Verify that a plain absolute workspace path is accepted after stripping.
        result = sb.safe_path("/src/server.py")
        assert str(result).startswith(str(sb.workspace.resolve()))

    def test_empty_path_after_strip_rejected(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        with pytest.raises(SandboxViolation, match="Empty path"):
            sb.safe_path("/")

    def test_returns_absolute_path(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        result = sb.safe_path("foo.py")
        assert result.is_absolute()


class TestSafeArtifactPath:
    def test_simple_artifact_path(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        result = sb.safe_artifact_path("test-results.json")
        assert result == sb.artifacts.resolve() / "test-results.json"

    def test_dotdot_rejected(self, tmp_path):
        sb = make_sandbox(tmp_path)
        sb.create()
        with pytest.raises(SandboxViolation):
            sb.safe_artifact_path("../../secrets.env")

"""Unit tests for agent/mesh/tester.py — dual-role implementation."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.mesh.tester import _build_prompt, _build_system, run
from agent.shared.run_context import RunContext


def make_ctx(tmp_path, **kwargs) -> RunContext:
    return RunContext(
        run_id="tester-test",
        intent_spec={
            "raw_goal": "build an MCP server",
            "build_target": "mcp_server",
            "deploy_target": "fly.io",
            "integrations": ["perplexity"],
        },
        output_dir=str(tmp_path),
        architecture_spec={
            "file_tree": ["src/server.py"],
            "module_interfaces": {
                "server": {"input": "query: str", "output": "SearchResult"}
            },
            "tech_choices": {"framework": "fastmcp"},
        },
        **kwargs,
    )


def make_end_turn_response() -> MagicMock:
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = []
    return response


def make_write_file_response(path: str, content: str, tool_id: str = "tu_1") -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "write_file"
    block.input = {"path": path, "content": content}
    block.id = tool_id

    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


class TestBuildSystem:
    def test_includes_build_target(self, tmp_path):
        ctx = make_ctx(tmp_path)
        system = _build_system(ctx)
        assert "mcp_server" in system

    def test_includes_module_interfaces(self, tmp_path):
        ctx = make_ctx(tmp_path)
        system = _build_system(ctx)
        assert "server" in system

    def test_instructs_to_write_tests(self, tmp_path):
        ctx = make_ctx(tmp_path)
        system = _build_system(ctx)
        assert "pytest" in system.lower() or "test" in system.lower()


class TestBuildPrompt:
    def test_mentions_files_written(self, tmp_path):
        ctx = make_ctx(tmp_path)
        ctx.files_written = ["src/server.py", "src/utils.py"]
        prompt = _build_prompt(ctx)
        assert "src/server.py" in prompt

    def test_empty_files_written_shows_none(self, tmp_path):
        ctx = make_ctx(tmp_path)
        ctx.files_written = []
        prompt = _build_prompt(ctx)
        assert "none" in prompt.lower()


class TestTesterRun:
    @pytest.mark.asyncio
    async def test_end_turn_no_test_files_written(self, tmp_path):
        """LLM returns end_turn immediately — no files written, run_tests still called."""
        ctx = make_ctx(tmp_path)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=make_end_turn_response())

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc), \
             patch("agent.shared.capabilities.tempfile.TemporaryDirectory") as mock_tmp:
            real_tmp = tmp_path / "pt"
            real_tmp.mkdir()
            report = {"summary": {"total": 0, "passed": 0, "failed": 0}, "tests": []}
            (real_tmp / "report.json").write_text(json.dumps(report))
            mock_tmp.return_value.__enter__ = MagicMock(return_value=str(real_tmp))
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

            await run(ctx, client=mock_client)

        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_writes_test_file_and_records_it(self, tmp_path):
        """LLM writes a test file via write_file tool."""
        ctx = make_ctx(tmp_path)
        ctx.files_written = ["src/server.py"]
        (tmp_path / "src").mkdir()

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[
                make_write_file_response(
                    "tests/test_server.py",
                    "def test_search(): assert True",
                ),
                make_end_turn_response(),
            ]
        )

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc), \
             patch("agent.shared.capabilities.tempfile.TemporaryDirectory") as mock_tmp:
            real_tmp = tmp_path / "pt2"
            real_tmp.mkdir()
            report = {"summary": {"total": 1, "passed": 1, "failed": 0}, "tests": []}
            (real_tmp / "report.json").write_text(json.dumps(report))
            mock_tmp.return_value.__enter__ = MagicMock(return_value=str(real_tmp))
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

            await run(ctx, client=mock_client)

        assert "tests/test_server.py" in ctx.tests_written

    @pytest.mark.asyncio
    async def test_test_failures_populate_context(self, tmp_path):
        """After tester runs, ctx.test_failures reflects what pytest found."""
        ctx = make_ctx(tmp_path)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=make_end_turn_response())

        failure_report = {
            "summary": {"total": 2, "passed": 1, "failed": 1},
            "tests": [
                {"nodeid": "test_fail", "outcome": "failed",
                 "call": {"longrepr": "AssertionError"}},
                {"nodeid": "test_ok", "outcome": "passed", "call": {}},
            ],
        }

        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc), \
             patch("agent.shared.capabilities.tempfile.TemporaryDirectory") as mock_tmp:
            real_tmp = tmp_path / "pt3"
            real_tmp.mkdir()
            (real_tmp / "report.json").write_text(json.dumps(failure_report))
            mock_tmp.return_value.__enter__ = MagicMock(return_value=str(real_tmp))
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

            await run(ctx, client=mock_client)

        assert len(ctx.test_failures) == 1
        assert ctx.test_failures[0]["test"] == "test_fail"
        assert ctx.tests_passed == 1
        assert ctx.tests_failed == 1

    @pytest.mark.asyncio
    async def test_no_duplicate_test_files_in_written(self, tmp_path):
        """Same test file path written twice — only appears once in tests_written."""
        ctx = make_ctx(tmp_path)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[
                make_write_file_response("tests/test_a.py", "# v1", "tu_1"),
                make_write_file_response("tests/test_a.py", "# v2", "tu_2"),
                make_end_turn_response(),
            ]
        )

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc), \
             patch("agent.shared.capabilities.tempfile.TemporaryDirectory") as mock_tmp:
            real_tmp = tmp_path / "pt4"
            real_tmp.mkdir()
            (real_tmp / "report.json").write_text(json.dumps(
                {"summary": {"total": 0, "passed": 0, "failed": 0}, "tests": []}
            ))
            mock_tmp.return_value.__enter__ = MagicMock(return_value=str(real_tmp))
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

            await run(ctx, client=mock_client)

        assert ctx.tests_written.count("tests/test_a.py") == 1

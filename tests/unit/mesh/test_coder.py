"""Unit tests for agent/mesh/coder.py — ReAct loop implementation."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.mesh.coder import _build_messages, _build_system, _dispatch, run
from agent.shared.run_context import RunContext


def make_ctx(tmp_path, **kwargs) -> RunContext:
    return RunContext(
        run_id="coder-test",
        intent_spec={
            "raw_goal": "build an MCP server",
            "build_target": "mcp_server",
            "deploy_target": "fly.io",
            "integrations": ["perplexity"],
        },
        output_dir=str(tmp_path),
        architecture_spec={
            "file_tree": ["src/server.py", "tests/test_server.py"],
            "module_interfaces": {"server": {"input": "query: str", "output": "SearchResult"}},
            "tech_choices": {"framework": "fastmcp", "search": "perplexity-api"},
        },
        **kwargs,
    )


def make_end_turn_response() -> MagicMock:
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = []
    return response


def make_tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "tu_1") -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
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

    def test_includes_deploy_target(self, tmp_path):
        ctx = make_ctx(tmp_path)
        system = _build_system(ctx)
        assert "fly.io" in system

    def test_includes_tech_choices(self, tmp_path):
        ctx = make_ctx(tmp_path)
        system = _build_system(ctx)
        assert "fastmcp" in system

    def test_includes_instructions(self, tmp_path):
        ctx = make_ctx(tmp_path)
        system = _build_system(ctx)
        assert "write" in system.lower() or "Write" in system


class TestBuildMessages:
    def test_round_one_no_errors_is_start_message(self, tmp_path):
        ctx = make_ctx(tmp_path)
        ctx.coder_rounds = 1
        messages = _build_messages(ctx)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        text = messages[0]["content"][0]["text"]
        assert "Round 1" in text

    def test_round_two_with_lint_errors_includes_errors(self, tmp_path):
        ctx = make_ctx(tmp_path)
        ctx.coder_rounds = 2
        ctx.lint_errors = [{"code": "F401", "message": "unused import", "row": 1, "filename": "src/server.py"}]
        messages = _build_messages(ctx)
        text = messages[0]["content"][0]["text"]
        assert "lint" in text.lower() or "Lint" in text
        assert "F401" in text

    def test_test_failures_included_in_message(self, tmp_path):
        ctx = make_ctx(tmp_path)
        ctx.coder_rounds = 2
        ctx.test_failures = [{"test": "test_search", "error": "AssertionError: expected 200"}]
        messages = _build_messages(ctx)
        text = messages[0]["content"][0]["text"]
        assert "test_search" in text


class TestDispatch:
    @pytest.mark.asyncio
    async def test_write_file_writes_to_context(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        result = await _dispatch(
            "write_file",
            {"path": "src/server.py", "content": "# server"},
            ctx,
            mock_client,
        )
        assert "src/server.py" in ctx.file_contents
        assert "Written" in result

    @pytest.mark.asyncio
    async def test_read_file_returns_cached_content(self, tmp_path):
        ctx = make_ctx(tmp_path)
        ctx.file_contents["src/server.py"] = "# cached content"
        mock_client = AsyncMock()
        result = await _dispatch(
            "read_file",
            {"path": "src/server.py"},
            ctx,
            mock_client,
        )
        assert "cached content" in result

    @pytest.mark.asyncio
    async def test_read_file_missing_returns_error(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        result = await _dispatch(
            "read_file",
            {"path": "nonexistent.py"},
            ctx,
            mock_client,
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_run_lint_passing_returns_success_message(self, tmp_path):
        ctx = make_ctx(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "server.py").write_text("x = 1\n")
        mock_client = AsyncMock()

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "[]"
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc):
            result = await _dispatch(
                "run_lint",
                {"files": ["src/server.py"]},
                ctx,
                mock_client,
            )

        assert "passed" in result.lower()

    @pytest.mark.asyncio
    async def test_run_tests_passing_returns_count(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()

        import json as _json, tempfile as _tempfile
        report = {
            "summary": {"total": 5, "passed": 5, "failed": 0},
            "tests": [],
        }

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with patch("agent.shared.capabilities.subprocess.run", return_value=fake_proc), \
             patch("agent.shared.capabilities.tempfile.TemporaryDirectory") as mock_tmp:
            real_tmp = tmp_path / "pytest_dispatch"
            real_tmp.mkdir()
            (real_tmp / "report.json").write_text(_json.dumps(report))
            mock_tmp.return_value.__enter__ = MagicMock(return_value=str(real_tmp))
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

            result = await _dispatch("run_tests", {}, ctx, mock_client)

        assert "5/5" in result or "passed" in result.lower()

    @pytest.mark.asyncio
    async def test_fill_knowledge_gap_dispatched(self, tmp_path):
        ctx = make_ctx(tmp_path)
        (tmp_path / "fastmcp.md").write_text("# fastmcp docs")
        # Write the skill file so fill_knowledge_gap fast-paths
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "fastmcp.md").write_text("# fastmcp\n\nTool registration docs.")

        ctx2 = RunContext(
            run_id="coder-test",
            intent_spec=ctx.intent_spec,
            output_dir=str(tmp_path),
            skills_dir=str(skills_dir),
        )

        mock_client = AsyncMock()
        result = await _dispatch(
            "fill_knowledge_gap",
            {"domain": "fastmcp", "question": "how to register tools"},
            ctx2,
            mock_client,
        )
        assert "fastmcp" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        result = await _dispatch("unknown_tool", {}, ctx, mock_client)
        assert "Unknown" in result


class TestCoderRun:
    @pytest.mark.asyncio
    async def test_end_turn_immediately_returns(self, tmp_path):
        """Coder exits cleanly when model immediately returns end_turn."""
        ctx = make_ctx(tmp_path)
        ctx.coder_rounds = 1

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=make_end_turn_response())

        await run(ctx, client=mock_client)
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_use_then_end_turn(self, tmp_path):
        """Coder calls a tool, then ends — two API calls total."""
        ctx = make_ctx(tmp_path)
        ctx.coder_rounds = 1
        (tmp_path / "src").mkdir()

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[
                make_tool_use_response(
                    "write_file",
                    {"path": "src/server.py", "content": "# server"},
                ),
                make_end_turn_response(),
            ]
        )

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "[]"
        fake_proc.stderr = ""

        await run(ctx, client=mock_client)
        assert mock_client.messages.create.call_count == 2
        assert "src/server.py" in ctx.file_contents

    @pytest.mark.asyncio
    async def test_unexpected_stop_reason_exits_loop(self, tmp_path):
        ctx = make_ctx(tmp_path)
        ctx.coder_rounds = 1

        weird_response = MagicMock()
        weird_response.stop_reason = "max_tokens"
        weird_response.content = []

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=weird_response)

        # Should not raise, should exit
        await run(ctx, client=mock_client)
        mock_client.messages.create.assert_called_once()

"""Unit tests for agent/mesh/planner.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.mesh.planner import (
    PlanSpec,
    _build_prompt,
    run,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ARCHITECTURE = {
    "file_tree": ["src/server.py", "src/search.py", "tests/test_server.py", "requirements.txt"],
    "module_interfaces": {
        "server": {
            "description": "FastAPI app entry point",
            "input": "query: str",
            "output": "SearchResponse",
        },
        "search": {
            "description": "Perplexity search client",
            "input": "query: str",
            "output": "list[str]",
        },
    },
    "dependencies": {
        "server": ["search"],
        "search": [],
    },
    "tech_choices": {
        "web_framework": "fastapi",
        "search_client": "perplexity-api",
        "deployment": "fly.io",
    },
}

SAMPLE_FILE_PLANS = {
    "src/server.py": {
        "description": "FastAPI application entry point",
        "imports": ["from fastapi import FastAPI", "from .search import SearchClient"],
        "constants": ["PORT = 8080"],
        "classes": [],
        "functions": [
            {
                "name": "handle_search",
                "signature": "async def handle_search(query: str) -> dict",
                "docstring": "Handle search requests and return results",
            }
        ],
        "notes": "Entry point — call uvicorn.run here",
    },
    "src/search.py": {
        "description": "Perplexity search client wrapper",
        "imports": ["import httpx"],
        "constants": [],
        "classes": [
            {
                "name": "SearchClient",
                "bases": [],
                "docstring": "Client for Perplexity search API",
                "methods": [
                    {
                        "name": "search",
                        "signature": "async def search(self, query: str) -> list[str]",
                        "docstring": "Execute a search query and return results",
                    }
                ],
            }
        ],
        "functions": [],
        "notes": "Must export SearchClient",
    },
    "tests/test_server.py": {
        "description": "Unit tests for server module",
        "imports": ["import pytest", "from src.server import handle_search"],
        "constants": [],
        "classes": [],
        "functions": [
            {
                "name": "test_handle_search_returns_dict",
                "signature": "async def test_handle_search_returns_dict()",
                "docstring": "Verify handle_search returns a dict",
            }
        ],
        "notes": "pytest async tests",
    },
    "requirements.txt": {
        "description": "Python dependencies",
        "imports": [],
        "constants": [],
        "classes": [],
        "functions": [],
        "notes": "Plain text file — list fastapi, uvicorn, httpx",
    },
}


def make_tool_use_response(file_plans: dict) -> MagicMock:
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {
        "file_plans": file_plans,
        "entry_point": "src/server.py",
        "test_strategy": "Unit test each handler in isolation with mocked clients.",
    }

    response = MagicMock()
    response.content = [tool_block]
    return response


def make_no_tool_response() -> MagicMock:
    text_block = MagicMock()
    text_block.type = "text"

    response = MagicMock()
    response.content = [text_block]
    return response


# ---------------------------------------------------------------------------
# _build_prompt tests
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_includes_raw_goal(self, sample_intent_spec):
        prompt = _build_prompt(sample_intent_spec, SAMPLE_ARCHITECTURE)
        assert "MCP server" in prompt or "Perplexity" in prompt

    def test_includes_all_files(self, sample_intent_spec):
        prompt = _build_prompt(sample_intent_spec, SAMPLE_ARCHITECTURE)
        for path in SAMPLE_ARCHITECTURE["file_tree"]:
            assert path in prompt

    def test_includes_tech_choices(self, sample_intent_spec):
        prompt = _build_prompt(sample_intent_spec, SAMPLE_ARCHITECTURE)
        assert "fastapi" in prompt
        assert "perplexity-api" in prompt

    def test_includes_module_interfaces(self, sample_intent_spec):
        prompt = _build_prompt(sample_intent_spec, SAMPLE_ARCHITECTURE)
        assert "server" in prompt
        assert "search" in prompt

    def test_empty_architecture_still_builds(self, sample_intent_spec):
        prompt = _build_prompt(sample_intent_spec, {"file_tree": ["main.py"], "module_interfaces": {}, "tech_choices": {}, "dependencies": {}})
        assert "main.py" in prompt


# ---------------------------------------------------------------------------
# run() tests
# ---------------------------------------------------------------------------


class TestPlannerRun:
    @pytest.mark.asyncio
    async def test_returns_plan_spec_shape(self, sample_intent_spec):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_use_response(SAMPLE_FILE_PLANS)
        )

        result = await run(sample_intent_spec, SAMPLE_ARCHITECTURE, client=mock_client)

        assert "file_plans" in result
        assert "entry_point" in result
        assert "test_strategy" in result

    @pytest.mark.asyncio
    async def test_file_plans_is_dict(self, sample_intent_spec):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_use_response(SAMPLE_FILE_PLANS)
        )

        result = await run(sample_intent_spec, SAMPLE_ARCHITECTURE, client=mock_client)

        assert isinstance(result["file_plans"], dict)

    @pytest.mark.asyncio
    async def test_entry_point_is_string(self, sample_intent_spec):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_use_response(SAMPLE_FILE_PLANS)
        )

        result = await run(sample_intent_spec, SAMPLE_ARCHITECTURE, client=mock_client)

        assert isinstance(result["entry_point"], str)
        assert result["entry_point"] == "src/server.py"

    @pytest.mark.asyncio
    async def test_empty_intent_raises_value_error(self):
        mock_client = AsyncMock()
        with pytest.raises(ValueError, match="intent_spec is empty"):
            await run({}, SAMPLE_ARCHITECTURE, client=mock_client)

    @pytest.mark.asyncio
    async def test_empty_architecture_raises_value_error(self, sample_intent_spec):
        mock_client = AsyncMock()
        with pytest.raises(ValueError, match="architecture_spec is empty"):
            await run(sample_intent_spec, {}, client=mock_client)

    @pytest.mark.asyncio
    async def test_empty_file_tree_raises_value_error(self, sample_intent_spec):
        mock_client = AsyncMock()
        arch = {**SAMPLE_ARCHITECTURE, "file_tree": []}
        with pytest.raises(ValueError, match="file_tree is empty"):
            await run(sample_intent_spec, arch, client=mock_client)

    @pytest.mark.asyncio
    async def test_missing_raw_goal_raises_key_error(self):
        mock_client = AsyncMock()
        bad_intent = {"build_target": "mcp_server"}
        with pytest.raises(KeyError):
            await run(bad_intent, SAMPLE_ARCHITECTURE, client=mock_client)

    @pytest.mark.asyncio
    async def test_no_tool_call_raises_runtime_error(self, sample_intent_spec):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_no_tool_response()
        )
        with pytest.raises(RuntimeError, match="did not call define_file_plans"):
            await run(sample_intent_spec, SAMPLE_ARCHITECTURE, client=mock_client)

    @pytest.mark.asyncio
    async def test_uses_forced_tool_choice(self, sample_intent_spec):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_use_response(SAMPLE_FILE_PLANS)
        )

        await run(sample_intent_spec, SAMPLE_ARCHITECTURE, client=mock_client)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["tool_choice"] == {"type": "tool", "name": "define_file_plans"}

    @pytest.mark.asyncio
    async def test_file_plans_contain_expected_keys(self, sample_intent_spec):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_use_response(SAMPLE_FILE_PLANS)
        )

        result = await run(sample_intent_spec, SAMPLE_ARCHITECTURE, client=mock_client)

        for _path, fp in result["file_plans"].items():
            assert "description" in fp
            assert "imports" in fp
            assert "functions" in fp or "classes" in fp

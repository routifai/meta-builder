"""Unit tests for agent/mesh/critic.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.mesh.critic import (
    MIN_BLOCK_CONFIDENCE,
    evaluate_code,
    evaluate_plan,
    evaluate_tests,
)


def make_tool_response(decision: str, confidence: float = 0.9, **kwargs) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = {
        "decision": decision,
        "confidence": confidence,
        "issues": kwargs.get("issues", []),
        "revision_instructions": kwargs.get("revision_instructions", ""),
        "score": kwargs.get("score", 80.0),
    }
    response = MagicMock()
    response.content = [block]
    return response


def make_intent_spec() -> dict:
    return {
        "raw_goal": "build an MCP server for Perplexity search",
        "build_target": "mcp_server",
        "deploy_target": "fly.io",
    }


def make_plan_spec() -> dict:
    return {
        "file_plans": {
            "src/server.py": {
                "description": "Main MCP server",
                "functions": [{"name": "search", "signature": "def search(query: str) -> str", "docstring": "Search via Perplexity"}],
                "classes": [],
                "imports": [],
                "constants": [],
                "notes": "",
            }
        },
        "entry_point": "src/server.py",
        "test_strategy": "Unit test each handler",
    }


def make_arch_spec() -> dict:
    return {
        "file_tree": ["src/server.py", "tests/test_server.py"],
        "module_interfaces": {"server": {"input": "query", "output": "result"}},
        "tech_choices": {"framework": "fastmcp"},
    }


class TestEvaluatePlan:
    @pytest.mark.asyncio
    async def test_approve_returned(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response("approve", score=85.0)
        )
        result = await evaluate_plan(
            make_plan_spec(), make_arch_spec(), make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "approve"
        assert result["score"] == 85.0

    @pytest.mark.asyncio
    async def test_revise_returned_with_instructions(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response(
                "revise",
                confidence=0.88,
                revision_instructions="Add tests/test_server.py to file_plans",
                issues=[{"type": "missing_file", "message": "Test file missing", "severity": "critical"}],
                score=55.0,
            )
        )
        result = await evaluate_plan(
            make_plan_spec(), make_arch_spec(), make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "revise"
        assert "test_server.py" in result["revision_instructions"]
        assert result["score"] == 55.0

    @pytest.mark.asyncio
    async def test_block_with_high_confidence(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response(
                "block",
                confidence=0.95,  # above MIN_BLOCK_CONFIDENCE
                revision_instructions="Architecture is fundamentally wrong",
                score=10.0,
            )
        )
        result = await evaluate_plan(
            make_plan_spec(), make_arch_spec(), make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "block"

    @pytest.mark.asyncio
    async def test_block_with_low_confidence_becomes_revise(self):
        """Low confidence blocks are downgraded to revise."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response(
                "block",
                confidence=MIN_BLOCK_CONFIDENCE - 0.1,  # below threshold
            )
        )
        result = await evaluate_plan(
            make_plan_spec(), make_arch_spec(), make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "revise"

    @pytest.mark.asyncio
    async def test_no_tool_call_returns_approve_fallback(self):
        """If model doesn't call evaluate_output, return approve with low confidence."""
        mock_client = AsyncMock()
        response = MagicMock()
        response.content = []
        mock_client.messages.create = AsyncMock(return_value=response)

        result = await evaluate_plan(
            make_plan_spec(), make_arch_spec(), make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "approve"
        assert result["confidence"] == 0.3


class TestEvaluateCode:
    @pytest.mark.asyncio
    async def test_approve_clean_code(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response("approve", score=82.0)
        )
        file_contents = {
            "src/server.py": "import os\n\ndef search(query: str) -> str:\n    return query\n"
        }
        result = await evaluate_code(
            file_contents, make_plan_spec(), make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "approve"

    @pytest.mark.asyncio
    async def test_revise_hardcoded_secret(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response(
                "revise",
                issues=[{
                    "type": "hardcoded_secret",
                    "message": "API_KEY = 'sk-...' is hardcoded",
                    "severity": "critical",
                }],
                revision_instructions="Read API_KEY from os.environ instead",
                score=30.0,
            )
        )
        file_contents = {
            "src/server.py": "API_KEY = 'sk-hardcoded'\n"
        }
        result = await evaluate_code(
            file_contents, make_plan_spec(), make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "revise"
        assert any(i["type"] == "hardcoded_secret" for i in result["issues"])

    @pytest.mark.asyncio
    async def test_file_previews_capped(self):
        """Large files should be truncated before sending to LLM."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response("approve")
        )
        # 100 lines — should be truncated to 40
        big_file = "\n".join(f"line_{i} = {i}" for i in range(100))
        file_contents = {"src/big.py": big_file}

        await evaluate_code(file_contents, make_plan_spec(), make_intent_spec(),
                            client=mock_client)

        call_args = mock_client.messages.create.call_args
        prompt_content = str(call_args)
        # The truncation note should appear in the prompt
        assert "more lines" in prompt_content


class TestEvaluateTests:
    @pytest.mark.asyncio
    async def test_no_tests_written_returns_revise(self):
        """No test files → immediately revise without LLM call."""
        mock_client = AsyncMock()
        result = await evaluate_tests(
            file_contents={},
            tests_written=[],
            intent_spec=make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "revise"
        assert result["confidence"] == 0.95
        mock_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_approve_meaningful_tests(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response("approve", score=88.0)
        )
        file_contents = {
            "tests/test_server.py": (
                "def test_search_returns_result():\n"
                "    assert search('query') == 'result'\n\n"
                "def test_search_empty_raises():\n"
                "    with pytest.raises(ValueError):\n"
                "        search('')\n"
            )
        }
        result = await evaluate_tests(
            file_contents=file_contents,
            tests_written=["tests/test_server.py"],
            intent_spec=make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "approve"

    @pytest.mark.asyncio
    async def test_revise_trivial_tests(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response(
                "revise",
                issues=[{
                    "type": "trivial_assertions",
                    "message": "Tests only contain assert True",
                    "severity": "critical",
                }],
                revision_instructions="Add meaningful assertions checking actual return values",
                score=20.0,
            )
        )
        file_contents = {
            "tests/test_server.py": "def test_search():\n    assert True\n"
        }
        result = await evaluate_tests(
            file_contents=file_contents,
            tests_written=["tests/test_server.py"],
            intent_spec=make_intent_spec(),
            client=mock_client,
        )
        assert result["decision"] == "revise"
        assert any(i["type"] == "trivial_assertions" for i in result["issues"])

    @pytest.mark.asyncio
    async def test_result_fields_present(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response("approve")
        )
        file_contents = {"tests/test_x.py": "def test_x(): assert 1 == 1"}
        result = await evaluate_tests(
            file_contents=file_contents,
            tests_written=["tests/test_x.py"],
            intent_spec=make_intent_spec(),
            client=mock_client,
        )
        assert "decision" in result
        assert "confidence" in result
        assert "issues" in result
        assert "revision_instructions" in result
        assert "score" in result

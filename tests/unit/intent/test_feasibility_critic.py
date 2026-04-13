"""Unit tests for agent/intent/feasibility_critic.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.intent.feasibility_critic import (
    FeasibilityResult,
    _build_prompt,
    evaluate,
)


def make_tool_response(decision: str, confidence: float = 0.9, **kwargs) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = {
        "decision": decision,
        "confidence": confidence,
        "issues": kwargs.get("issues", []),
        "refined_goal": kwargs.get("refined_goal"),
        "suggestions": kwargs.get("suggestions", []),
        "reasoning": kwargs.get("reasoning", "Test reasoning."),
    }

    response = MagicMock()
    response.content = [block]
    return response


class TestBuildPrompt:
    def test_includes_raw_goal(self):
        spec = {"raw_goal": "build a search API", "build_target": "api"}
        prompt = _build_prompt(spec)
        assert "build a search API" in prompt

    def test_includes_build_target(self):
        spec = {"raw_goal": "build X", "build_target": "mcp_server"}
        prompt = _build_prompt(spec)
        assert "mcp_server" in prompt

    def test_includes_must_ask_if_present(self):
        spec = {"raw_goal": "build X", "must_ask": ["deploy_target"]}
        prompt = _build_prompt(spec)
        assert "deploy_target" in prompt

    def test_minimal_spec_still_works(self):
        spec = {"raw_goal": "build a CLI tool"}
        prompt = _build_prompt(spec)
        assert "build a CLI tool" in prompt


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_proceed_decision_returned(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response("proceed", confidence=0.95)
        )
        spec = {"raw_goal": "build a todo API and deploy to fly.io"}
        result = await evaluate(spec, client=mock_client)

        assert result["decision"] == "proceed"
        assert result["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_block_decision_returned(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response(
                "block",
                confidence=0.92,
                issues=[{
                    "type": "physically_impossible",
                    "message": "Cannot send physical objects to Mars with software",
                    "severity": "critical",
                }],
                suggestions=["build mission planning software for Mars logistics"],
            )
        )
        spec = {"raw_goal": "build software that sends an apple to Mars"}
        result = await evaluate(spec, client=mock_client)

        assert result["decision"] == "block"
        assert len(result["issues"]) == 1
        assert result["issues"][0]["type"] == "physically_impossible"
        assert len(result["suggestions"]) == 1

    @pytest.mark.asyncio
    async def test_refine_decision_includes_refined_goal(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response(
                "refine",
                confidence=0.85,
                refined_goal="build a ride-booking API with drivers and riders",
                issues=[{
                    "type": "scope_too_large",
                    "message": "Full Uber clone is too large for single build",
                    "severity": "warning",
                }],
            )
        )
        spec = {"raw_goal": "build Uber"}
        result = await evaluate(spec, client=mock_client)

        assert result["decision"] == "refine"
        assert result["refined_goal"] == "build a ride-booking API with drivers and riders"

    @pytest.mark.asyncio
    async def test_empty_raw_goal_raises(self):
        mock_client = AsyncMock()
        spec = {"raw_goal": "  "}
        with pytest.raises(ValueError, match="raw_goal"):
            await evaluate(spec, client=mock_client)

    @pytest.mark.asyncio
    async def test_missing_tool_call_raises(self):
        mock_client = AsyncMock()
        response = MagicMock()
        response.content = []  # no tool_use block
        mock_client.messages.create = AsyncMock(return_value=response)

        spec = {"raw_goal": "build a search API"}
        with pytest.raises(RuntimeError, match="evaluate_feasibility"):
            await evaluate(spec, client=mock_client)

    @pytest.mark.asyncio
    async def test_confidence_preserved(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response("proceed", confidence=0.73)
        )
        spec = {"raw_goal": "build a simple CLI"}
        result = await evaluate(spec, client=mock_client)
        assert result["confidence"] == 0.73

    @pytest.mark.asyncio
    async def test_result_is_typed_dict(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_tool_response("proceed")
        )
        spec = {"raw_goal": "build an API"}
        result = await evaluate(spec, client=mock_client)

        assert "decision" in result
        assert "confidence" in result
        assert "issues" in result
        assert "refined_goal" in result
        assert "suggestions" in result
        assert "reasoning" in result

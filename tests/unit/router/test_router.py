"""Unit tests for agent/router/router.py"""
from __future__ import annotations

import pytest
from agent.router.router import route, RouterDecision
from agent.router.scorer import AUTO_MERGE_THRESHOLD


@pytest.fixture
def high_confidence_score():
    return {"confidence": 92.0, "risk_dimensions": {}, "breakdown": {}}


@pytest.fixture
def low_confidence_score():
    return {"confidence": 60.0, "risk_dimensions": {"coverage": "medium"}, "breakdown": {}}


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 13")
class TestRouter:
    @pytest.mark.asyncio
    async def test_returns_router_decision_shape(self, high_confidence_score, sample_intent_spec):
        result = await route(high_confidence_score, sample_intent_spec)
        assert "action" in result
        assert "reason" in result
        assert "pr_merged" in result
        assert "notification_sent" in result

    @pytest.mark.asyncio
    async def test_high_confidence_with_automerge_enabled_auto_merges(
        self, high_confidence_score, sample_intent_spec
    ):
        sample_intent_spec["auto_merge_if_ci_green"] = True
        result = await route(high_confidence_score, sample_intent_spec)
        assert result["action"] == "auto_merge"

    @pytest.mark.asyncio
    async def test_low_confidence_sends_async_ping(
        self, low_confidence_score, sample_intent_spec
    ):
        result = await route(low_confidence_score, sample_intent_spec)
        assert result["action"] == "async_ping"

    @pytest.mark.asyncio
    async def test_automerge_disabled_never_auto_merges(
        self, high_confidence_score, sample_intent_spec
    ):
        sample_intent_spec["auto_merge_if_ci_green"] = False
        result = await route(high_confidence_score, sample_intent_spec)
        assert result["action"] != "auto_merge"

    @pytest.mark.asyncio
    async def test_action_is_valid_literal(self, high_confidence_score, sample_intent_spec):
        result = await route(high_confidence_score, sample_intent_spec)
        assert result["action"] in ("auto_merge", "async_ping", "hold")

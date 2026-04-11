"""Unit tests for agent/intent/ambiguity_scorer.py"""
from __future__ import annotations

import pytest
from agent.intent.ambiguity_scorer import score_unknowns, MUST_ASK_THRESHOLD


@pytest.fixture
def parsed_goal_with_unknowns():
    return {
        "raw_goal": "build something",
        "domains": ["unknown-domain"],
        "entities": {
            "build_target": None,
            "integrations": [],
            "deploy_target": None,
        },
        "unknown_fields": ["build_target", "deploy_target"],
    }


@pytest.fixture
def parsed_goal_clear():
    return {
        "raw_goal": "build an MCP server for Perplexity and deploy to fly.io",
        "domains": ["mcp-protocol", "perplexity-api", "fly-workers"],
        "entities": {
            "build_target": "mcp-server",
            "integrations": ["perplexity"],
            "deploy_target": "fly.io",
        },
        "unknown_fields": [],
    }


class TestScoreUnknowns:
    def test_returns_scored_unknowns_shape(self, parsed_goal_with_unknowns):
        result = score_unknowns(parsed_goal_with_unknowns)
        assert "scores" in result
        assert "must_ask" in result
        assert "can_default" in result

    def test_scores_are_floats_between_0_and_1(self, parsed_goal_with_unknowns):
        result = score_unknowns(parsed_goal_with_unknowns)
        for field, score in result["scores"].items():
            assert 0.0 <= score <= 1.0, f"{field} score out of range: {score}"

    def test_must_ask_fields_above_threshold(self, parsed_goal_with_unknowns):
        result = score_unknowns(parsed_goal_with_unknowns)
        for field in result["must_ask"]:
            assert result["scores"][field] >= MUST_ASK_THRESHOLD

    def test_can_default_fields_below_threshold(self, parsed_goal_with_unknowns):
        result = score_unknowns(parsed_goal_with_unknowns)
        for field in result["can_default"]:
            assert result["scores"][field] < MUST_ASK_THRESHOLD

    def test_clear_goal_has_no_must_ask(self, parsed_goal_clear):
        result = score_unknowns(parsed_goal_clear)
        assert result["must_ask"] == []

    def test_must_ask_and_can_default_are_disjoint(self, parsed_goal_with_unknowns):
        result = score_unknowns(parsed_goal_with_unknowns)
        overlap = set(result["must_ask"]) & set(result["can_default"])
        assert overlap == set()

    def test_empty_parsed_goal_does_not_crash(self):
        result = score_unknowns({"raw_goal": "", "domains": [], "entities": {}, "unknown_fields": []})
        assert isinstance(result, dict)

    def test_bad_input_missing_keys_raises(self):
        with pytest.raises((KeyError, ValueError, Exception)):
            score_unknowns({})

"""Unit tests for agent/intent/defaults_agent.py"""
from __future__ import annotations

import pytest
from agent.intent.defaults_agent import fill_defaults, HumanInputRequired
from agent.shared.intent_spec import REQUIRED_FIELDS


@pytest.fixture
def parsed_goal():
    return {
        "raw_goal": "build an MCP server for Perplexity search and deploy to fly.io",
        "domains": ["mcp-protocol", "perplexity-api", "fly-workers"],
        "entities": {
            "build_target": "mcp-server",
            "integrations": ["perplexity"],
            "deploy_target": "fly.io",
        },
        "unknown_fields": [],
    }


@pytest.fixture
def scored_all_defaultable():
    return {
        "scores": {"llm_model": 0.1, "risk_tolerance": 0.2},
        "must_ask": [],
        "can_default": ["llm_model", "risk_tolerance"],
    }


@pytest.fixture
def scored_with_must_ask():
    return {
        "scores": {"api_key_location": 0.9},
        "must_ask": ["api_key_location"],
        "can_default": [],
    }


class TestFillDefaults:
    def test_happy_path_returns_intent_spec(self, parsed_goal, scored_all_defaultable):
        result = fill_defaults(scored_all_defaultable, parsed_goal)
        for field in REQUIRED_FIELDS:
            assert field in result, f"Missing: {field}"

    def test_must_ask_raises_human_input_required(self, parsed_goal, scored_with_must_ask):
        with pytest.raises(HumanInputRequired) as exc_info:
            fill_defaults(scored_with_must_ask, parsed_goal)
        assert "api_key_location" in exc_info.value.fields

    def test_defaults_applied_for_can_default_fields(self, parsed_goal, scored_all_defaultable):
        result = fill_defaults(scored_all_defaultable, parsed_goal)
        assert result["llm_model"] in ("claude-sonnet-4-6", "claude-opus-4-6")

    def test_run_id_is_generated(self, parsed_goal, scored_all_defaultable):
        result = fill_defaults(scored_all_defaultable, parsed_goal)
        assert isinstance(result["run_id"], str)
        assert len(result["run_id"]) > 0

    def test_created_at_is_iso_timestamp(self, parsed_goal, scored_all_defaultable):
        result = fill_defaults(scored_all_defaultable, parsed_goal)
        from datetime import datetime
        datetime.fromisoformat(result["created_at"])   # raises if invalid

    def test_output_schema_matches_intent_spec(self, parsed_goal, scored_all_defaultable):
        result = fill_defaults(scored_all_defaultable, parsed_goal)
        assert result["risk_tolerance"] in ("lean", "stable")
        assert result["notification_preference"] in ("blocked_only", "async", "never")
        assert isinstance(result["auto_merge_if_ci_green"], bool)

    def test_human_input_required_contains_all_must_ask_fields(self, parsed_goal):
        scored = {
            "scores": {"field_a": 0.95, "field_b": 0.85},
            "must_ask": ["field_a", "field_b"],
            "can_default": [],
        }
        with pytest.raises(HumanInputRequired) as exc_info:
            fill_defaults(scored, parsed_goal)
        assert set(exc_info.value.fields) == {"field_a", "field_b"}

"""Unit tests for agent/intent/prompt_parser.py"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from agent.intent.prompt_parser import parse_prompt, ParsedGoal


# ---------------------------------------------------------------------------
# Mock factory — returns a fake Anthropic client whose messages.create()
# returns a canned tool_use response for a given extracted result.
# ---------------------------------------------------------------------------

def _make_mock_client(extracted: dict):
    """Build a mock Anthropic client that returns `extracted` as the tool_use input."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = extracted

    response = MagicMock()
    response.content = [tool_block]

    client = MagicMock()
    client.messages.create.return_value = response
    return client


MCP_EXTRACTED = {
    "build_target": "mcp-server",
    "integrations": ["perplexity"],
    "deploy_target": None,   # "prod" maps to None per schema
    "domains": ["mcp-protocol", "perplexity-api", "fly-workers"],
    "unknown_fields": [],
}

LIBRARY_EXTRACTED = {
    "build_target": "python-library",
    "integrations": [],
    "deploy_target": None,
    "domains": ["python"],
    "unknown_fields": [],
}

VAGUE_EXTRACTED = {
    "build_target": None,
    "integrations": [],
    "deploy_target": None,
    "domains": [],
    "unknown_fields": ["build_target"],
}

MULTI_INTEGRATION_EXTRACTED = {
    "build_target": "rest-api",
    "integrations": ["github", "slack"],
    "deploy_target": None,
    "domains": ["rest-api", "github-api", "slack-api"],
    "unknown_fields": [],
}

FLY_EXTRACTED = {
    "build_target": "mcp-server",
    "integrations": ["perplexity"],
    "deploy_target": "fly.io",
    "domains": ["mcp-protocol", "perplexity-api", "fly-workers"],
    "unknown_fields": [],
}


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 1")
class TestParsePromptSkipped:
    """Placeholder — remove skip when implementing."""
    pass


class TestParsePrompt:
    def test_returns_parsedgoal_shape(self):
        client = _make_mock_client(MCP_EXTRACTED)
        result = parse_prompt(
            "build an MCP server for Perplexity search and deploy to prod",
            client=client,
        )
        assert "raw_goal" in result
        assert "domains" in result
        assert "entities" in result
        assert "unknown_fields" in result

    def test_raw_goal_preserved(self):
        goal = "build an MCP server for Perplexity search and deploy to prod"
        client = _make_mock_client(MCP_EXTRACTED)
        result = parse_prompt(goal, client=client)
        assert result["raw_goal"] == goal

    def test_mcp_domain_detected(self):
        client = _make_mock_client(MCP_EXTRACTED)
        result = parse_prompt(
            "build an MCP server for Perplexity search and deploy to prod",
            client=client,
        )
        assert any("mcp" in d.lower() for d in result["domains"])

    def test_deploy_target_extracted(self):
        client = _make_mock_client(FLY_EXTRACTED)
        result = parse_prompt(
            "build an MCP server for Perplexity search and deploy to fly.io",
            client=client,
        )
        assert result["entities"]["deploy_target"] == "fly.io"

    def test_integration_extracted(self):
        client = _make_mock_client(MULTI_INTEGRATION_EXTRACTED)
        result = parse_prompt(
            "build a tool that integrates with GitHub and Slack",
            client=client,
        )
        integrations = result["entities"]["integrations"]
        assert isinstance(integrations, list)
        assert len(integrations) >= 1

    def test_domains_is_list_of_strings(self):
        client = _make_mock_client(LIBRARY_EXTRACTED)
        result = parse_prompt("build a REST API with postgres", client=client)
        assert isinstance(result["domains"], list)
        assert all(isinstance(d, str) for d in result["domains"])

    def test_entities_has_required_keys(self):
        client = _make_mock_client(VAGUE_EXTRACTED)
        result = parse_prompt("build something", client=client)
        assert "build_target" in result["entities"]
        assert "integrations" in result["entities"]
        assert "deploy_target" in result["entities"]

    def test_unknown_fields_is_list(self):
        client = _make_mock_client(VAGUE_EXTRACTED)
        result = parse_prompt("build something vague", client=client)
        assert isinstance(result["unknown_fields"], list)

    def test_empty_string_raises(self):
        client = _make_mock_client(MCP_EXTRACTED)
        with pytest.raises(ValueError):
            parse_prompt("", client=client)

    def test_whitespace_only_raises(self):
        client = _make_mock_client(MCP_EXTRACTED)
        with pytest.raises(ValueError):
            parse_prompt("   ", client=client)

    def test_very_long_input_does_not_crash(self):
        long_goal = "build " + "an MCP server " * 200
        client = _make_mock_client(MCP_EXTRACTED)
        result = parse_prompt(long_goal, client=client)
        assert "raw_goal" in result

    def test_no_deploy_mention_sets_deploy_target_none(self):
        client = _make_mock_client(LIBRARY_EXTRACTED)
        result = parse_prompt("build a python library for data parsing", client=client)
        assert result["entities"]["deploy_target"] is None

    def test_model_is_passed_to_api(self):
        """Model override is forwarded to messages.create."""
        client = _make_mock_client(MCP_EXTRACTED)
        parse_prompt("build something", client=client, model="claude-haiku-4-5-20251001")
        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_tool_choice_forces_tool_use(self):
        """tool_choice must force the model to call extract_goal_entities."""
        client = _make_mock_client(MCP_EXTRACTED)
        parse_prompt("build something", client=client)
        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["tool_choice"]["type"] == "tool"
        assert call_kwargs["tool_choice"]["name"] == "extract_goal_entities"

    def test_no_tool_block_raises_runtime_error(self):
        """If the model somehow returns no tool_use block, RuntimeError is raised."""
        response = MagicMock()
        response.content = []   # no tool_use block
        client = MagicMock()
        client.messages.create.return_value = response
        with pytest.raises(RuntimeError):
            parse_prompt("build something", client=client)

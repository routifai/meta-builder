"""Unit tests for agent/intent/requirement_closure.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.intent.requirement_closure import close, evaluate, _get_template


class TestGetTemplate:
    def test_mcp_server_exact_match(self):
        template = _get_template("mcp_server")
        assert "transport" in template

    def test_mcp_server_with_spaces(self):
        template = _get_template("mcp server")
        assert "transport" in template

    def test_web_app_exact(self):
        template = _get_template("web_app")
        assert "framework" in template

    def test_unknown_target_returns_empty(self):
        template = _get_template("completely_unknown_xyz")
        assert template == {}

    def test_ai_agent_target(self):
        template = _get_template("ai_agent")
        assert "llm_provider" in template
        assert "max_iterations" in template

    def test_partial_match_mcp(self):
        # "deepsearch_mcp" should match mcp_server template
        template = _get_template("deepsearch_mcp")
        assert "transport" in template


class TestClose:
    def test_complete_mcp_spec_returns_complete(self):
        spec = {
            "run_id": "abc",
            "raw_goal": "build an MCP server",
            "build_target": "mcp_server",
            "deploy_target": "fly.io",
            "integrations": ["perplexity"],
            "transport": "stdio",
            "auth_method": "api_key",
            "max_output_tokens": 4096,
        }
        result = close(spec)
        assert result["status"] == "complete"
        assert result["missing_fields"] == []

    def test_missing_deploy_target_gets_autofilled(self):
        spec = {
            "run_id": "abc",
            "raw_goal": "build a CLI",
            "build_target": "cli_tool",
        }
        result = close(spec)
        assert result["status"] == "complete"
        assert "deploy_target" in result["auto_filled"]
        assert result["final_spec"]["deploy_target"] == "fly.io"

    def test_mcp_transport_autofilled_with_default(self):
        spec = {
            "run_id": "abc",
            "raw_goal": "build MCP",
            "build_target": "mcp_server",
            "deploy_target": "fly.io",
            "auth_method": "api_key",
            "max_output_tokens": 4096,
        }
        result = close(spec)
        assert result["status"] == "complete"
        assert result["auto_filled"].get("transport") == "stdio"

    def test_web_app_missing_framework_needs_input(self):
        """web_app.framework has no safe default — must ask."""
        spec = {
            "run_id": "abc",
            "raw_goal": "build a web app",
            "build_target": "web_app",
            "deploy_target": "fly.io",
        }
        result = close(spec)
        assert result["status"] == "needs_input"
        assert "framework" in result["missing_fields"]
        assert len(result["questions"]) >= 1

    def test_final_spec_includes_autofilled_fields(self):
        spec = {
            "run_id": "abc",
            "raw_goal": "build an API",
            "build_target": "api",
        }
        result = close(spec)
        assert "deploy_target" in result["final_spec"]
        assert "framework" in result["final_spec"]

    def test_existing_fields_not_overwritten(self):
        spec = {
            "run_id": "abc",
            "raw_goal": "build an MCP server",
            "build_target": "mcp_server",
            "deploy_target": "aws",      # explicit, not the default
            "transport": "sse",          # explicit, not the default
            "auth_method": "oauth2",
            "max_output_tokens": 8192,
        }
        result = close(spec)
        assert result["final_spec"]["deploy_target"] == "aws"
        assert result["final_spec"]["transport"] == "sse"

    def test_unknown_build_target_uses_universal_only(self):
        spec = {
            "run_id": "abc",
            "raw_goal": "build something unusual",
            "build_target": "custom_unique_thing",
            "deploy_target": "fly.io",
        }
        result = close(spec)
        # Only universal fields checked — deploy_target present → complete
        assert result["status"] == "complete"

    def test_empty_string_deploy_target_gets_autofilled(self):
        spec = {
            "run_id": "abc",
            "raw_goal": "build a CLI",
            "build_target": "cli_tool",
            "deploy_target": "",
        }
        result = close(spec)
        assert result["final_spec"]["deploy_target"] == "fly.io"

    def test_questions_mention_field_options(self):
        spec = {
            "run_id": "abc",
            "raw_goal": "build a web app",
            "build_target": "web_app",
            "deploy_target": "fly.io",
        }
        result = close(spec)
        assert result["status"] == "needs_input"
        # At least one question should mention options
        all_questions = " ".join(result["questions"])
        assert "fastapi" in all_questions.lower() or "flask" in all_questions.lower()


class TestEvaluateWithLLM:
    @pytest.mark.asyncio
    async def test_complete_spec_skips_llm(self):
        """Template check passes → LLM is still called for enrichment."""
        mock_client = AsyncMock()

        # Set up LLM to return no additional_missing fields
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.input = {
            "additional_missing": [],
            "assessment": "All required fields present.",
        }
        response = MagicMock()
        response.content = [tool_block]
        mock_client.messages.create = AsyncMock(return_value=response)

        spec = {
            "run_id": "abc",
            "raw_goal": "build an MCP server for Perplexity",
            "build_target": "mcp_server",
            "deploy_target": "fly.io",
            "transport": "stdio",
            "auth_method": "api_key",
            "max_output_tokens": 4096,
        }
        result = await evaluate(spec, client=mock_client)
        assert result["status"] == "complete"

    @pytest.mark.asyncio
    async def test_needs_input_skips_llm(self):
        """Template check finds needs_input → returns immediately without LLM."""
        mock_client = AsyncMock()
        spec = {
            "run_id": "abc",
            "raw_goal": "build a web app",
            "build_target": "web_app",
            "deploy_target": "fly.io",
        }
        result = await evaluate(spec, client=mock_client)
        # LLM should NOT be called when template already finds needs_input
        mock_client.messages.create.assert_not_called()
        assert result["status"] == "needs_input"

    @pytest.mark.asyncio
    async def test_llm_additional_missing_adds_questions(self):
        """LLM identifies a domain-specific missing field not in template."""
        mock_client = AsyncMock()

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.input = {
            "additional_missing": [
                {
                    "field": "search_provider",
                    "description": "Which search API provider to use",
                    "safe_default": "",  # no safe default
                    "question": "Which search provider? (tavily, perplexity, google)",
                }
            ],
            "assessment": "Missing search provider specification.",
        }
        response = MagicMock()
        response.content = [tool_block]
        mock_client.messages.create = AsyncMock(return_value=response)

        spec = {
            "run_id": "abc",
            "raw_goal": "build a deepsearch MCP server",
            "build_target": "mcp_server",
            "deploy_target": "fly.io",
            "transport": "stdio",
            "auth_method": "api_key",
            "max_output_tokens": 4096,
        }
        result = await evaluate(spec, client=mock_client)
        assert result["status"] == "needs_input"
        assert "search_provider" in result["missing_fields"]
        assert any("search" in q.lower() for q in result["questions"])

    @pytest.mark.asyncio
    async def test_llm_safe_default_auto_fills(self):
        """LLM identifies missing field but provides safe default → auto-fill."""
        mock_client = AsyncMock()

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.input = {
            "additional_missing": [
                {
                    "field": "timeout_seconds",
                    "description": "Request timeout",
                    "safe_default": "30",
                    "question": "What timeout?",
                }
            ],
            "assessment": "Timeout not specified.",
        }
        response = MagicMock()
        response.content = [tool_block]
        mock_client.messages.create = AsyncMock(return_value=response)

        spec = {
            "run_id": "abc",
            "raw_goal": "build an MCP server",
            "build_target": "mcp_server",
            "deploy_target": "fly.io",
            "transport": "stdio",
            "auth_method": "api_key",
            "max_output_tokens": 4096,
        }
        result = await evaluate(spec, client=mock_client)
        assert result["status"] == "complete"
        assert result["auto_filled"].get("timeout_seconds") == "30"

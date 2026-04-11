"""Shared fixtures for all tests."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from dotenv import load_dotenv

# Load .env so ANTHROPIC_API_KEY is available for integration tests
# that call the real API. Unit tests inject mock clients and are unaffected.
load_dotenv()


@pytest.fixture
def sample_intent_spec() -> dict:
    return {
        "raw_goal": "build an MCP server for Perplexity search and deploy to prod",
        "build_target": "mcp-server",
        "integrations": ["perplexity"],
        "deploy_target": "fly.io",
        "llm_provider": "anthropic",
        "llm_model": "claude-sonnet-4-6",
        "llm_base_url": None,
        "risk_tolerance": "stable",
        "auto_merge_if_ci_green": True,
        "notification_preference": "async",
        "run_id": "test-run-001",
        "created_at": "2026-04-10T00:00:00Z",
    }


@pytest.fixture
def mock_redis():
    """Mock Redis client with common methods pre-configured."""
    client = AsyncMock()
    client.hset = AsyncMock(return_value=1)
    client.hgetall = AsyncMock(return_value={})
    client.hexists = AsyncMock(return_value=False)
    client.hincrby = AsyncMock(return_value=1)
    client.pipeline = MagicMock(return_value=AsyncMock())
    client.publish = AsyncMock(return_value=1)
    client.set = AsyncMock(return_value=True)
    client.get = AsyncMock(return_value=None)
    client.expire = AsyncMock(return_value=True)
    return client


@pytest.fixture
def run_id() -> str:
    return "test-run-001"

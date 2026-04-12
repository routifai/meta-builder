"""Unit tests for agent/monitor/context_builder.py"""
from __future__ import annotations

import pytest
from agent.monitor.context_builder import build, FixContext


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 17")
class TestContextBuilder:
    @pytest.mark.asyncio
    async def test_returns_fix_context_shape(self):
        anomaly = {"type": "bug", "priority": "high", "run_id": "r1",
                   "source_event": {"sample_errors": ["ImportError: module not found"]}}
        result = await build(anomaly)
        assert "stack_trace" in result
        assert "relevant_skills" in result
        assert "relevant_files" in result
        assert "run_id" in result
        assert "anomaly" in result

    @pytest.mark.asyncio
    async def test_relevant_skills_is_list_of_strings(self):
        anomaly = {"type": "bug", "priority": "high", "run_id": "r1", "source_event": {}}
        result = await build(anomaly)
        assert isinstance(result["relevant_skills"], list)

    @pytest.mark.asyncio
    async def test_run_id_propagated(self):
        anomaly = {"type": "bug", "priority": "high", "run_id": "r1", "source_event": {}}
        result = await build(anomaly)
        assert result["run_id"] == "r1"

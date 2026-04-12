"""Unit tests for agent/router/signal_collector.py"""
from __future__ import annotations

import pytest
from agent.router.signal_collector import collect, SignalBundle


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 11")
class TestSignalCollector:
    @pytest.mark.asyncio
    async def test_returns_signal_bundle_shape(self, run_id):
        result = await collect(run_id)
        assert "ci_passed" in result
        assert "smoke_tests_passed" in result
        assert "coverage_pct" in result
        assert "lint_passed" in result
        assert "type_check_passed" in result
        assert "test_failures" in result
        assert "deploy_succeeded" in result

    @pytest.mark.asyncio
    async def test_coverage_pct_is_float(self, run_id):
        result = await collect(run_id)
        assert isinstance(result["coverage_pct"], float)

    @pytest.mark.asyncio
    async def test_test_failures_is_list(self, run_id):
        result = await collect(run_id)
        assert isinstance(result["test_failures"], list)

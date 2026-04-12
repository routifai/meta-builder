"""Unit tests for agent/monitor/anomaly_classifier.py"""
from __future__ import annotations

import pytest
from agent.monitor.anomaly_classifier import classify, ClassifiedAnomaly


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 16")
class TestAnomalyClassifier:
    @pytest.mark.asyncio
    async def test_returns_classified_anomaly_shape(self):
        event = {
            "event": "anomaly_detected",
            "run_id": "r1",
            "service": "api",
            "error_rate": 0.15,
            "window_seconds": 60,
            "sample_errors": ["NullPointerException"],
            "timestamp": "2026-04-10T00:00:00Z",
        }
        result = await classify(event)
        assert "type" in result
        assert "priority" in result
        assert "run_id" in result
        assert "source_event" in result

    @pytest.mark.asyncio
    async def test_type_is_valid_literal(self):
        event = {"event": "anomaly_detected", "run_id": "r1", "service": "api",
                 "error_rate": 0.5, "window_seconds": 60, "sample_errors": [], "timestamp": ""}
        result = await classify(event)
        assert result["type"] in ("bug", "config", "infra", "regression")

    @pytest.mark.asyncio
    async def test_priority_is_valid_literal(self):
        event = {"event": "anomaly_detected", "run_id": "r1", "service": "api",
                 "error_rate": 0.5, "window_seconds": 60, "sample_errors": [], "timestamp": ""}
        result = await classify(event)
        assert result["priority"] in ("critical", "high", "medium", "low")

    @pytest.mark.asyncio
    async def test_high_error_rate_is_critical(self):
        event = {"event": "anomaly_detected", "run_id": "r1", "service": "api",
                 "error_rate": 0.9, "window_seconds": 60, "sample_errors": [], "timestamp": ""}
        result = await classify(event)
        assert result["priority"] in ("critical", "high")

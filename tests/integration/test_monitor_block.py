"""Integration test: monitor + fix loop wired together."""
from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 21")
class TestMonitorBlock:
    @pytest.mark.asyncio
    async def test_anomaly_event_to_fix_pr(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from agent.monitor.anomaly_classifier import classify
        from agent.monitor.context_builder import build
        from agent.monitor.fix_agent import run as fix_run
        from agent.monitor.validator import validate
        from agent.monitor.skills_updater import update

        event = {
            "event": "anomaly_detected", "run_id": "r1", "service": "api",
            "error_rate": 0.2, "window_seconds": 60,
            "sample_errors": ["KeyError: 'model'"], "timestamp": "2026-04-10T00:00:00Z",
        }
        classified = await classify(event)
        context = await build(classified)
        fix = await fix_run(context)
        validation = await validate(fix, "r1")
        update_result = await update(fix, classified)

        assert fix["pr_url"]
        assert update_result["skills_updated"] or update_result["new_entries"] is not None

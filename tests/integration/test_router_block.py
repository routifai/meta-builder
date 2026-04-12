"""Integration test: all 3 router agents wired together."""
from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 14")
class TestRouterBlock:
    @pytest.mark.asyncio
    async def test_signal_to_route_decision(self, run_id, sample_intent_spec):
        from agent.router.signal_collector import collect
        from agent.router.scorer import score
        from agent.router.router import route

        signals = await collect(run_id)
        scored = score(signals)
        decision = await route(scored, sample_intent_spec)

        assert decision["action"] in ("auto_merge", "async_ping", "hold")

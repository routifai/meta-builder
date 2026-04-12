"""End-to-end integration test: intent spec in → prod deploy decision out."""
from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 22")
class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_goal_to_router_decision(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".agent").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "decision-log").mkdir()

        from agent.intent.prompt_parser import parse_prompt
        from agent.intent.ambiguity_scorer import score_unknowns
        from agent.intent.defaults_agent import fill_defaults
        import asyncio
        from agent.mesh.researcher import run as researcher_run
        from agent.mesh.architect import run as architect_run
        from agent.mesh.coder import run as coder_run
        from agent.mesh.tester import run as tester_run
        from agent.mesh.deployer import run as deployer_run
        from agent.router.signal_collector import collect
        from agent.router.scorer import score
        from agent.router.router import route

        raw = "build an MCP server for Perplexity search and deploy to fly.io"
        parsed = parse_prompt(raw)
        scored = score_unknowns(parsed)
        spec = fill_defaults(scored, parsed)

        research, arch = await asyncio.gather(
            researcher_run(spec),
            architect_run(spec, {}),
        )
        coder_result, tester_result, deployer_result = await asyncio.gather(
            coder_run(arch, spec),
            tester_run(arch, spec),
            deployer_run(spec, arch),
        )

        signals = await collect(spec["run_id"])
        score_result = score(signals)
        decision = await route(score_result, spec)

        assert decision["action"] in ("auto_merge", "async_ping", "hold")

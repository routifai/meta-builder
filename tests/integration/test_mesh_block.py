"""Integration test: all mesh agents wired together."""
from __future__ import annotations

import pytest


class TestMeshBlock:
    @pytest.mark.asyncio
    async def test_mesh_agents_run_concurrently(self, sample_intent_spec):
        import asyncio
        from agent.mesh.researcher import run as researcher_run
        from agent.mesh.architect import run as architect_run

        research, arch = await asyncio.gather(
            researcher_run(sample_intent_spec),
            architect_run(sample_intent_spec, {}),
        )
        assert research["recommended_stack"]
        assert arch["file_tree"]

"""Unit tests for agent/mesh/deployer.py"""
from __future__ import annotations

import pytest
from agent.mesh.deployer import run, DeployerResult


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 9")
class TestDeployer:
    @pytest.mark.asyncio
    async def test_returns_deployer_result_shape(self, sample_intent_spec):
        arch = {"file_tree": [], "module_interfaces": {}, "dependencies": {}, "tech_choices": {}}
        result = await run(sample_intent_spec, arch)
        assert "dockerfile_path" in result
        assert "workflow_paths" in result
        assert "staging_url" in result
        assert "smoke_tests_passed" in result
        assert "secrets_injected" in result

    @pytest.mark.asyncio
    async def test_dockerfile_path_is_string(self, sample_intent_spec):
        arch = {"file_tree": [], "module_interfaces": {}, "dependencies": {}, "tech_choices": {}}
        result = await run(sample_intent_spec, arch)
        assert isinstance(result["dockerfile_path"], str)

    @pytest.mark.asyncio
    async def test_secrets_injected_contains_no_values(self, sample_intent_spec):
        """Secrets list should contain names only, never actual secret values."""
        arch = {"file_tree": [], "module_interfaces": {}, "dependencies": {}, "tech_choices": {}}
        result = await run(sample_intent_spec, arch)
        for secret_name in result["secrets_injected"]:
            assert not secret_name.startswith("sk-")
            assert not secret_name.startswith("ghp_")
